def build_agents_model_provider(config: dict):
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
        return OllamaProvider(base_url=api_url, model=model_name, api_key=api_key, timeout=timeout)

    if provider_name in {"llama_cpp", "llamacpp", "local", "openai_compatible"}:
        return LlamaCppProvider(base_url=api_url, model=model_name, api_key=api_key, timeout=timeout)

    if provider_name == "openai":
        return OpenAIProvider(base_url=api_url or None, api_key=api_key)

    raise ValueError(
        f"Unsupported LLM_PROVIDER '{provider_name}'. Use auto, ollama, llama_cpp, or openai."
    )
