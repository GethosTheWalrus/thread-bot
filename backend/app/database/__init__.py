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
            CREATE TABLE IF NOT EXISTS skills (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(255) NOT NULL,
                description TEXT DEFAULT '',
                content TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS thread_skill_overrides (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                UNIQUE (thread_id, skill_id)
            )
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_thread_skill_overrides_thread_id "
            "ON thread_skill_overrides(thread_id)"
        ))
        await conn.execute(text("""
            INSERT INTO skills (name, description, content, is_active)
            SELECT
                'Statistical probability analysis',
                'Research event rates online and calculate probabilities, odds, and dry-streak questions.',
                $skill$
Use this skill for questions like "what is the probability of X happening", drop-rate odds, at-least-one-event questions, streaks, cumulative probability, expected value, and similar statistical analysis.

Procedure:
1. Clarify the event, trial count, and whether the user asks about future trials, past trials, or total trials. If the question is ambiguous but can be answered with a reasonable interpretation, state the interpretation.
2. Use web/search/fetch tools to find a reliable source for the event rate. Prefer official docs, primary game wikis, published papers, or clearly maintained reference pages. Quote the source and rate used.
3. Convert the rate to a per-trial probability p. For "1 in N", p = 1/N.
4. For at least one success in n independent future trials, use 1 - (1 - p)^n. Existing failures do not change the future probability unless there is pity protection, depletion, replacement, changing odds, or another non-independent mechanic.
5. For probability of already having at least one success after k independent trials, use 1 - (1 - p)^k.
6. For probability of first success occurring within the next n trials after k prior failures under independent fixed odds, use 1 - (1 - p)^n; if asked for total by k+n trials, use 1 - (1 - p)^(k+n).
7. Use calculator for all arithmetic and probability calculations instead of mental math. Prefer structured calculator operations: at_least_one for at least one success in n trials, binomial_pmf/binomial_cdf/binomial_at_least for exact or cumulative binomial questions, geometric_pmf/geometric_cdf for first-success questions, poisson_pmf/poisson_cdf for rate events, normal_cdf/z_score for normal-distribution questions, and chi_square_gof/chi_square_independence/chi_square_survival for chi-squared tests. Show formula, substitutions, final percentage or p-value, and a plain-language interpretation.
8. Mention assumptions: independence, constant drop rate, and whether the source rate applies to the user's exact activity.

Example pattern:
If a drop is 1/400 and the user asks for at least one in the next 10 kills, compute 1 - (399/400)^10 = about 2.47%. If they also mention 500 prior kills, explain that under independent fixed odds the prior 500 kills do not affect the next-10 probability, but the chance of having seen at least one by 500 kills is 1 - (399/400)^500 = about 71.4%.
$skill$,
                TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM skills WHERE lower(name) = lower('Statistical probability analysis')
            )
        """))
        await conn.execute(text("""
            UPDATE skills
            SET content = replace(
                content,
                '7. Use calculator for arithmetic instead of mental math. Show formula, substitutions, final percentage, and a plain-language interpretation.',
                '7. Use calculator for all arithmetic and probability calculations instead of mental math. Prefer structured calculator operations: at_least_one for at least one success in n trials, binomial_pmf/binomial_cdf/binomial_at_least for exact or cumulative binomial questions, geometric_pmf/geometric_cdf for first-success questions, poisson_pmf/poisson_cdf for rate events, normal_cdf/z_score for normal-distribution questions, and chi_square_gof/chi_square_independence/chi_square_survival for chi-squared tests. Show formula, substitutions, final percentage or p-value, and a plain-language interpretation.'
            )
            WHERE lower(name) = lower('Statistical probability analysis')
              AND content LIKE '%normal_cdf/z_score for normal-distribution questions%'
        """))
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
