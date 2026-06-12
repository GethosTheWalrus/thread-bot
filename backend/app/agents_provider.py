import base64
import json


_DYNAMIC_MODEL_PREFIX = "threadbot+llm:"
_DYNAMIC_MODEL_KEYS = {"provider", "api_url", "api_key", "model", "stream_timeout"}


def encode_agents_model_config(config: dict) -> str | None:
    """Encode per-run provider settings into a model name for Temporal model activities."""
    model_name = config.get("model")
    if not model_name:
        return None

    payload = {
        key: config.get(key)
        for key in sorted(_DYNAMIC_MODEL_KEYS)
        if config.get(key) not in (None, "")
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    return f"{_DYNAMIC_MODEL_PREFIX}{encoded}"


def _decode_agents_model_config(model_name: str | None) -> dict | None:
    if not model_name or not model_name.startswith(_DYNAMIC_MODEL_PREFIX):
        return None
    encoded = model_name[len(_DYNAMIC_MODEL_PREFIX):]
    try:
        decoded = base64.urlsafe_b64decode(encoded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid ThreadBot dynamic model config") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid ThreadBot dynamic model config")
    return {key: payload[key] for key in _DYNAMIC_MODEL_KEYS if key in payload}


class ThreadBotModelProvider:
    """Model provider that resolves encoded per-run ThreadBot LLM settings."""

    def __init__(self, default_provider):
        self._default_provider = default_provider

    def get_model(self, model_name: str | None):
        dynamic_config = _decode_agents_model_config(model_name)
        if dynamic_config is None:
            return self._default_provider.get_model(model_name)
        print(
            "ThreadBot model provider resolved per-run config: "
            f"provider={dynamic_config.get('provider') or 'auto'} "
            f"api_url={dynamic_config.get('api_url') or ''} "
            f"model={dynamic_config.get('model') or ''}"
        )
        return _build_agents_model_provider(dynamic_config).get_model(dynamic_config.get("model"))

    async def aclose(self) -> None:
        close = getattr(self._default_provider, "aclose", None)
        if close is not None:
            await close()


def _build_agents_model_provider(config: dict):
    """Build an OpenAI Agents SDK model provider from ThreadBot LLM settings."""
    from openai_agents_providers import LlamaCppProvider, OllamaProvider
    from agents import OpenAIProvider

    api_url = (config.get("api_url") or "").rstrip("/")
    api_key = config.get("api_key") or "ollama"
    model_name = config.get("model")
    provider_name = (config.get("provider") or "auto").lower()
    timeout = float(config.get("stream_timeout", 600))

    if provider_name == "auto":
        provider_name = "ollama" if ":11434" in api_url or "ollama" in api_url.lower() else "llama_cpp"

    if provider_name == "ollama":
        if api_url and not api_url.endswith("/v1"):
            api_url = f"{api_url}/v1"
        return OllamaProvider(base_url=api_url, model=model_name, api_key=api_key, timeout=timeout)

    if provider_name in {"llama_cpp", "llamacpp", "local", "openai_compatible"}:
        return LlamaCppProvider(base_url=api_url, model=model_name, api_key=api_key, timeout=timeout)

    if provider_name == "openai":
        return OpenAIProvider(base_url=api_url or None, api_key=api_key)

    raise ValueError(
        f"Unsupported LLM_PROVIDER '{provider_name}'. Use auto, ollama, llama_cpp, or openai."
    )


def build_agents_model_provider(config: dict):
    """Build a provider that supports global defaults and per-run overrides."""
    return ThreadBotModelProvider(_build_agents_model_provider(config))
