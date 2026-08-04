"""Activity-only credential resolution. Callers must never serialize its result."""
from uuid import UUID


async def resolve_credential_binding(binding_id: UUID | str) -> dict:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.encryption import decrypt_scalar
    from app.models.foundation_models import CredentialBinding, Credential, CredentialVersion

    async with AsyncSessionLocal() as db:
        binding = await db.scalar(select(CredentialBinding).where(CredentialBinding.id == UUID(str(binding_id)), CredentialBinding.is_active.is_(True)))
        if not binding:
            raise PermissionError("credential binding is inactive or missing")
        credential = await db.get(Credential, binding.credential_id)
        if not credential or not credential.active_version_id:
            raise PermissionError("credential has no active version")
        version = await db.get(CredentialVersion, credential.active_version_id)
        if not version:
            raise PermissionError("credential version is missing")
        secret = await decrypt_scalar(version.ciphertext)
        return {"binding_id": str(binding.id), "provider": credential.provider, "secret": secret, "constraints": binding.constraints or {}}
