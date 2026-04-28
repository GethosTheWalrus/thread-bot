# ThreadBot — OpenCode Instructions

## Project Structure
```
docker-compose.yml          # Dev orchestration: postgres, temporal, temporal-ui, redis, backend, worker, frontend
backend/                    # Python/FastAPI + Temporal worker
  app/
    main.py                 # FastAPI app, lifespan, CORS, health endpoint
    worker.py               # Temporal worker: registers RunThreadWorkflow + 8 activities
    workflows/thread_workflow.py  # Orchestrator: get_messages → compact_history → call_llm → save_message → auto-title → publish_done
    api/routes.py           # REST endpoints at /api/* (threads, chat, settings, stream reconnect); Redis pub/sub streaming
    models/models.py        # SQLAlchemy: Thread (self-referencing FK) + Message (JSONB metadata_) + MCPServer + Setting (key-value)
    models/schemas.py       # Pydantic v2 schemas (ThreadResponse includes is_generating)
    config.py               # Singleton Settings + update_settings() for runtime overrides + load_settings_from_db(); REDIS_URL, REDIS_DB
    database/               # Async SQLAlchemy engine, session factory, get_db dependency, CRUD
    activities/llm_activities.py  # Temporal activities (lazy DB imports inside functions)
    mcp_helper.py           # Auto-detect Docker vs K8s, build StdioServerParameters for MCP containers
  config/dynamicconfig/     # Temporal dynamic config YAML
frontend/                   # Flutter web app (dark theme, Material 3)
  lib/
    main.dart               # App entry — MaterialApp with ThreadBotApp
    services/api_service.dart       # API calls + reconnectStream
    models/message.dart     # Message model (mutable content for streaming)
    models/thread.dart      # Thread (with isGenerating) + ThreadListItem models (mutable title for live updates)
    screens/chat_screen.dart  # Main chat: structured JSON event parsing, token streaming, placeholder management, stream reconnect
    screens/                # HomeScreen, ThreadListScreen, ThreadDetailScreen, SettingsScreen, MCPScreen
    widgets/chat_message_list.dart  # Message rendering: ChatBubble, ToolCallBubble, ToolCallChip (loading spinner, expandable I/O), ThinkingBubble, skeleton shimmer
    widgets/                # Sidebar, ChatInput, ThreadTreeView
  pubspec.yaml              # flutter_lints, http, flutter_markdown
docker/
  Dockerfile.frontend       # Two-stage: ubuntu+Flutter SDK clone → nginx:alpine, inline nginx config (includes /api/ proxy)
  init/01-init.sql          # Auto-init: threads + messages + settings tables with CASCADE FKs
k8s/                        # Production: namespace, configmap, rbac, deployments (backend x2, worker x1, frontend x2), services, ingress
```

## Key Architecture Facts
- **Thread model**: self-referencing FK (`parent_id`) for branching conversations. Displayed as a tree in UI.
- **Temporal workflow**: `RunThreadWorkflow` — orchestrates history fetching, token-aware compaction, tool execution loop, persistence, auto-title, and stream finalization. Order: `get_messages → compact_history → call_llm → save_message → auto-title → publish_title → publish_done`.
- **Token streaming**: The final LLM call uses `stream: true`. SSE chunks are parsed in `call_llm`, each token published to Redis as `{"type":"token","content":"..."}`. Non-streaming calls are used during tool iterations (need full `tool_calls` JSON). The frontend appends tokens progressively to a placeholder assistant message.
- **Redis pub/sub + event buffer**: Bridges the worker→backend gap for real-time streaming. The worker publishes structured JSON events to a per-request Redis channel AND appends them to a Redis list (`events:{channel}`). The backend subscribes before starting the workflow and relays events to the frontend via `StreamingResponse`. The event buffer list enables stream reconnect after page refresh. Redis is required because the worker and backend are separate processes/containers.
- **Stream reconnect**: When the user refreshes mid-generation, the frontend detects `is_generating: true` in the thread response, connects to `GET /api/threads/{id}/stream`, and replays all buffered events from the Redis list. A `generating:{thread_id}` Redis key (600s TTL) tracks active generation. `publish_done` clears it and sets the event list TTL to 60s.
- **Structured stream events**: `{"type":"thinking","content":"..."}`, `{"type":"tool_call","content":"...","tools":[...],"tool_calls":[...]}`, `{"type":"tool_result","tool":"...","content":"...","success":bool}`, `{"type":"token","content":"..."}`, `{"type":"title","content":"..."}`, `{"type":"text","content":"..."}` (fallback). `[DONE]` and `[ERROR]` are plain string sentinels.
- **Tool Persistence**: `tool_call` and `tool_result` are distinct roles in the DB. `get_messages` activity MUST reconstruct the OpenAI-compatible format (`assistant` role with `tool_calls` array and `tool` role for results) to maintain LLM context. `thinking` role is display-only and skipped during reconstruction.
- **Context Compaction**: When history exceeds a threshold, `compact_history` triggers. It summarizes older messages into a `system` message and deletes the originals. This keeps the prompt size manageable.
- **Auto-title**: Runs before `publish_done` so the title event arrives while the stream is still open. Publishes `{"type":"title","content":"..."}` to Redis so the sidebar updates instantly. No polling required.
- **Config**: Settings are persisted in a `settings` key-value table in PostgreSQL. On startup, `load_settings_from_db()` loads all rows into the in-memory `_overrides` dict. The `PATCH /api/settings` endpoint writes to both `_overrides` and the DB. Env vars (configmap) serve as defaults; DB values take precedence. The frontend no longer stores settings in SharedPreferences — it loads from and saves to the backend API exclusively.
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
- **Per-chip tool pulse** — Tool call pulse animation is per-chip (on `_ToolCallChip`), not per-bubble. A chip stops pulsing immediately when its result arrives. Each chip shows a loading spinner while waiting for its result. The bubble-level `_ToolCallBubble` has no animation.
- **Tool call `isLoading` detection** — `hasAssistantAfter` checks for assistant messages with non-empty content. The empty placeholder (`temp-ast-*` with empty content) is excluded so `isLoading` correctly evaluates to `true` during streaming.
- **Stream reconnect in frontend** — `_processStreamChunks` is a shared method used by both `_sendMessage` (live) and `_reconnectToStream` (page refresh). On reconnect, non-user/system messages are cleared from the list before replaying events from the buffer. The `skipHeader` flag skips `THREAD_ID:` parsing for reconnect (no header in reconnect stream).
- **Ollama URL** — Default is `host.docker.internal:11434` (Docker internal). Workers need network access to the Ollama instance. Configure via Settings screen (persisted to DB). Ollama must be installed and running on the host machine for chat to work.
- **K8s ingress** — Routes `/api` and `/health` to backend, `/` to frontend. Backend Service port is 80 (target 8000).
- **MCP infrastructure auto-detection** — `mcp_helper.py` checks for `/var/run/secrets/kubernetes.io/serviceaccount/token` to decide between Docker (`docker run -i`) and Kubernetes (`kubectl run --rm -i --quiet`). In K8s, full `os.environ` must be passed to `StdioServerParameters` so kubectl can find the API server.
- **MCP pod name collision** — `mcp_tools_map` stores `image`/`env_vars` instead of pre-built `StdioServerParameters`. Fresh params with unique pod names are generated per tool execution via `get_mcp_server_params()`.
- **K8s RBAC for MCP** — The `threadbot-sa` ServiceAccount needs a Role with permissions for `pods` (create/delete/get/list/watch), `pods/attach`, and `pods/log` in the threadbot namespace.
