from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def ensure_database_schema() -> None:
    """Verify that the separately-run Alembic migration reached head."""
    await check_database_schema()


async def check_database_schema() -> None:
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from pathlib import Path

    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    async with engine.connect() as conn:
        current = await conn.run_sync(lambda sync_conn: MigrationContext.configure(sync_conn).get_current_revision())
    if current != head:
        raise RuntimeError(
            f"Database schema is at {current or 'unversioned'}, but application requires Alembic head {head}. "
            "Run `cd backend && alembic upgrade head` before starting the API or worker."
        )
