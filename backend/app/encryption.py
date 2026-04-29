"""
Symmetric encryption for MCP server secrets (env_vars, args).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package.
The encryption key is resolved in this order:
  1. MCP_ENCRYPTION_KEY environment variable (base64-encoded 32-byte key)
  2. Auto-generated key stored in the `settings` DB table

Values are encrypted per-field: each value in the dict is encrypted
individually so keys remain visible for display purposes.
"""

import base64
import json
import os

from cryptography.fernet import Fernet


_fernet: Fernet | None = None


def _get_or_create_key() -> bytes:
    """Get encryption key from env or DB, creating one if needed."""
    env_key = os.environ.get("MCP_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key

    # Import lazily to avoid circular imports and Temporal sandbox issues
    import asyncio
    from app.database import AsyncSessionLocal
    from app.database.crud import get_all_settings, upsert_settings

    async def _load_or_create():
        async with AsyncSessionLocal() as db:
            settings = await get_all_settings(db)
            existing = settings.get("mcp_encryption_key")
            if existing:
                return existing.encode()
            # Generate a new key and persist it
            new_key = Fernet.generate_key()
            await upsert_settings(db, {"mcp_encryption_key": new_key.decode()})
            await db.commit()
            return new_key

    # Handle both sync and async contexts
    try:
        loop = asyncio.get_running_loop()
        # We're inside an async context — create a task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return loop.run_in_executor(pool, lambda: asyncio.run(_load_or_create()))
    except RuntimeError:
        # No event loop — safe to use asyncio.run
        return asyncio.run(_load_or_create())


def _get_fernet() -> Fernet:
    """Get or initialize the Fernet instance."""
    global _fernet
    if _fernet is None:
        key = _get_or_create_key()
        if isinstance(key, bytes):
            _fernet = Fernet(key)
        else:
            # It's a coroutine from run_in_executor
            raise RuntimeError("Encryption key not yet loaded")
    return _fernet


async def _get_fernet_async() -> Fernet:
    """Async version that properly awaits key creation."""
    global _fernet
    if _fernet is None:
        env_key = os.environ.get("MCP_ENCRYPTION_KEY")
        if env_key:
            key = env_key.encode() if isinstance(env_key, str) else env_key
        else:
            from app.database import AsyncSessionLocal
            from app.database.crud import get_all_settings, upsert_settings

            async with AsyncSessionLocal() as db:
                settings = await get_all_settings(db)
                existing = settings.get("mcp_encryption_key")
                if existing:
                    key = existing.encode()
                else:
                    key = Fernet.generate_key()
                    await upsert_settings(db, {"mcp_encryption_key": key.decode()})
                    await db.commit()
        _fernet = Fernet(key)
    return _fernet


async def encrypt_dict(data: dict | None) -> dict | None:
    """Encrypt all values in a dict. Keys are preserved in plaintext."""
    if not data:
        return data
    f = await _get_fernet_async()
    encrypted = {}
    for k, v in data.items():
        plaintext = str(v).encode("utf-8")
        encrypted[k] = f.encrypt(plaintext).decode("utf-8")
    return encrypted


async def decrypt_dict(data: dict | None) -> dict | None:
    """Decrypt all values in a dict. Handles mixed encrypted/plaintext gracefully."""
    if not data:
        return data
    f = await _get_fernet_async()
    decrypted = {}
    for k, v in data.items():
        try:
            plaintext = f.decrypt(v.encode("utf-8")).decode("utf-8")
            decrypted[k] = plaintext
        except Exception:
            # Value is not encrypted (legacy data or plaintext) — pass through
            decrypted[k] = v
    return decrypted
