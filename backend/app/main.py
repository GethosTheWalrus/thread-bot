from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import get_settings
from app.api.routes import router, set_temporal_client
from temporalio.client import Client


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    client = await Client.connect(
        target_host=f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}",
        namespace=settings.TEMPORAL_NAMESPACE,
    )
    set_temporal_client(client)
    yield


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
