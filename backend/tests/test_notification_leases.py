import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.activities.notification_activities import reconcile_notification_deliveries
from app.notifications.service import DELIVERY_CLAIM_LEASE_SECONDS, claim_delivery, mark_delivery


class _Session:
    def __init__(self, row=None):
        self.row = row
        self.committed = False

    async def scalar(self, _statement):
        return self.row

    async def flush(self):
        pass

    async def get(self, _model, _delivery_id):
        return self.row

    async def commit(self):
        self.committed = True


def test_claim_sets_a_lease_and_mark_clears_it():
    row = SimpleNamespace(status="pending", attempts=0, claimed_at=None, claim_expires_at=None, delivered_at=None, last_error=None, available_at=None)
    db = _Session(row)

    assert asyncio.run(claim_delivery(db, uuid4())) is True
    assert row.status == "sending"
    assert row.claimed_at is not None
    assert row.claim_expires_at >= row.claimed_at + timedelta(seconds=DELIVERY_CLAIM_LEASE_SECONDS)

    asyncio.run(mark_delivery(db, uuid4(), True))
    assert row.status == "delivered"
    assert row.claimed_at is None
    assert row.claim_expires_at is None


def test_delivered_notification_cannot_regress_to_retry():
    delivered_at = datetime.now(timezone.utc)
    row = SimpleNamespace(
        status="delivered", attempts=2, claimed_at=None, claim_expires_at=None,
        delivered_at=delivered_at, last_error=None, available_at=None,
    )

    asyncio.run(mark_delivery(_Session(row), uuid4(), False, "late worker failure"))

    assert row.status == "delivered"
    assert row.delivered_at == delivered_at
    assert row.last_error is None


class _ReconcileResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self.rows)


class _ReconcileSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        now = datetime.now(timezone.utc)
        return _ReconcileResult([
            row for row in self.rows
            if row.claim_expires_at is None or row.claim_expires_at < now
        ])

    async def scalar(self, _statement):
        return None

    async def commit(self):
        pass


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


def test_reconcile_skips_recent_sending_and_retries_stale(monkeypatch):
    recent = SimpleNamespace(
        id=uuid4(), workspace_id=uuid4(), status="sending", attempts=1,
        claim_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        claimed_at=datetime.now(timezone.utc), available_at=None,
    )
    stale = SimpleNamespace(
        id=uuid4(), workspace_id=uuid4(), status="sending", attempts=1,
        claim_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        claimed_at=datetime.now(timezone.utc) - timedelta(minutes=3), available_at=None,
    )
    session = _ReconcileSession([recent, stale])
    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: _SessionContext(session))

    result = asyncio.run(reconcile_notification_deliveries({"limit": 100}))

    assert result["requeued"] == 1
    assert str(stale.id) in result["delivery_ids"]
    assert recent.status == "sending"
    assert stale.status == "retry"
    assert stale.claim_expires_at is None
