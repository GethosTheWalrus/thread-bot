from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
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
    """Apply small idempotent schema fixes for existing deployments.

    Docker init SQL and SQLAlchemy create_all only cover fresh databases. This
    project has no migration framework yet, so keep additive compatibility DDL
    here for persisted Postgres volumes.
    """
    from app.models.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS args JSONB DEFAULT '{}'::jsonb"))
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS cached_tools JSONB DEFAULT NULL"))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS thread_tool_overrides (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                server_id UUID NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
                tool_name VARCHAR(255),
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                UNIQUE (thread_id, server_id, tool_name)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_thread_tool_overrides_thread_id "
            "ON thread_tool_overrides(thread_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS discord_thread_links (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                thread_id UUID NOT NULL UNIQUE REFERENCES threads(id) ON DELETE CASCADE,
                guild_id VARCHAR(255) NOT NULL,
                channel_id VARCHAR(255) NOT NULL,
                discord_thread_id VARCHAR(255) NOT NULL UNIQUE,
                discord_thread_name VARCHAR(255) NOT NULL,
                last_discord_message_id VARCHAR(255),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_discord_thread_links_thread_id "
            "ON discord_thread_links(thread_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_discord_thread_links_discord_thread_id "
            "ON discord_thread_links(discord_thread_id)"
        ))
