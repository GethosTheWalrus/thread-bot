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

    # LLM API
    LLM_API_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = "ollama"
    LLM_MODEL: str = "llama3.1"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2048
    LLM_STREAM_TIMEOUT: int = 120

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "*"

    # App
    APP_NAME: str = "ThreadBot"

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


def get_llm_config() -> dict:
    """Get current LLM config with overrides applied."""
    return {
        "api_url": get_setting("LLM_API_URL"),
        "api_key": get_setting("LLM_API_KEY"),
        "model": get_setting("LLM_MODEL"),
        "temperature": get_setting("LLM_TEMPERATURE"),
        "max_tokens": get_setting("LLM_MAX_TOKENS"),
        "stream_timeout": get_setting("LLM_STREAM_TIMEOUT"),
    }
