from temporalio.activity import defn

@defn
async def retain_expired_artifacts(args):
    from app.database import AsyncSessionLocal
    from app.artifacts import FilesystemArtifactStore
    from app.services.retention import expire_artifacts
    store = FilesystemArtifactStore(args.get("root", "/tmp/threadbot-artifacts"))
    async with AsyncSessionLocal() as db:
        count = await expire_artifacts(db, store, limit=int(args.get("limit", 500))); await db.commit(); return {"deleted": count}
