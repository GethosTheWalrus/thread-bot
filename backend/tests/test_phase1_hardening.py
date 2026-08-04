from datetime import timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.schedule_service import preview
from app.contracts.autonomy import DraftUpsert, TriggerCreate


def test_schedule_preview_is_timezone_aware_and_deterministic_shape():
    result = preview("*/15 * * * *", "UTC", 3)
    assert len(result["occurrences"]) == 3
    assert all(item.tzinfo == timezone.utc for item in result["occurrences"])
    assert result["occurrences"] == sorted(result["occurrences"])


def test_schedule_contract_rejects_invalid_timezone_and_cron():
    with pytest.raises(ValidationError):
        TriggerCreate(trigger_type="schedule", config={"cron": "* * *", "timezone": "UTC"})
    with pytest.raises(ValidationError):
        TriggerCreate(trigger_type="schedule", config={"cron": "* * * * *", "timezone": "Not/AZone"})


def test_public_draft_rejects_secret_material_but_allows_binding_reference():
    valid = DraftUpsert(optimistic_lock_version=1, credential_bindings=[{"binding_id": uuid4()}])
    assert valid.credential_bindings
    with pytest.raises(ValidationError):
        DraftUpsert(optimistic_lock_version=1, config={"api_key": "never"})
