# ThreadBot — OpenCode Instructions

## Project Structure
```
docker-compose.yml          # Dev orchestration: postgres, temporal, temporal-ui, redis, backend, worker, frontend
backend/                    # Python/FastAPI + Temporal worker
  app/
    main.py                 # FastAPI app, lifespan, CORS, health endpoint
    worker.py               # Temporal worker: registers RunThreadWorkflow + 12 activities
    workflows/thread_workflow.py  # Orchestrator: get_messages → compact_history → discover_tools → loop { llm_turn → execute_tools } → stream_response → save_message → auto-title → publish_done
    api/routes.py           # REST endpoints at /api/* (threads, chat, settings, MCP, tool overrides, stream reconnect); Redis pub/sub streaming
    models/models.py        # SQLAlchemy: Thread, Message, MCPServer (encrypted env_vars/args, cached_tools), ThreadToolOverride, Setting
    models/schemas.py       # Pydantic v2 schemas (ThreadResponse, ToolOverridesResponse, MCPServerResponse, etc.)
    config.py               # Singleton Settings + update_settings() for runtime overrides + load_settings_from_db(); REDIS_URL, REDIS_DB
    database/               # Async SQLAlchemy engine, session factory, get_db dependency, CRUD (18 functions)
    activities/llm_activities.py  # Temporal activities (lazy DB imports inside functions)
    encryption.py           # Fernet encryption/decryption for MCP secrets (env_vars, args)
    mcp_helper.py           # Auto-detect Docker vs K8s, build StdioServerParameters for MCP containers
  config/dynamicconfig/     # Temporal dynamic config YAML
  Dockerfile                # python:3.12-slim + Docker CLI + kubectl
  requirements.txt          # FastAPI, SQLAlchemy, temporalio, redis, mcp, cryptography, etc.
frontend/                   # Flutter web app (dark theme, Material 3)
  lib/
    main.dart               # App entry — MaterialApp, dark theme, Google Fonts (Inter), seed color #8B5CF6
    services/api_service.dart       # API calls + reconnectStream, base URL auto-detection
    models/message.dart     # Message model (mutable content for streaming)
    models/thread.dart      # Thread (with isGenerating) + ThreadListItem models (mutable title for live updates)
    models/mcp_server.dart  # MCPServer model
    screens/chat_screen.dart  # Main chat: JSON event parsing, token streaming, placeholder management, stream reconnect, tool overrides bottom sheet
    screens/settings_screen.dart  # LLM config, context management, tool result truncation settings
    screens/mcp_screen.dart       # MCP server CRUD, test connection, KV pair editor for env vars/args
    widgets/chat_message_list.dart  # Message rendering: ChatBubble, ToolCallChip (pulse, spinner, expandable I/O), ThinkingBubble, CompactionDivider, ResponseTimeline, skeleton shimmer
    widgets/sidebar.dart    # Thread list sidebar, date-grouped, rename/delete, nav to Settings/MCP
    widgets/chat_input.dart # Text input with send button, tools (wrench) button, context donut chart
  pubspec.yaml              # http, intl, flutter_markdown, url_launcher, google_fonts
docker/
  Dockerfile.frontend       # Two-stage: ubuntu+Flutter SDK clone → nginx:alpine, inline nginx config (includes /api/ proxy)
  init/01-init.sql          # Auto-init: threads, messages, mcp_servers, settings, thread_tool_overrides tables
k8s/                        # Production: namespace, configmap, rbac, deployments, services, proxy, LB, MCP cleanup CronJob
deploy.sh                   # Interactive K8s deploy script: configmap generation, multi-arch builds, manifest apply
```

