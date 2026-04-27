import aiohttp
from temporalio.activity import defn


@defn
async def call_llm(args: dict) -> str:
    """Call the OpenAI-compatible LLM API.
    
    Args should contain:
        messages: list of chat messages
        llm_config: optional dict with api_url, api_key, model, temperature, max_tokens, stream_timeout
    """
    from app.config import get_llm_config

    messages = args.get("messages", [])
    # Merge any per-request overrides with global config
    config = get_llm_config()
    overrides = args.get("llm_config", {})
    if overrides:
        config.update({k: v for k, v in overrides.items() if v is not None})

    api_url = config["api_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 2048),
        "stream": False,
    }

    timeout = aiohttp.ClientTimeout(total=config.get("stream_timeout", 120))
    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, headers=headers, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"LLM API error {resp.status}: {error_text}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]


@defn
async def save_message(args: dict) -> None:
    """Save a message to the database."""
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.database.crud import add_message

    thread_id = args["thread_id"]
    role = args["role"]
    content = args["content"]
    async with AsyncSessionLocal() as db:
        await add_message(db, UUID(thread_id), role, content)
        await db.commit()


@defn
async def get_messages(thread_id: str) -> list[dict]:
    """Get chat history for a thread."""
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.database.crud import get_thread_messages

    async with AsyncSessionLocal() as db:
        messages = await get_thread_messages(db, UUID(thread_id))
        return [{"role": m.role, "content": m.content} for m in messages]


@defn
async def update_title(args: dict) -> None:
    """Update thread title."""
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.database.crud import update_thread_title

    thread_id = args["thread_id"]
    title = args["title"]
    async with AsyncSessionLocal() as db:
        await update_thread_title(db, UUID(thread_id), title)
        await db.commit()
