# ThreadBot Architecture & Design

This document provides a comprehensive overview of the ThreadBot system architecture, intended to help developers and AI agents understand how the components interact.

## System Overview

ThreadBot is a ChatGPT-like application that uses **Temporal** for orchestrating long-running LLM generation and database interactions. It consists of:

1.  **Frontend**: A Flutter Web application with a responsive, premium UI.
2.  **Backend API**: A FastAPI service that handles HTTP requests from the frontend and relays streaming events from Redis.
3.  **Temporal Worker**: A Python worker process that executes the actual workflows and activities.
4.  **Database**: PostgreSQL for storing threads, messages, MCP server configurations, settings, and per-thread tool overrides.
5.  **Temporal Server**: The orchestration engine.
6.  **Redis**: Pub/sub message broker bridging the worker and backend for real-time streaming.
7.  **MCP Tool Servers**: Ephemeral containers (Docker or Kubernetes pods) that provide tools to the LLM via the Model Context Protocol. Auto-detected via `mcp_helper.py`.

```
    User → Frontend (Flutter Web)
    Frontend → Backend (FastAPI) via HTTP/REST
    Backend → PostgreSQL (Read/Write)
    Backend → Temporal Server (Submit Workflow)
    Backend ← Redis Pub/Sub (Subscribe to stream events)
    Temporal Server → Worker (Dispatch Task)
    Worker → PostgreSQL (Read/Write)
    Worker → LLM API (HTTP, streaming SSE)
    Worker → Redis Pub/Sub (Publish stream events)
    Worker → MCP Tool Containers (Docker exec / kubectl run)
```

The entire stack is containerized using Docker Compose (7 services: postgres, temporal, temporal-ui, redis, backend, worker, frontend). For production, Kubernetes manifests are provided with an interactive deploy script.

---

## 1. Backend Architecture (Python / FastAPI)

The backend is split into the API server (`app/main.py` + `app/api/routes.py`) and the Temporal Worker (`app/worker.py`). Both share the same database models, schemas, and config.

