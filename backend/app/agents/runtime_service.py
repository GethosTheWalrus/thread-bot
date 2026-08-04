from uuid import UUID
from app.autonomy_hashing import canonical_hash


async def load_runtime_snapshot(snapshot_id: UUID | str) -> dict:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.runtime_models import RuntimeConfigSnapshot

    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(RuntimeConfigSnapshot).where(RuntimeConfigSnapshot.id == UUID(str(snapshot_id))))
        if not row:
            raise LookupError("runtime config snapshot not found")
        config = dict(row.config or {})
        if any(key.lower() in {"secret", "token", "password", "api_key", "ciphertext"} for key in config):
            raise ValueError("runtime snapshot contains secret material")
        if canonical_hash(config) != row.config_hash:
            raise ValueError("runtime config snapshot hash mismatch")
        return {"id": str(row.id), "workspace_id": str(row.workspace_id), "schema_version": row.schema_version, "config": config, "model_credential_binding_id": str(row.model_credential_binding_id) if row.model_credential_binding_id else None}
