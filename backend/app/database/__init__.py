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
        await conn.execute(text(
            "ALTER TABLE threads ADD COLUMN IF NOT EXISTS llm_overrides JSONB DEFAULT NULL"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS generated_images (
                filename VARCHAR(255) PRIMARY KEY,
                content BYTEA NOT NULL,
                content_type VARCHAR(100) NOT NULL DEFAULT 'image/png',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS generated_media (
                filename VARCHAR(255) PRIMARY KEY,
                content BYTEA NOT NULL,
                content_type VARCHAR(100) NOT NULL DEFAULT 'video/mp4',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS args JSONB DEFAULT '{}'::jsonb"))
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS registry_credentials JSONB DEFAULT '{}'::jsonb"))
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS cached_tools JSONB DEFAULT NULL"))
        await conn.execute(text("ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS cached_tools_at TIMESTAMPTZ DEFAULT NULL"))
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
                indexed_discord_message_id VARCHAR(255),
                indexed_at TIMESTAMPTZ,
                indexing_status VARCHAR(50),
                indexing_error TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "ALTER TABLE discord_thread_links ADD COLUMN IF NOT EXISTS indexed_discord_message_id VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE discord_thread_links ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE discord_thread_links ADD COLUMN IF NOT EXISTS indexing_status VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE discord_thread_links ADD COLUMN IF NOT EXISTS indexing_error TEXT"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_discord_thread_links_thread_id "
            "ON discord_thread_links(thread_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_discord_thread_links_discord_thread_id "
            "ON discord_thread_links(discord_thread_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS discord_servers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                guild_id VARCHAR(255) NOT NULL UNIQUE,
                guild_name VARCHAR(255) NOT NULL,
                default_channel_id VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text(
            "ALTER TABLE discord_servers ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_discord_servers_guild_id "
            "ON discord_servers(guild_id)"
        ))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS discord_server_tool_overrides (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                guild_id VARCHAR(255) NOT NULL REFERENCES discord_servers(guild_id) ON DELETE CASCADE,
                server_id UUID NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
                tool_name VARCHAR(255),
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                UNIQUE (guild_id, server_id, tool_name)
            )
        """))
        await conn.execute(text(
            "ALTER TABLE discord_server_tool_overrides ADD COLUMN IF NOT EXISTS tool_name VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE discord_server_tool_overrides "
            "DROP CONSTRAINT IF EXISTS discord_server_tool_overrides_guild_id_server_id_key"
        ))
        await conn.execute(text(
            "ALTER TABLE discord_server_tool_overrides ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_discord_server_tool_overrides_guild_id "
            "ON discord_server_tool_overrides(guild_id)"
        ))
        await conn.execute(text(
            "INSERT INTO discord_servers (id, guild_id, guild_name) "
            "SELECT gen_random_uuid(), guild_id, guild_id FROM "
            "(SELECT DISTINCT guild_id FROM discord_thread_links) linked_guilds "
            "ON CONFLICT (guild_id) DO NOTHING"
        ))
