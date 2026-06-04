from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chatbot"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Temporal
    TEMPORAL_HOST: str = "localhost"
    TEMPORAL_PORT: int = 7233
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "chatbot-task-queue"
    TEMPORAL_PAYLOAD_CODEC_ENABLED: bool = False
    TEMPORAL_PAYLOAD_CODEC_KEY: str = ""
    TEMPORAL_PAYLOAD_CODEC_KEY_FILE: str = ""

    # LLM API
    LLM_API_URL: str = "http://host.docker.internal:11434/v1"
    LLM_API_KEY: str = "ollama"
    LLM_MODEL: str = "llama3.1"
    LLM_IMAGE_API_URL: str = ""
    LLM_IMAGE_MODEL: str = ""
    LLM_PROVIDER: str = "auto"  # auto, ollama, llama_cpp, openai
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2048
    LLM_STREAM_TIMEOUT: int = 600
    LLM_MAX_ITERATIONS: int = 25
    LLM_CONTEXT_WINDOW: int = 8192
    LLM_COMPACTION_THRESHOLD: float = 0.75
    LLM_PRESERVE_RECENT: int = 10
    LLM_TOOL_RESULT_MAX_CHARS: int = 0  # 0 = no truncation

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "*"

    # App
    APP_NAME: str = "ThreadBot"
    APP_PUBLIC_BASE_URL: str = ""
    GENERATED_IMAGE_DIR: str = "/tmp/threadbot-generated-images"

    # Discord integration (optional)
    DISCORD_ENABLED: bool = False
    DISCORD_BOT_TOKEN: str = ""
    DISCORD_GUILD_ID: str = ""
    DISCORD_CHANNEL_ID: str = ""
    DISCORD_POLL_INTERVAL_SECONDS: int = 10

    model_config = {"extra": "ignore"}


# Store overrides separately since Pydantic v2 models are frozen
_settings: Settings | None = None
_overrides: dict = {}


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_setting(key: str):
    """Get a setting value, checking overrides first."""
    key_lower = key.lower()
    if key_lower in _overrides:
        return _overrides[key_lower]
    settings = get_settings()
    upper = key.upper()
    if hasattr(settings, upper):
        return getattr(settings, upper)
    if hasattr(settings, key_lower):
        return getattr(settings, key_lower)
    return None


def update_settings(**kwargs) -> None:
    """Update settings at runtime via an override dict (Pydantic v2 models are frozen)."""
    for key, value in kwargs.items():
        _overrides[key.lower()] = value


async def load_settings_from_db() -> None:
    """Load persisted settings from DB into the override dict.

    Called once during app startup so that DB-stored values take precedence
    over environment variables / Pydantic defaults.
    """
    from app.database import AsyncSessionLocal
    from app.database.crud import get_all_settings

    async with AsyncSessionLocal() as db:
        rows = await get_all_settings(db)

    # Map DB keys (stored lowercase) into the override dict.
    # Coerce numeric types back from their string representation.
    _type_map = {
        "llm_temperature": float,
        "llm_max_tokens": int,
        "llm_stream_timeout": int,
        "llm_max_iterations": int,
        "llm_context_window": int,
        "llm_compaction_threshold": float,
        "llm_preserve_recent": int,
        "llm_tool_result_max_chars": int,
        "discord_enabled": lambda v: str(v).lower() in ("1", "true", "yes", "on"),
        "discord_poll_interval_seconds": int,
    }
    for key, value in rows.items():
        coerce = _type_map.get(key)
        if coerce:
            try:
                value = coerce(value)
            except (ValueError, TypeError):
                pass
        _overrides[key] = value


def get_llm_config() -> dict:
    """Get current LLM config with overrides applied."""
    return {
        "api_url": get_setting("LLM_API_URL"),
        "api_key": get_setting("LLM_API_KEY"),
        "model": get_setting("LLM_MODEL"),
        "image_model": get_setting("LLM_IMAGE_MODEL") or get_setting("LLM_MODEL"),
        "image_api_url": get_setting("LLM_IMAGE_API_URL") or get_setting("LLM_API_URL"),
        "public_base_url": get_setting("APP_PUBLIC_BASE_URL") or "",
        "generated_image_dir": get_setting("GENERATED_IMAGE_DIR") or "/tmp/threadbot-generated-images",
        "provider": get_setting("LLM_PROVIDER"),
        "temperature": get_setting("LLM_TEMPERATURE"),
        "max_tokens": get_setting("LLM_MAX_TOKENS"),
        "stream_timeout": get_setting("LLM_STREAM_TIMEOUT"),
        "max_iterations": get_setting("LLM_MAX_ITERATIONS"),
        "context_window": get_setting("LLM_CONTEXT_WINDOW"),
        "compaction_threshold": get_setting("LLM_COMPACTION_THRESHOLD"),
        "preserve_recent": get_setting("LLM_PRESERVE_RECENT"),
        "tool_result_max_chars": get_setting("LLM_TOOL_RESULT_MAX_CHARS"),
    }


def get_discord_config() -> dict:
    """Get current Discord integration config with overrides applied."""
    return {
        "enabled": bool(get_setting("DISCORD_ENABLED")),
        "bot_token": get_setting("DISCORD_BOT_TOKEN") or "",
        "guild_id": get_setting("DISCORD_GUILD_ID") or "",
        "channel_id": get_setting("DISCORD_CHANNEL_ID") or "",
        "poll_interval_seconds": int(get_setting("DISCORD_POLL_INTERVAL_SECONDS") or 10),
    }


def get_redis_url() -> str:
    """Build the effective Redis URL, appending REDIS_DB if not already in the URL."""
    url = get_setting("REDIS_URL")
    db = get_setting("REDIS_DB")
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.path and parsed.path not in ("", "/"):
        return url
    return f"{url.rstrip('/')}/{db}"