### Configuration (`app/config.py`)
- Uses Pydantic v2 `BaseSettings`.
- Because Pydantic v2 models are frozen by default, runtime overrides (e.g., from the settings UI) are stored in a separate `_overrides` dictionary.
- On startup, `load_settings_from_db()` loads all persisted settings from the `settings` table into `_overrides`, so DB values take precedence over environment variables.
- The `PATCH /api/settings` endpoint writes to both `_overrides` (in-memory) and the `settings` table (DB), ensuring values survive restarts.
- Always use `get_setting("KEY")` or `get_llm_config()` rather than accessing the `Settings` object directly to ensure overrides are respected.
- `REDIS_URL` and `REDIS_DB` are configurable via environment variables. `get_redis_url()` returns the full connection string.
- Key settings: `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_STREAM_TIMEOUT`, `LLM_CONTEXT_WINDOW`, `LLM_COMPACTION_THRESHOLD`, `LLM_PRESERVE_RECENT`, `LLM_TOOL_RESULT_MAX_CHARS`, `DATABASE_URL`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `TEMPORAL_HOST`, `TEMPORAL_PORT`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE`, `REDIS_URL`, `REDIS_DB`.

### Database (`app/database/`, `app/models/`)
- Uses **SQLAlchemy 2.0** with `asyncpg` for asynchronous database access.
- `expire_on_commit=False` and `autoflush=False` are set on the `async_sessionmaker`.
- **Models** (5 tables):
    - `Thread`: Represents a conversation. Has a `parent_id` for branching (self-referencing FK with CASCADE delete). Fields: `id`, `title`, `parent_id`, `created_at`, `updated_at`.
    - `Message`: Belongs to a Thread. Contains `role` (user/assistant/thinking/tool_call/tool_result/system), `content`, and `metadata_` (JSONB). Fields: `id`, `thread_id`, `role`, `content`, `created_at`, `metadata_`.
    - `MCPServer`: Stores MCP server configurations. Environment variables and container arguments are encrypted at rest using Fernet symmetric encryption. Fields: `id`, `name`, `image`, `env_vars` (encrypted JSONB), `args` (encrypted JSONB), `is_active`, `cached_tools` (JSONB — populated by test endpoint or first chat), `created_at`.
    - `ThreadToolOverride`: Per-thread MCP tool enable/disable overrides. Fields: `id`, `thread_id`, `server_id`, `tool_name` (nullable — null means server-level override), `enabled`. Unique constraint on `(thread_id, server_id, tool_name)`. Cascade deletes on thread and server.
    - `Setting`: Simple key-value table for persisting runtime settings (LLM URL, model, API key, context params, etc.). Fields: `key` (PK), `value`.
- **CRUD**: Located in `app/database/crud.py`. 18+ async functions including: `create_thread`, `get_thread`, `get_thread_with_messages` (selectinload), `get_root_threads`, `get_child_threads`, `add_message`, `get_thread_messages`, `update_thread_title`, `delete_thread`, `get_message_count`, `create_mcp_server` (encrypts), `get_mcp_servers`, `delete_mcp_server`, `toggle_mcp_server`, `update_mcp_server` (encrypts), `get_all_settings`, `upsert_settings`, `get_thread_tool_overrides`, `set_thread_tool_overrides` (delete-and-replace).

### API Routes (`app/api/routes.py`)
- Standard REST endpoints for managing threads, messages, settings, MCP servers, and tool overrides.
- **Endpoints**:
    - `POST /api/threads` — Create a new thread
    - `POST /api/chat` — Send message, start Temporal workflow, return SSE stream
    - `GET /api/threads` — List root threads (paginated: limit, offset)
    - `GET /api/threads/{id}` — Get thread with messages + `is_generating` check via Redis
    - `GET /api/threads/{id}/stream` — Reconnect to in-progress generation stream (204 if not generating)
    - `GET /api/threads/{id}/replies` — Get child threads (branches)
    - `PATCH /api/threads/{id}` — Rename thread
    - `DELETE /api/threads/{id}` — Delete thread
    - `DELETE /api/threads` — Delete ALL threads
    - `GET /api/settings` — Get current LLM settings (reloads from DB first)
    - `PATCH /api/settings` — Update settings (persists to DB + in-memory overrides)
    - `GET /api/mcp` — List all MCP servers (decrypted)
    - `POST /api/mcp` — Create MCP server (encrypts env_vars/args)
    - `DELETE /api/mcp/{id}` — Delete MCP server
    - `PATCH /api/mcp/{id}/toggle` — Toggle MCP server active/inactive
    - `PATCH /api/mcp/{id}` — Update MCP server (name, image, env_vars, args)
    - `POST /api/mcp/{id}/test` — Test MCP server connection, cache discovered tools in `cached_tools` column
    - `GET /api/threads/{id}/tool-overrides` — Get available servers (from cache) + per-thread overrides (instant, no container spin-up)
    - `PUT /api/threads/{id}/tool-overrides` — Set per-thread tool overrides (bulk replace)
- The `POST /api/chat` endpoint is the core of the application:
    1. It creates the user's message in the database in an isolated transaction.
    2. It subscribes to a per-request Redis pub/sub channel **before** starting the workflow (critical to avoid race conditions — Redis pub/sub doesn't buffer).
    3. It sets a `generating:{thread_id}` flag in Redis (with a 600s TTL) so the frontend can detect in-progress generation after a page refresh.
    4. It submits a Temporal workflow (`RunThreadWorkflow.run`) asynchronously using `start_workflow`.
    5. It returns a `StreamingResponse` that relays events from Redis to the frontend. Events are structured JSON. `[DONE]` and `[ERROR]` are plain string sentinels.
- The `GET /api/threads/{thread_id}/stream` endpoint supports **stream reconnect** after a page refresh:
    1. It checks the `generating:{thread_id}` Redis key to find the active channel. Returns 204 if not generating.
    2. It polls the Redis event buffer list (`events:{channel}`) using an index cursor, yielding all events from the beginning.
    3. New events are picked up on subsequent polls until `[DONE]` is encountered.
- The `GET /api/threads/{thread_id}` endpoint includes an `is_generating` boolean field by checking Redis.

### Temporal Workflows & Activities (`app/workflows/`, `app/activities/`)
- **Workflow** (`RunThreadWorkflow`): Orchestrates the chat process in this order:
    1. `get_messages` — fetch chat history, reconstructing OpenAI-compatible format (10s timeout)
    2. `compact_history` — token-aware compaction check and summarization (120s timeout, 2 retries)
    3. If compacted: `save_message` (summary) + `delete_messages_before` (cleanup)
    4. `call_llm` — LLM interaction loop with MCP tool support and real-time streaming (600s timeout, 1 attempt)
    5. `save_message` — persist final assistant response (10s timeout)
    6. Auto-title (conditional: first exchange or every 5th message) — `call_llm` (title gen, 60s) + `update_title` + `publish_title`
    7. `publish_done` — send `[DONE]` sentinel to close the stream (5s timeout, 2 retries)
- **Activities** (8 registered in `worker.py`):
    - `call_llm`: Agent loop with MCP tool support. Discovers active MCP tools (from DB), applies per-thread tool overrides (tool-level > server-level > default enabled), runs non-streaming calls during tool iterations (need full `tool_calls` JSON). Re-issues the final call with `stream: true` and publishes each SSE token to Redis as `{"type":"token","content":"..."}`. Saves intermediate messages (thinking, tool_call, tool_result) to DB inline. Caches discovered tools in `mcp_servers.cached_tools`. Supports configurable tool result truncation (`LLM_TOOL_RESULT_MAX_CHARS`). All events are also buffered in a Redis list (`events:{channel}`) for stream reconnect.
    - `compact_history`: Estimates tokens in history using a character-count heuristic (`chars / 4`) and uses the LLM to generate a summary of older messages if a threshold is exceeded.
    - `delete_messages_before`: Cleans up the database by removing messages that have been compacted into a summary.
    - `save_message`, `get_messages`, `update_title`: Interact with the database.
    - `publish_done`: Publishes `[DONE]` sentinel to Redis (both pub/sub and event buffer). Clears the `generating:{thread_id}` Redis key and sets a 60s TTL on the event buffer for reconnect grace period.
    - `publish_title`: Publishes `{"type":"title","content":"..."}` to Redis (both pub/sub and event buffer).
- **Crucial Rules**:
    1. **Explicit Workflow Inputs**: All configuration required by a workflow (such as LLM URLs, model names, API keys, Redis URL, and stream channel) MUST be provided explicitly as workflow input arguments. Activities should NOT rely on environment variables.
    2. **Temporal Sandbox**: Because Temporal executes activities in an isolated sandbox, database imports must happen inside the activity function bodies, not at the module level.

### MCP & Tool Orchestration
ThreadBot supports extending the LLM with custom tools via the Model Context Protocol (MCP).
- **Discovery**: The `call_llm` activity queries all active `MCPServer` entries in the database. For each server, it decrypts env_vars and args, then uses a temporary `stdio_client` connection to discover tool definitions. The connection method is auto-detected by `mcp_helper.py`: Docker locally (`docker run -i`), or `kubectl run` pods in Kubernetes.
- **Tool Caching**: Discovered tools are cached in the `cached_tools` JSONB column on `mcp_servers`. This is populated by the test endpoint (`POST /mcp/{id}/test`) and by `call_llm` during the first chat. The `GET /tool-overrides` endpoint reads from this cache — it does NOT spin up MCP containers, making it instant.
- **Per-Thread Overrides**: Users can enable/disable individual MCP tools or entire servers on a per-thread basis. Overrides are stored in the `thread_tool_overrides` table. Tool-level overrides take precedence over server-level. No rows = all enabled (default). The frontend provides a wrench icon in the chat input to access a bottom sheet with server master toggles and individual tool toggles.
- **Networking**: In Docker, tool containers are launched with `--add-host=host.docker.internal:host-gateway` to allow them to reach services on the host machine. In Kubernetes, MCP pods run in the same namespace with RBAC permissions via the `threadbot-sa` ServiceAccount.
- **Container Arguments**: MCP servers can have additional CLI arguments (stored as key-value pairs, converted to `--key=value` flags). These are appended after the image name in docker/kubectl commands. In K8s, a `--` separator is added before the arguments.
- **Execution**: If the LLM requests a tool call, the worker launches the corresponding container/pod, executes the tool, and feeds the result back into the LLM context. Fresh `StdioServerParameters` are generated per execution to avoid pod name collisions.
- **Tool Result Truncation**: Configurable via `LLM_TOOL_RESULT_MAX_CHARS` setting (default 0 = no truncation). When enabled, only the LLM context is truncated; the full result is saved to DB and streamed to the frontend. Truncated results include an LLM-aware notice: `[TRUNCATED — result was X chars, showing first Y. Consider using more specific parameters.]`.
- **Encryption**: MCP server secrets (`env_vars` and `args`) are encrypted at rest in PostgreSQL using Fernet (AES-128-CBC + HMAC-SHA256). The encryption key is resolved from the `MCP_ENCRYPTION_KEY` environment variable, or auto-generated and stored in the `settings` table. Values are encrypted per-field (keys remain in plaintext). Decryption handles legacy unencrypted data gracefully by passing through values that fail decryption.
- **Persistence**: Unlike standard tool loops, ThreadBot persists every `tool_call` and `tool_result` to the database as unique message roles. This ensures the LLM retains "tool memory" across turns and allows for visual reconstruction in the UI.
- **Agent Loop**: Capped at `max_iterations` (default 25). A system prompt is injected when tools are available to encourage multi-step tool use.
- **Infrastructure Requirements**: The `backend` and `worker` containers must have the `docker` CLI installed (Docker Compose) or `kubectl` (Kubernetes). In K8s, the `threadbot-sa` ServiceAccount needs RBAC permissions for pods, pods/attach, and pods/log.
- **Pod Cleanup**: A K8s CronJob (`mcp-pod-cleanup`) runs every 15 minutes to delete completed/failed MCP pods in the threadbot namespace.

### Conversational Compaction & Memory
To manage large conversations and stay within LLM context limits, ThreadBot implements **Token-Aware Compaction**:
- **Monitoring**: Before every LLM call, history is analyzed using a character-count heuristic (`chars / 4`).
- **Thresholds**: If tokens exceed a configurable percentage of the `context_window` (default 75%), a compaction event triggers.
- **Summarization**: Older messages (excluding a configurable "preserve recent" buffer, default 10) are sent to a separate non-streaming LLM call for summarization.
- **Replacement**: The original messages are deleted from the database and replaced with a single `system` role message containing the summary. This summary is then provided to the LLM as the first message in subsequent turns.

---

## 2. Real-Time Streaming Architecture

Streaming is the core UX feature. Here's why Redis pub/sub is used and how it works:

### Why Redis is Required
The Temporal worker (where `call_llm` executes) and the backend (where the HTTP streaming response lives) are **separate processes/containers**. Temporal workflows/activities don't support streaming results back to the caller — they return values only when complete. Redis bridges this gap with:
- **Pub/sub channels**: Real-time event relay from worker to backend for the initial SSE connection.
- **Event buffer lists**: A Redis list (`events:{channel}`) stores all events for stream reconnect after page refresh. The list is polled by the reconnect endpoint.
- **Generating status**: A Redis key (`generating:{thread_id}`) tracks which threads have active generation so the frontend knows to reconnect.

### Event Flow
```
LLM API --SSE tokens--> Worker (call_llm activity)
                            |
                            | publish() to Redis channel + event buffer list
                            v
                    Redis Pub/Sub Channel ──────── Redis List (events:{channel})
                            |                              |
                            | subscribe (live connection)  | LRANGE (reconnect)
                            v                              v
                    Backend (StreamingResponse)     Backend (reconnect endpoint)
                            |                              |
                            | HTTP chunked response        | HTTP chunked response
                            v                              v
                    Frontend (initial send)         Frontend (page refresh)
