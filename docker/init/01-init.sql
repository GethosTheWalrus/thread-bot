-- Create tables if they don't exist
CREATE TABLE IF NOT EXISTS threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL DEFAULT 'New Thread',
    parent_id UUID REFERENCES threads(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    llm_overrides JSONB DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_threads_parent_id ON threads(parent_id);
CREATE INDEX IF NOT EXISTS idx_threads_created_at ON threads(created_at DESC);

CREATE TABLE IF NOT EXISTS mcp_servers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    image VARCHAR(255) NOT NULL,
    env_vars JSONB DEFAULT '{}'::jsonb,
    args JSONB DEFAULT '{}'::jsonb,
    registry_credentials JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    cached_tools JSONB DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(255) PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_tool_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    server_id UUID NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    tool_name VARCHAR(255),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (thread_id, server_id, tool_name)
);

CREATE INDEX IF NOT EXISTS idx_thread_tool_overrides_thread_id ON thread_tool_overrides(thread_id);

CREATE TABLE IF NOT EXISTS skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    content TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS thread_skill_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (thread_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_thread_skill_overrides_thread_id ON thread_skill_overrides(thread_id);

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
);

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
);

CREATE INDEX IF NOT EXISTS idx_discord_thread_links_thread_id ON discord_thread_links(thread_id);
CREATE INDEX IF NOT EXISTS idx_discord_thread_links_discord_thread_id ON discord_thread_links(discord_thread_id);
