# ThreadBot — OpenCode Instructions

## Project Structure
```
docker-compose.yml          # Dev orchestration: postgres, temporal, temporal-ui, redis, backend, worker, frontend
backend/                    # Python/FastAPI + Temporal worker
  app/
    main.py                 # FastAPI app, lifespan, CORS, health endpoint
    worker.py               # Temporal worker: registers RunThreadWorkflow + 8 activities
    workflows/thread_workflow.py  # Orchestrator: get_messages → compact_history → call_llm → save_message → auto-title → publish_done
    api/routes.py           # REST endpoints at /api/* (threads, chat, settings); Redis pub/sub streaming
    models/models.py        # SQLAlchemy: Thread (self-referencing FK) + Message (JSONB metadata_) + MCPServer
    models/schemas.py       # Pydantic v2 schemas
    config.py               # Singleton Settings + update_settings() for runtime overrides; REDIS_URL, REDIS_DB
    database/               # Async SQLAlchemy engine, session factory, get_db dependency, CRUD
    activities/llm_activities.py  # Temporal activities (lazy DB imports inside functions)
  config/dynamicconfig/     # Temporal dynamic config YAML
frontend/                   # Flutter web app (dark theme, Material 3)
  lib/
    main.dart               # App entry — MaterialApp with ThreadBotApp
    services/api_service.dart       # API calls + SharedPreferences for LLM config
    models/message.dart     # Message model (mutable content for streaming)
    models/thread.dart      # Thread + ThreadListItem models (mutable title for live updates)
    screens/chat_screen.dart  # Main chat: structured JSON event parsing, token streaming, placeholder management
    screens/                # HomeScreen, ThreadListScreen, ThreadDetailScreen, SettingsScreen, MCPScreen
    widgets/chat_message_list.dart  # Message rendering: ChatBubble, ToolCallBubble, ToolCallChip, ThinkingBubble, skeleton shimmer
    widgets/                # Sidebar, ChatInput, ThreadTreeView
  pubspec.yaml              # flutter_lints, http, shared_preferences, flutter_markdown
docker/
  Dockerfile.frontend       # Two-stage: ubuntu+Flutter SDK clone → nginx:alpine, inline nginx config (includes /api/ proxy)
  init/01-init.sql          # Auto-init: threads + messages tables with CASCADE FKs
k8s/                        # Production: namespace, configmap, deployments (backend x2, worker x1, frontend x2), services, ingress
```

## Key Architecture Facts
- **Thread model**: self-referencing FK (`parent_id`) for branching conversations. Displayed as a tree in UI.
- **Temporal workflow**: `RunThreadWorkflow` — orchestrates history fetching, token-aware compaction, tool execution loop, persistence, auto-title, and stream finalization. Order: `get_messages → compact_history → call_llm → save_message → auto-title → publish_title → publish_done`.
- **Token streaming**: The final LLM call uses `stream: true`. SSE chunks are parsed in `call_llm`, each token published to Redis as `{"type":"token","content":"..."}`. Non-streaming calls are used during tool iterations (need full `tool_calls` JSON). The frontend appends tokens progressively to a placeholder assistant message.
- **Redis pub/sub**: Bridges the worker→backend gap for real-time streaming. The worker publishes structured JSON events to a per-request Redis channel. The backend subscribes before starting the workflow and relays events to the frontend via `StreamingResponse`. Redis is required because the worker and backend are separate processes/containers.
- **Structured stream events**: `{"type":"thinking","content":"..."}`, `{"type":"tool_call","content":"...","tools":[...]}`, `{"type":"tool_result","tool":"...","content":"...","success":bool}`, `{"type":"token","content":"..."}`, `{"type":"title","content":"..."}`, `{"type":"text","content":"..."}` (fallback). `[DONE]` and `[ERROR]` are plain string sentinels.
- **Tool Persistence**: `tool_call` and `tool_result` are distinct roles in the DB. `get_messages` activity MUST reconstruct the OpenAI-compatible format (`assistant` role with `tool_calls` array and `tool` role for results) to maintain LLM context. `thinking` role is display-only and skipped during reconstruction.
- **Context Compaction**: When history exceeds a threshold, `compact_history` triggers. It summarizes older messages into a `system` message and deletes the originals. This keeps the prompt size manageable.
- **Auto-title**: Runs before `publish_done` so the title event arrives while the stream is still open. Publishes `{"type":"title","content":"..."}` to Redis so the sidebar updates instantly. No polling required.
- **Config**: Runtime-overridable via `update_settings()` — LLM config, MCP servers, and compaction limits can be changed via UI.
- **Frontend state**: Per-screen StatefulWidget with local state + `ApiService`. No singleton provider, no `provider` package. Each screen creates its own `ApiService()` instance and manages state via `setState()`.
- **DB**: Async SQLAlchemy 2.0 with `asyncpg`. `expire_on_commit=False`, `autoflush=False`. Always use explicit queries or `selectinload` — lazy loading after commit raises `MissingGreenlet`.
- **Temporal SDK v1.8+**: Workflows must be classes decorated with `@defn`, with `@run` method. Activities use `@activity.defn`. DB imports must be inside function bodies (Temporal sandbox blocks SQLAlchemy imports at module level).