```

### Structured JSON Events
All events are JSON objects published to a per-request Redis channel:

| Type | Payload | When |
|------|---------|------|
| `thinking` | `{"type":"thinking","content":"..."}` | LLM returns content alongside tool_calls |
| `tool_call` | `{"type":"tool_call","content":"Calling ...","tools":["..."]}` | LLM requests tool execution |
| `tool_result` | `{"type":"tool_result","tool":"...","content":"...","success":bool}` | Tool execution completes |
| `token` | `{"type":"token","content":"<chunk>"}` | Each SSE token from the final streaming LLM call |
| `title` | `{"type":"title","content":"..."}` | Auto-generated thread title |
| `text` | `{"type":"text","content":"..."}` | Fallback for non-streaming responses |
| `[DONE]` | Plain string sentinel | Stream complete, safe to reload from DB |
| `[ERROR]` | Plain string sentinel | Error occurred |

### Token Streaming Details
- During the agent loop, tool iterations use **non-streaming** calls to get the full `tool_calls` JSON structure in one response.
- When the final iteration returns text-only (no tool calls), the activity re-issues the same request with `stream: true`.
- SSE `data:` lines are parsed, `choices[0].delta.content` tokens are extracted and published individually to Redis.
- If the streaming call fails, the activity falls back to the non-streaming response already received.
- The frontend appends each token to a placeholder assistant message, and the markdown renderer progressively displays the growing text.

---

## 3. Frontend Architecture (Flutter)

The frontend is a Flutter Web application designed to look and feel like a premium AI chat interface.

### State Management
- State is managed locally within `StatefulWidget`s (e.g., `ChatScreen`).
- No global state management libraries (like Provider or Riverpod) are used to keep the architecture simple and avoid issues with Dart's tree-shaking on Flutter master branch.
- `Message.content` and `ThreadListItem.title` are mutable fields to support in-place streaming updates without object replacement.

### Screens (3 total)
- `ChatScreen` (`lib/screens/chat_screen.dart`): The main layout containing the sidebar and the chat area. Handles message sending, structured JSON event parsing, token streaming, placeholder management, stream reconnect, and tool overrides bottom sheet. Contains `_ToolOverridesSheet` for per-thread MCP tool enable/disable.
- `SettingsScreen` (`lib/screens/settings_screen.dart`): LLM configuration (API URL, API Key, Model), context management (window size, compaction threshold, preserve recent), and tool call settings (tool result truncation max chars).
- `MCPScreen` (`lib/screens/mcp_screen.dart`): MCP server CRUD with add/edit dialog (name, Docker image, env vars as KV pairs, container args as KV pairs). Toggle active/inactive. Test connection (shows discovered tools). Delete confirmation. Secret masking with reveal toggle. Link to Docker Hub MCP catalog.

There is no `HomeScreen`, `ThreadListScreen`, `ThreadDetailScreen`, or `ThreadTreeView`.

### API Communication (`lib/services/api_service.dart`)
- Handles all HTTP communication with the FastAPI backend.
- Base URL auto-detects: `Uri.base.origin` for web, `localhost:8000` otherwise.
- Settings (LLM URL, model, API key, context params) are loaded from and saved to the backend API exclusively. No local storage is used for settings.
- Includes `getThreadToolOverrides()` and `setThreadToolOverrides()` for per-thread tool override management.

### UI Components (`lib/widgets/`)
- `ChatMessageList` (`lib/widgets/chat_message_list.dart`): Renders the conversation using `flutter_markdown`. Contains many private widget classes for different message types:
    - **User/Assistant**: Standard chat bubbles (`_ChatBubble`) with distinct, color-coded, uppercase labels ("YOU" / "THREADBOT").
    - **Thinking**: Collapsible amber blocks (`_ThinkingBubble` standalone, `_InlineThinkingBlock` within assistant bubbles).
    - **Tool Call**: Styled purple chips (`_ToolCallChip`) showing the server and tool name. Each chip has its own pulse animation that stops when its result arrives. Chips show a loading spinner while waiting for results. Expandable sections show tool input (JSON arguments) and output.
    - **Tool Result**: Collapsible monospace code blocks (`_CollapsibleResultBlock`) for raw tool output, with green check / red X status icons.
    - **Response Timeline**: Compact horizontal timeline (`_ResponseTimeline`) on each assistant bubble with nodes for thinking, tool_call, tool_result, and response steps. Active step pulses. Start dot + end chevron arrow indicate reading direction. Derived from the message sequence (no extra storage).
    - **Compaction Summary**: Subtle divider labels indicating that earlier messages have been summarized.
    - **Skeleton Shimmer** (`_TypingDots`): Cascading gradient bars shown while waiting for the first token.
    - Pre-computes claimed indices to avoid duplicate rendering of tool results, tool calls, and thinking messages across bubbles.
- `Sidebar` (`lib/widgets/sidebar.dart`): 280px wide thread list sidebar. Groups threads by: Today, Yesterday, Previous 7 Days, Older. New Chat button, thread list with rename/delete popup menus, bottom actions (Clear Conversations, MCP Servers, Settings). Shows spinner for "New Thread" titles (generating).
- `ChatInput` (`lib/widgets/chat_input.dart`): Text input with send button and tools (wrench) button for per-thread tool overrides. Multi-line (max 6 lines). Wrench icon highlights purple when overrides are active.

### Placeholder & Streaming Flow
1. User sends a message -> frontend creates a `temp-ast-*` placeholder assistant message (empty content, shows skeleton shimmer under THREADBOT header).
2. Intermediate events (thinking, tool_call, tool_result) are inserted **before** the placeholder in the message list.
3. `token` events append content to the placeholder progressively — shimmer disappears on first token.
4. `title` events update the sidebar thread title in-place.
5. On `[DONE]`, a silent DB reload replaces all temp messages with persisted ones.

### Stream Reconnect Flow
If the page is refreshed mid-generation:
1. `_loadThread` fetches messages from DB. The `ThreadResponse` includes `is_generating: true`.
2. Frontend calls `_reconnectToStream`: clears non-user/system messages, adds a placeholder assistant message, sets `_isSending = true`.
3. Connects to `GET /api/threads/{id}/stream` which polls the Redis event buffer list.
4. All buffered events replay from the beginning via `_processStreamChunks` (shared with `_sendMessage`), rebuilding thinking/tool_call/tool_result bubbles and streaming tokens.
5. New events continue to arrive via polling until `[DONE]`.
6. On `[DONE]`, standard silent DB reload and `_isSending = false`.

---

## 4. Data Flow: Sending a Message

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend (Flutter)
    participant B as Backend (FastAPI)
    participant R as Redis
    participant DB as PostgreSQL
    participant T as Temporal Server
    participant W as Temporal Worker
    participant L as LLM API
    participant MCP as MCP Tool Containers

    U->>F: Type message & Send
    F->>F: Optimistic UI (add user msg + placeholder)
    F->>B: POST /api/chat (streaming request)
    B->>DB: Save user message & commit
    B->>R: Subscribe to stream channel
    B->>R: SET generating:{thread_id} = channel
    B->>T: Start RunThreadWorkflow (async)
    B-->>F: Open StreamingResponse

    T->>W: Dispatch Workflow Task
    W->>DB: get_messages (fetch history)
    W->>W: compact_history (token check)
    opt Compaction Triggered
        W->>L: Summarize older messages
        W->>DB: Save summary & delete old messages
    end

    W->>W: call_llm activity begins
    W->>W: Discover active MCP tools
    W->>W: Apply per-thread tool overrides

    loop Agent Loop (non-streaming)
        W->>L: POST /chat/completions
        L-->>W: Response with tool_calls
        W->>R: publish thinking event
        W->>DB: save_inline thinking
        W->>R: publish tool_call event
        W->>DB: save_inline tool_call
        W->>MCP: Execute tool (Docker run / kubectl run)
        MCP-->>W: Tool result
        W->>R: publish tool_result event
        W->>DB: save_inline tool_result
    end

    Note over W,L: Final call — re-issue with stream:true
    W->>L: POST /chat/completions (stream:true)
    loop Token Streaming
        L-->>W: SSE data chunk
        W->>R: publish token event
        R-->>B: relay event
        B-->>F: yield token chunk
        F->>F: append token to placeholder
    end

    W->>DB: save_message (final assistant response)
    W->>L: Generate title (non-streaming)
    W->>DB: update_title
    W->>R: publish title event
    R-->>B: relay title
    B-->>F: yield title event
    F->>F: update sidebar title

    W->>R: publish [DONE] + buffer to events list
    W->>R: DEL generating:{thread_id}
    R-->>B: relay [DONE]
    B-->>F: close stream
    F->>B: Silent reload from DB
```

