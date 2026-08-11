from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.config import load_settings_from_db
from app.security import cors_origin_allowed, security_mode, actor_from_request, browser_cookie_secure, correlation_id_for_request, local_actor, SESSION_MAX_AGE_SECONDS
from app.api.routes import router, set_temporal_client
from app.api.autonomy import router as autonomy_router
from app.api.phase2 import router as phase2_router, public_router as phase2_public_router
from app.api.phase3 import router as phase3_router
from app.api.phase4 import router as phase4_router
from app.api.osrs import router as osrs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to serve until the separately-run Alembic migration is current.
    from app.database import ensure_database_schema
    await ensure_database_schema()

    # Load persisted settings from DB into override dict
    await load_settings_from_db()

    from app.temporal_client import connect_temporal_client
    from app.config import get_llm_config
    from app.agents_provider import build_agents_model_provider
    from datetime import timedelta
    from temporalio.contrib.openai_agents import ModelActivityParameters, OpenAIAgentsPlugin

    llm_config = get_llm_config()
    plugin = OpenAIAgentsPlugin(
        model_params=ModelActivityParameters(
            start_to_close_timeout=timedelta(seconds=llm_config.get("stream_timeout", 600)),
            heartbeat_timeout=timedelta(seconds=120),
            streaming_topic="threadbot-model-events",
            streaming_batch_interval=timedelta(milliseconds=100),
        ),
        model_provider=build_agents_model_provider(llm_config),
    )
    client = await connect_temporal_client(plugins=[plugin])
    set_temporal_client(client)
    import asyncio
    from app.discord_bot import run_discord_bot
    from app.discord_integration import discord_poll_loop
    discord_task = asyncio.create_task(discord_poll_loop(client))
    discord_bot_task = asyncio.create_task(run_discord_bot(client))
    try:
        yield
    finally:
        for task in (discord_task, discord_bot_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="ThreadBot API",
    description="A ChatGPT-like chatbot with thread-based conversations backed by Temporal",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    correlation_id = correlation_id_for_request(request)
    request.state.correlation_id = correlation_id
    origin = request.headers.get("origin")
    forwarded_scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", "")).split(",", 1)[0].strip()
    origin_allowed = bool(origin and cors_origin_allowed(origin, forwarded_scheme, forwarded_host))

    def apply_cors(response: Response) -> Response:
        if origin_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.append("Vary", "Origin")
        return response

    if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
        if not origin_allowed:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=400)
        response = Response(status_code=200)
        response.headers["Access-Control-Allow-Methods"] = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"
        response.headers["Access-Control-Allow-Headers"] = request.headers.get("access-control-request-headers", "*")
        response.headers["Access-Control-Max-Age"] = "600"
    else:
        public_path = request.url.path.startswith("/api/agent-webhooks/")
        if request.method != "OPTIONS" and request.url.path.startswith("/api/") and not public_path and request.url.path not in {"/api/auth/bootstrap", "/api/auth/session"}:
            if security_mode() == "oidc":
                return apply_cors(JSONResponse({"detail": "OIDC authentication is not configured"}, status_code=501,
                                    headers={"X-Correlation-ID": str(correlation_id)}))
            if security_mode() == "admin_token":
                from app.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    try:
                        actor = await actor_from_request(request, db)
                        request.state.actor = actor
                    except Exception as exc:
                        status = getattr(exc, "status_code", 500)
                        if status == 500:
                            raise
                        return apply_cors(JSONResponse({"detail": getattr(exc, "detail", "Authentication required")}, status_code=status,
                                            headers={"X-Correlation-ID": str(correlation_id)}))
                    if request.method not in {"GET", "HEAD", "OPTIONS"} and not {"owner", "admin"}.intersection(actor.roles):
                        return apply_cors(JSONResponse({"detail": "Owner or admin role required"}, status_code=403,
                                            headers={"X-Correlation-ID": str(correlation_id)}))
            elif security_mode() == "local":
                request.state.actor = local_actor(correlation_id)
        response = await call_next(request)

    response_sets_session = any(
        value.startswith("threadbot_session=")
        for value in response.headers.getlist("set-cookie")
    )
    if security_mode() == "admin_token" and request.cookies.get("threadbot_session") and not response_sets_session:
        response.set_cookie(
            "threadbot_session",
            request.cookies["threadbot_session"],
            httponly=True,
            secure=browser_cookie_secure(request),
            samesite="strict",
            max_age=SESSION_MAX_AGE_SECONDS,
        )
    apply_cors(response)
    response.headers["X-Correlation-ID"] = str(correlation_id)
    return response

app.include_router(router)
app.include_router(autonomy_router)
app.include_router(phase2_router)
app.include_router(phase2_public_router)
app.include_router(phase3_router)
app.include_router(phase4_router)
app.include_router(osrs_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
