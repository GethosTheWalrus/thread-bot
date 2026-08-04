from datetime import datetime, timezone
from sqlalchemy import select
from app.models.run_models import Artifact
from app.models.phase3_models import ArtifactTombstone
from app.services.phase3 import tombstone_artifact

async def expire_artifacts(db, store, now=None, limit=500):
    now = now or datetime.now(timezone.utc)
    rows = list((await db.execute(select(Artifact).where(Artifact.retention_until <= now, Artifact.legal_hold == 0).limit(limit))).scalars())
    deleted = 0
    for artifact in rows:
        if await db.scalar(select(ArtifactTombstone.id).where(ArtifactTombstone.artifact_id == artifact.id)): continue
        if artifact.legal_hold: continue
        await store.delete(artifact.storage_key)
        await tombstone_artifact(db, artifact); deleted += 1
    await db.flush()
    return deleted