1.  **User action**: The user types a message and presses Enter in `ChatInput`.
2.  **Frontend Optimistic Update**: `ChatScreen` immediately adds the user's message and a placeholder assistant message (empty content, shows skeleton shimmer) to the local list and scrolls to the bottom.
3.  **API Request**: `ApiService.sendMessageStream` sends a `POST /api/chat` request containing the content and optional thread ID. LLM configuration is managed entirely server-side.
4.  **Backend Setup**: `chat_endpoint` creates the message in DB, subscribes to the Redis channel, sets the `generating:{thread_id}` flag in Redis, starts the workflow, and opens a `StreamingResponse` that relays Redis events.
5.  **Tool Override Filtering**: The worker loads per-thread overrides from the DB and filters the discovered tool set. Tool-level overrides take precedence over server-level. No overrides = all tools enabled.
6.  **Agent Loop**: The worker executes `call_llm` with non-streaming calls during tool iterations. Intermediate messages (thinking, tool_call, tool_result) are saved to DB inline and published to Redis (both pub/sub and event buffer list) in real-time. Tool results can be truncated for the LLM context while the full result is saved to DB and streamed to the frontend.
7.  **Token Streaming**: When the agent loop's final iteration returns text (no tool calls), `call_llm` re-issues the request with `stream: true`. Each SSE token is published to Redis -> relayed by backend -> appended to the placeholder by the frontend.
8.  **Title Generation**: After saving the final response, the workflow generates a title, saves it, and publishes a `title` event to Redis so the sidebar updates instantly.
9.  **Finalization**: `publish_done` sends `[DONE]` to close the stream, buffers it in the events list, and clears the `generating:{thread_id}` Redis key. The event buffer list TTL is set to 60s for reconnect grace period. The frontend does a silent DB reload to replace temp messages with persisted ones.

