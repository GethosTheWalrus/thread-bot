"""Durable autonomy core tables.

Revision ID: 0005_agents_core
Revises: 0004_foundation
"""
from alembic import op

revision = "0005_agents_core"
down_revision = "0004_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These tables are deliberately sourced from the bounded autonomy metadata;
    # keeping the migration additive also makes fresh and 0004 databases agree.
    from app.models import agent_models, run_models, policy_models, budget_models
    bind = op.get_bind()
    # AgentAction has no depth column; depth is a run-level invariant.
    for model in (agent_models.AgentTemplate, agent_models.AgentTemplateVersion,
                  agent_models.Agent, agent_models.AgentVersionDraft,
                  agent_models.AgentVersion, agent_models.AgentTrigger,
                  agent_models.TriggerEvent, run_models.AgentRun,
                  run_models.AgentRunStep, run_models.AgentAction,
                  run_models.AgentRunEvent, run_models.AgentStateSnapshot,
                  run_models.Artifact, policy_models.ToolRiskProfile,
                  policy_models.PolicySet, policy_models.PolicyVersion,
                  policy_models.PolicyRule, budget_models.BudgetProfile,
                  budget_models.BudgetBucket, budget_models.BudgetReservation,
                  run_models.ThreadExecutionLease):
        model.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("Autonomy migration is intentionally irreversible; restore a database backup instead.")
