# ThreadBot — OpenCode Instructions

## Project Structure
```
docker-compose.yml          # Dev orchestration: postgres, temporal, temporal-ui, backend, worker, frontend
backend/                    # Python/FastAPI + Temporal worker
  app/
    main.py                 # FastAPI app, lifespan, CORS, health endpoint
    worker.py               # Temporal worker: registers RunThreadWorkflow + 6 activities
    workflows/thread_workflow.py  # Orchestrator: get_messages → compact_history → call_llm → save_message(s)
    api/routes.py           # REST endpoints at /api/* (threads, chat, settings)
    models/models.py        # SQLAlchemy: Thread (self-referencing FK) + Message (JSONB metadata_)
    models/schemas.py       # Pydantic v2 schemas
    config.py               # Singleton Settings + update_settings() for runtime overrides
    database/               # Async SQLAlchemy engine, session factory, get_db dependency, CRUD
    activities/llm_activities.py  # Temporal activities (lazy DB imports inside functions)
  config/dynamicconfig/     # Temporal dynamic config YAML
frontend/                   # Flutter web app (dark theme, Material 3)
  lib/
    main.dart               # App entry — MaterialApp with ThreadBotApp
    services/api_service.dart       # API calls + SharedPreferences for LLM config
    screens/                # HomeScreen (IndexedStack + bottom nav), ThreadListScreen, ThreadDetailScreen, SettingsScreen
    widgets/                # ThreadListTile, MessageBubble, MessageInput, ThreadTreeView
  pubspec.yaml              # flutter_lints, http, shared_preferences, flutter_markdown
docker/
  Dockerfile.frontend       # Two-stage: ubuntu+Flutter SDK clone → nginx:alpine, inline nginx config
  init/01-init.sql          # Auto-init: threads + messages tables with CASCADE FKs
k8s/                        # Production: namespace, configmap, deployments (backend x2, worker x1, frontend x2), services, ingress
```

## Key Architecture Facts
- **Thread model**: self-referencing FK (`parent_id`) for branching conversations. Displayed as a tree in UI.
- **Temporal workflow**: `RunThreadWorkflow` — orchestrates history fetching, token-aware compaction, tool execution loop, and persistence. It ensures all tool interactions are saved as distinct messages.
- **Tool Persistence**: `tool_call` and `tool_result` are distinct roles in the DB. `get_messages` activity MUST reconstruct the OpenAI-compatible format (`assistant` role with `tool_calls` array and `tool` role for results) to maintain LLM context.
- **Context Compaction**: When history exceeds a threshold, `compact_history` triggers. It summarizes older messages into a `system` message and deletes the originals. This keeps the prompt size manageable.
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
- **Infrastructure Agnostic**: Support both local (Docker Compose) and external instances for Temporal and PostgreSQL via environment variables.
- **Context Awareness**: The LLM context must be managed via the token-aware compaction logic documented in `DESIGN.md`.

## Commands

### Run (Docker)
```bash
docker compose up --build    # All 6 services: postgres, temporal, temporal-ui, backend, worker, frontend
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
- **Frontend Docker nginx** — config is inline in Dockerfile, not a mounted file. Cache-Control: max-age=31536000 — browser caches JS aggressively. After rebuilding, use `docker cp` to update the container or hard-refresh browser (Ctrl+Shift+R).
- **Temporal + DB race condition** — `chat_endpoint` creates thread+message in a committed `AsyncSessionLocal()` before starting the workflow. The route's `get_db` session commits AFTER workflow completes. Never remove the committed session pattern.
- **Temporal sandbox** — Never import SQLAlchemy/uuid at module level in activity files. All DB imports must be inside the activity function body.
- **SQLAlchemy `metadata_`** — Column named `metadata_` (reserved name), Pydantic schema field stays `metadata` (auto-mapped via `from_attributes`).
- **`call_llm` Return Type** — Returns a `dict` with `content` (str) and `intermediate_messages` (list). DO NOT change this back to a raw string or tool persistence will break.
- **`get_messages` Reconstruction** — This activity is critical for "tool memory." It converts DB `tool_call`/`tool_result` rows back into the nested `assistant`/`tool` format expected by OpenAI/Ollama APIs.
- **Ollama URL** — Default is `host.docker.internal:11434` (Docker internal). Workers need network access to the Ollama instance. Configure via Settings screen. Ollama must be installed and running on the host machine for chat to work.
- **K8s ingress** — Routes `/api` and `/health` to backend, `/` to frontend. Backend Service port is 80 (target 8000).