---

## 5. Docker & Infrastructure

### Docker Compose
- Defined in `docker-compose.yml`.
- **Services** (7):
    - `postgres`: PostgreSQL 16 Alpine. Volume `postgres-data`. Init script from `docker/init/01-init.sql`.
    - `temporal`: Temporal auto-setup (v1.25.1). Uses postgres as backend. Healthcheck via `tctl cluster health`.
    - `temporal-ui`: Temporal Web UI. Port 8080.
    - `redis`: Redis 7 Alpine. Healthcheck.
    - `backend`: FastAPI server built from `./backend/Dockerfile`. Port 8000. Mounts docker.sock. `extra_hosts: host.docker.internal`. Restart on-failure.
    - `worker`: Same image as backend. Command: `python -m app.worker`. Same volumes/env as backend. No exposed ports.
    - `frontend`: Built from `docker/Dockerfile.frontend` (context: `./frontend`). Port 3000->80. Nginx with inline config, SPA fallback, `/api/` proxy to backend.
- **Startup Dependencies**: The `backend` and `worker` services use `depends_on` with `condition: service_healthy` to wait for Postgres, Temporal, and Redis to be ready.

### Kubernetes
- **Manifests** in `k8s/`:
    - `namespace.yaml`: Namespace `threadbot`.
    - `configmap.yaml`: `threadbot-config` with DATABASE_URL, TEMPORAL_HOST, LLM_API_URL, REDIS_URL, REDIS_DB.
    - `rbac.yaml`: ServiceAccount `threadbot-sa`, Role `mcp-pod-runner` (pods: create/delete/get/list/watch; pods/attach + pods/log: create/get), RoleBinding.
    - `deployment.yaml`: Backend Deployment (2 replicas, readiness+liveness probes), backend Service (port 80->8000), Worker Deployment (1 replica), Frontend Deployment (2 replicas), Frontend Service (port 80), Proxy Deployment (nginx:alpine with ConfigMap routing), `threadbot-lb` LoadBalancer Service (port 80).
    - `cronjob-mcp-cleanup.yaml`: CronJob `mcp-pod-cleanup` running every 15 minutes to delete completed/failed MCP pods.