## Key Architecture Facts
- **Thread model**: self-referencing FK (`parent_id`) for branching conversations. Displayed as a tree in UI.
- **Temporal workflow**: `RunThreadWorkflow` — orchestrates history fetching, token-aware compaction, tool execution loop, persistence, auto-title, and stream finalization. Order: `get_messages → compact_history → discover_tools → loop { llm_turn → execute_tools } → stream_response → save_message → auto-title → publish_title → publish_done`.
- **Token streaming**: The final LLM call uses `stream: true`. SSE chunks are parsed in `stream_response`, each token published to Redis as `{"type":"token","content":"..."}`. Non-streaming calls are used during tool iterations (need full `tool_calls` JSON). The frontend appends tokens progressively to a placeholder assistant message.
- **Redis pub/sub + event buffer**: Bridges the worker→backend gap for real-time streaming. The worker publishes structured JSON events to a per-request Redis channel AND appends them to a Redis list (`events:{channel}`). The backend subscribes before starting the workflow and relays events to the frontend via `StreamingResponse`. The event buffer list enables stream reconnect after page refresh. Redis is required because the worker and backend are separate processes/containers.
- **Stream reconnect**: When the user refreshes mid-generation, the frontend detects `is_generating: true` in the thread response, connects to `GET /api/threads/{id}/stream`, and replays all buffered events from the Redis list. A `generating:{thread_id}` Redis key (600s TTL) tracks active generation. `publish_done` clears it and sets the event list TTL to 60s.
- **Structured stream events**: `{"type":"thinking","content":"..."}`, `{"type":"tool_call","content":"...","tools":[...],"tool_calls":[...]}`, `{"type":"tool_result","tool":"...","content":"...","success":bool}`, `{"type":"token","content":"..."}`, `{"type":"title","content":"..."}`, `{"type":"compaction","content":"...","compacted_count":N}`, `{"type":"context","estimated_tokens":N,"context_window":N}`, `{"type":"text","content":"..."}` (fallback). `[DONE]` and `[ERROR]` are plain string sentinels.
- **Tool Persistence**: `tool_call` and `tool_result` are distinct roles in the DB. `get_messages` activity MUST reconstruct the OpenAI-compatible format (`assistant` role with `tool_calls` array and `tool` role for results) to maintain LLM context. `thinking` role is display-only and skipped during reconstruction.
- **Context Compaction**: When history exceeds a threshold, `compact_history` triggers. It summarizes older messages into a `system` message and deletes the originals. This keeps the prompt size manageable.
- **Auto-title**: Runs before `publish_done` so the title event arrives while the stream is still open. Publishes `{"type":"title","content":"..."}` to Redis so the sidebar updates instantly. No polling required. Triggers on the first exchange and then every 5th message.
- **Config**: Settings are persisted in a `settings` key-value table in PostgreSQL. On startup, `load_settings_from_db()` loads all rows into the in-memory `_overrides` dict. The `PATCH /api/settings` endpoint writes to both `_overrides` and the DB. Env vars (configmap) serve as defaults; DB values take precedence. The frontend no longer stores settings in SharedPreferences — it loads from and saves to the backend API exclusively.
- **Frontend state**: Per-screen StatefulWidget with local state + `ApiService`. No singleton provider, no `provider` package. Each screen creates its own `ApiService()` instance and manages state via `setState()`.
- **DB**: Async SQLAlchemy 2.0 with `asyncpg`. `expire_on_commit=False`, `autoflush=False`. Always use explicit queries or `selectinload` — lazy loading after commit raises `MissingGreenlet`.
- **Temporal SDK v1.8+**: Workflows must be classes decorated with `@defn`, with `@run` method. Activities use `@activity.defn`. DB imports must be inside function bodies (Temporal sandbox blocks SQLAlchemy imports at module level).
- **Per-thread tool overrides**: Users can enable/disable individual MCP tools or entire servers on a per-thread basis via a wrench icon in the chat input. Overrides are stored in the `thread_tool_overrides` table. Tool-level overrides take precedence over server-level. No rows = all enabled (default).
- **MCP tool caching**: Discovered tools are cached in the `cached_tools` JSONB column on `mcp_servers`. Populated by the test endpoint (`POST /mcp/{id}/test`) and by `discover_tools` during the first chat. The `GET /tool-overrides` endpoint reads from the cache — it does NOT spin up MCP containers.
- **Tool result truncation**: Configurable via `LLM_TOOL_RESULT_MAX_CHARS` setting (default 0 = no truncation). When enabled, only the LLM context is truncated; the full result is saved to DB and streamed to the frontend. Truncated results include an LLM-aware notice: `[TRUNCATED — result was X chars, showing first Y. Consider using more specific parameters.]`.

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
curl http://localhost:8080                   # Temporal UI
```

## Gotchas
- **No `provider` package or singleton provider in frontend** — state is managed locally in each StatefulWidget via `setState()`. Do NOT create global provider instances or use `ChangeNotifier` as a shared state holder.
- **Flutter master branch** — uses aggressive dart2js tree-shaking. Top-level singleton variables and their methods are stripped unless called from recognized lifecycle entry points (`initState` + `addPostFrameCallback`). Per-screen state via `setState()` is never tree-shaken.
- **Only 3 screens exist**: `ChatScreen`, `SettingsScreen`, `MCPScreen`. There is no `HomeScreen`, `ThreadListScreen`, `ThreadDetailScreen`, or `ThreadTreeView`.
- **Frontend Docker build** — uses `ubuntu:24.04` + cloned Flutter SDK (no official `flutter` Docker image exists). Flutter SDK path is `/usr/local/flutter`. Build context is `./frontend`.
- **Frontend Docker nginx** — config is inline in Dockerfile, not a mounted file. Includes `/api/` and `/health` reverse proxy blocks to the backend. Cache-Control: max-age=31536000 — browser caches JS aggressively. After rebuilding, use `docker cp` to update the container or hard-refresh browser (Ctrl+Shift+R).
- **Redis pub/sub race condition** — `chat_endpoint` subscribes to the Redis channel BEFORE starting the Temporal workflow. Redis pub/sub doesn't buffer — if the worker publishes before subscription, messages (including `[DONE]`) are lost and the stream hangs forever.
- **`[DONE]` must be sent after DB persistence** — `publish_done` is a separate activity called after `save_message` and `auto-title`. The frontend reloads from DB on `[DONE]`, so all data must be persisted first.
- **Temporal + DB race condition** — `chat_endpoint` creates thread+message in a committed `AsyncSessionLocal()` before starting the workflow. The route's `get_db` session commits AFTER workflow completes. Never remove the committed session pattern.
- **Temporal sandbox** — Never import SQLAlchemy/uuid at module level in activity files. All DB imports must be inside the activity function body.
- **SQLAlchemy `metadata_`** — Column named `metadata_` (reserved name), Pydantic schema field stays `metadata` (auto-mapped via `from_attributes`).
- **`generate_title` Return Type** — Returns a `dict` with `content` (str). Used exclusively for auto-title generation.
- **`stream_response` Streaming** — Uses `stream: true` only for the final LLM response (no tool calls). Tool iterations use non-streaming `llm_turn` calls to get the full `tool_calls` JSON array. If the streaming call fails, falls back to the non-streaming response already received.
- **`get_messages` Reconstruction** — This activity is critical for "tool memory." It converts DB `tool_call`/`tool_result` rows back into the nested `assistant`/`tool` format expected by OpenAI/Ollama APIs. It skips `thinking` role messages (display-only).
- **Placeholder assistant message** — The frontend creates a `temp-ast-*` placeholder on send. Intermediate events (thinking, tool_call, tool_result) are inserted before it. Token events append to its content. The placeholder is never removed during streaming — it becomes the real message content. On `[DONE]`, a silent DB reload replaces temp messages with persisted ones.
- **Per-chip tool pulse** — Tool call pulse animation is per-chip (on `_ToolCallChip`), not per-bubble. A chip stops pulsing immediately when its result arrives. Each chip shows a loading spinner while waiting for its result. The bubble-level `_ToolCallBubble` has no animation.
- **Tool call `isLoading` detection** — `hasAssistantAfter` checks for assistant messages with non-empty content. The empty placeholder (`temp-ast-*` with empty content) is excluded so `isLoading` correctly evaluates to `true` during streaming.
- **Stream reconnect in frontend** — `_processStreamChunks` is a shared method used by both `_sendMessage` (live) and `_reconnectToStream` (page refresh). On reconnect, non-user/system messages are cleared from the list before replaying events from the buffer. The `skipHeader` flag skips `THREAD_ID:` parsing for reconnect (no header in reconnect stream).
- **Ollama URL** — Default is `host.docker.internal:11434` (Docker internal). Workers need network access to the Ollama instance. Configure via Settings screen (persisted to DB). Ollama must be installed and running on the host machine for chat to work.
- **K8s proxy** — A dedicated nginx proxy deployment routes `/api/` and `/health` to backend, `/` to frontend. Exposed via `threadbot-lb` LoadBalancer Service. Backend Service port is 80 (target 8000).
- **MCP infrastructure auto-detection** — `mcp_helper.py` checks for `/var/run/secrets/kubernetes.io/serviceaccount/token` to decide between Docker (`docker run -i`) and Kubernetes (`kubectl run --rm -i --quiet`). In K8s, full `os.environ` must be passed to `StdioServerParameters` so kubectl can find the API server.
- **MCP pod name collision** — `mcp_tools_map` stores `image`/`env_vars`/`args` instead of pre-built `StdioServerParameters`. Fresh params with unique pod names are generated per tool execution via `get_mcp_server_params()`.
- **MCP encryption** — `env_vars` and `args` are encrypted at rest in PostgreSQL using Fernet (AES-128-CBC + HMAC-SHA256). Key comes from `MCP_ENCRYPTION_KEY` env var or auto-generated in the `settings` table. Values are encrypted per-field (keys stay plaintext). Decryption handles legacy unencrypted data gracefully. The `encryption.py` module provides `encrypt_dict()` and `decrypt_dict()` async functions.
- **MCP container args** — Stored as key-value dict, converted to `--key=value` CLI flags appended after the image. In K8s, a `--` separator is added before the args.
- **K8s RBAC for MCP** — The `threadbot-sa` ServiceAccount needs a Role with permissions for `pods` (create/delete/get/list/watch), `pods/attach`, and `pods/log` in the threadbot namespace.
- **MCP pod cleanup** — A K8s CronJob (`mcp-pod-cleanup`) runs every 15 minutes to delete completed/failed MCP pods in the threadbot namespace.
- **Response timeline** — Each assistant bubble shows a compact horizontal timeline with nodes for thinking, tool_call, tool_result, compaction, and response steps. Active step pulses. Derived from the message sequence (no extra storage). Start dot + end chevron arrow indicate reading direction.
- **Built-in tools** — 8 tools that execute in-process (no MCP containers): `continue_thinking`, `web_fetch`, `current_datetime`, `calculator`, `json_parse`, `text_count`, `base64_encode`, `base64_decode`. Defined in `thread_workflow.py` as OpenAI function schemas, executed via `_execute_builtin()` in `llm_activities.py`. The `BUILTIN_TOOLS` set gates dispatching. `continue_thinking` is silent (no tool_call chip, only thinking bubble). Others show as `built-in:{name}` chips.
- **Context donut chart** — `_ContextDonut` widget in `chat_input.dart` renders a `CustomPaint` donut showing context window consumption (estimated_tokens / context_window). Color-coded: green (<50%), amber (50-75%), red (>75%). Only visible when `estimatedTokens > 0`. Updated by `context` stream events from the backend.
- **Context usage events** — Published from `llm_turn` (after each LLM response) and `compact_history` (before/after compaction) as `{"type":"context","estimated_tokens":N,"context_window":N}`. Frontend stores in `_contextEstimatedTokens`/`_contextWindow` state vars, resets on thread switch.
- **Smart auto-scroll** — `_isAtBottom` flag (80px threshold) tracks scroll position. `_scrollToBottom()` skips when user has scrolled away. `force: true` overrides for intentional actions (send, load thread, reconnect). Stream events respect user's scroll position.
- **Flutter web input fixes** — `ChatInput` uses a Stack-based hint overlay instead of `InputDecoration.hintText` to avoid native browser placeholder doubling. `TextSelectionTheme` wraps the `TextField` with explicit `selectionColor` to prevent double selection highlights. `FocusNode` listener triggers rebuilds for border color transitions.
