from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.approval_service import ApprovalDecisionError, record_approval_decision
from app.models.approval_models import ApprovalDecision


class _FakeDb:
    def __init__(self, scalars):
        self.scalars = list(scalars)
        self.added = []
        self.committed = False

    async def scalar(self, _query):
        return self.scalars.pop(0)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_record_approval_decision_commits_before_signal_boundary():
    workspace_id = uuid4()
    approval_id = uuid4()
    run_id = uuid4()
    request = SimpleNamespace(
        id=approval_id,
        workspace_id=workspace_id,
        run_id=run_id,
        action_id="action-1",
        request_hash="hash-1",
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    action = SimpleNamespace(request_hash="hash-1", status="awaiting_approval")
    db = _FakeDb([request, None, action])

    result = await record_approval_decision(
        db,
        approval_id=approval_id,
        workspace_id=workspace_id,
        decision="approved",
        actor_id="discord:42",
        actor_type="human",
        channel="discord",
        provider_interaction_id="message-99",
    )

    assert db.committed
    assert request.status == "approved"
    assert result["run_id"] == run_id
    decision = next(value for value in db.added if isinstance(value, ApprovalDecision))
    assert decision.decision == "approved"
    assert decision.channel == "discord"
    assert decision.provider_interaction_id == "message-99"


@pytest.mark.asyncio
async def test_record_approval_decision_rejects_inactive_request():
    workspace_id = uuid4()
    request = SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace_id,
        run_id=uuid4(),
        action_id="action-1",
        request_hash="hash-1",
        status="expired",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db = _FakeDb([request, None])

    with pytest.raises(ApprovalDecisionError, match="no longer active"):
        await record_approval_decision(
            db,
            approval_id=request.id,
            workspace_id=workspace_id,
            decision="denied",
            actor_id="owner",
            actor_type="human",
            channel="web",
            provider_interaction_id="key-1",
        )