- **Deploy Script** (`deploy.sh`): Interactive script that prompts for registry prefix, image pull secret, PostgreSQL/Temporal/Redis/LLM connection details. Generates `k8s/configmap.yaml`, builds multi-arch images (amd64 + arm64), pushes to registry, and applies all K8s manifests.
- **Proxy Architecture**: In K8s, a dedicated nginx proxy deployment routes `/api/` and `/health` to the backend service and `/` to the frontend service. Exposed via `threadbot-lb` LoadBalancer. The frontend's inline nginx proxy blocks are never reached in K8s.

---

## 6. Development Guidelines

- **Simplicity First**: Avoid over-engineering. If a simple `setState` works in Flutter, use it instead of a complex state management system.
- **Temporal Sandbox**: Always remember that Temporal activities run in restricted environments. Avoid module-level state and perform lazy imports for database connections.
- **Config Overrides**: Always use the override-aware helper functions (`get_setting`, `get_llm_config`) in the backend, as Pydantic models are immutable. Settings are persisted in the DB `settings` table and loaded on startup via `load_settings_from_db()`.
- **Redis is Required**: Redis pub/sub cannot be replaced with in-memory queues because the worker and backend are separate processes. With K8s multi-replica deployments, in-memory approaches fail when the request handler and worker activity land on different pods. Redis also serves as the event buffer store for stream reconnect (events lists) and generation status tracking (generating keys).
- **MCP Tool Caching**: The `GET /tool-overrides` endpoint must never spin up MCP containers. It reads from the `cached_tools` column on `mcp_servers`, which is populated by the test endpoint or by `call_llm` during the first chat.
