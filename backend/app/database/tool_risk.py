from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.policy_models import ToolRiskProfile

async def get_tool_risk(db: AsyncSession, workspace_id, tool_identity: str) -> ToolRiskProfile | None:
    return await db.scalar(select(ToolRiskProfile).where(ToolRiskProfile.workspace_id == workspace_id, ToolRiskProfile.tool_identity == tool_identity))

async def require_known_tool(db: AsyncSession, workspace_id, tool_identity: str) -> ToolRiskProfile:
    profile = await get_tool_risk(db, workspace_id, tool_identity)
    if profile is None or profile.risk_level == "unknown":
        raise PermissionError("tool has no approved risk profile")
    return profile
