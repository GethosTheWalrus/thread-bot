from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import load_settings_from_db
from app.api.routes import router, set_temporal_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables and additive schema updates exist (idempotent)
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