## Coding Principles
- **Simplicity First**: Prioritize simplicity and brevity over cleverness. Avoid over-engineering.
- **File Integrity**: Do not overload single files. Maintain clean boundaries between API, Workflows, Activities, and Database layers.
- **Conventional Commits**: Use conventional commit messages for clarity.
- **Optimistic UI**: The frontend should feel responsive. Use optimistic updates for message sending.

## Core Requirements
- **Explicit Inputs**: All data required for workflow execution (URLs, models, keys) MUST be passed as input arguments to the workflow. Never rely on module-level environment variables inside activities.
- **Infrastructure Agnostic**: Support both local (Docker Compose) and external instances for Temporal, PostgreSQL, and Redis via environment variables.
- **Context Awareness**: The LLM context must be managed via the token-aware compaction logic documented in `DESIGN.md`.

## Commands

### Run (Docker)
```bash
docker compose up --build    # All 7 services: postgres, temporal, temporal-ui, redis, backend, worker, frontend
docker compose logs -f backend   # Stream backend logs
docker compose logs -f worker    # Stream worker logs (workflow execution)
```

### Frontend Dev (local Flutter)
```bash
cd frontend
flutter pub get
flutter build web --release          # Build web artifacts to build/web/
# Manual deploy to container:
docker cp build/web temporal-chat-bot-frontend-1:/usr/share/nginx/html/
```

### Backend Dev (local)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload        # Dev server on localhost:8000
```

### Lint / Analyze
```bash
cd frontend
flutter analyze
flutter test                           # Widget tests (only 1 test: widget_test.dart)
```

### Verify Health
```bash
curl http://localhost:8000/health           # Backend health
curl http://localhost:3000                   # Frontend (nginx SPA)
curl http://localhost:8088                   # Temporal UI
```

## Gotchas
- **No `provider` package or singleton provider in frontend** — state is managed locally in each StatefulWidget via `setState()`. Do NOT create global provider instances or use `ChangeNotifier` as a shared state holder.
- **Flutter master branch** — uses aggressive dart2js tree-shaking. Top-level singleton variables and their methods are stripped unless called from recognized lifecycle entry points (`initState` + `addPostFrameCallback`). Per-screen state via `setState()` is never tree-shaken.
- **Frontend Docker build** — uses `ubuntu:24.04` + cloned Flutter SDK (no official `flutter` Docker image exists). Flutter SDK path is `/usr/local/flutter`.
- **Frontend Docker nginx** — config is inline in Dockerfile, not a mounted file. Includes `/api/` and `/health` reverse proxy blocks to the backend. Cache-Control: max-age=31536000 — browser caches JS aggressively. After rebuilding, use `docker cp` to update the container or hard-refresh browser (Ctrl+Shift+R).
- **Redis pub/sub race condition** — `chat_endpoint` subscribes to the Redis channel BEFORE starting the Temporal workflow. Redis pub/sub doesn't buffer — if the worker publishes before subscription, messages (including `[DONE]`) are lost and the stream hangs forever.
- **`[DONE]` must be sent after DB persistence** — `publish_done` is a separate activity called after `save_message` and `auto-title`. The frontend reloads from DB on `[DONE]`, so all data must be persisted first.
- **Temporal + DB race condition** — `chat_endpoint` creates thread+message in a committed `AsyncSessionLocal()` before starting the workflow. The route's `get_db` session commits AFTER workflow completes. Never remove the committed session pattern.
- **Temporal sandbox** — Never import SQLAlchemy/uuid at module level in activity files. All DB imports must be inside the activity function body.
- **SQLAlchemy `metadata_`** — Column named `metadata_` (reserved name), Pydantic schema field stays `metadata` (auto-mapped via `from_attributes`).
- **`call_llm` Return Type** — Returns a `dict` with `content` (str), `used_tools` (bool), and `iterations` (int). DO NOT change this back to a raw string or tool persistence will break.
- **`call_llm` Streaming** — Uses `stream: true` only for the final LLM response (no tool calls). Tool iterations use non-streaming calls to get the full `tool_calls` JSON array. If the streaming call fails, falls back to the non-streaming response already received.
- **`get_messages` Reconstruction** — This activity is critical for "tool memory." It converts DB `tool_call`/`tool_result` rows back into the nested `assistant`/`tool` format expected by OpenAI/Ollama APIs. It skips `thinking` role messages (display-only).
- **Placeholder assistant message** — The frontend creates a `temp-ast-*` placeholder on send. Intermediate events (thinking, tool_call, tool_result) are inserted before it. Token events append to its content. The placeholder is never removed during streaming — it becomes the real message content. On `[DONE]`, a silent DB reload replaces temp messages with persisted ones.
- **Per-chip tool pulse** — Tool call pulse animation is per-chip (on `_ToolCallChip`), not per-bubble. A chip stops pulsing immediately when its result arrives. The bubble-level `_ToolCallBubble` has no animation.
- **Ollama URL** — Default is `host.docker.internal:11434` (Docker internal). Workers need network access to the Ollama instance. Configure via Settings screen. Ollama must be installed and running on the host machine for chat to work.
- **K8s ingress** — Routes `/api` and `/health` to backend, `/` to frontend. Backend Service port is 80 (target 8000).
- **MCP containers use `host.docker.internal`** — MCP Docker containers connect to host services via `--add-host=host.docker.internal:host-gateway`. They are NOT added to the Docker Compose network.
