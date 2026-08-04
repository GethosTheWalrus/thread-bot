from types import SimpleNamespace
from uuid import uuid4

from app.effect_policy import effect_free_result
from app.services.phase4 import cohort_matches, shadow_effects_blocked
from app.api.phase4 import _workflow_is_started


class _Handle:
    def __init__(self, exists):
        self.exists = exists

    async def describe(self):
        if not self.exists:
            raise RuntimeError("not found")


class _Client:
    def __init__(self, exists):
        self.handle = _Handle(exists)

    def get_workflow_handle(self, workflow_id):
        return self.handle


def test_replay_start_reconciliation_distinguishes_ambiguous_started_from_failure():
    import asyncio

    assert asyncio.run(_workflow_is_started(_Client(True), "agent-run:stable")) is True
    assert asyncio.run(_workflow_is_started(_Client(False), "agent-run:stable")) is False


def test_canary_cohort_is_deterministic_and_filters_event_attributes():
    event = SimpleNamespace(id=uuid4(), source="schedule", event_type="schedule.occurrence", subject={"tenant": "a"}, payload={})
    cohort = {"deployment_id": "deployment-a", "source": "schedule", "subject": {"tenant": "a"}, "percentage": 100}
    assert cohort_matches(cohort, event)
    assert cohort_matches(cohort, event) == cohort_matches(cohort, event)
    assert not cohort_matches({**cohort, "source": "webhook"}, event)
    assert not cohort_matches({**cohort, "percentage": 0}, event)


def test_effect_free_modes_report_mode_specific_suppression():
    result = effect_free_result("action-1", 1, "canary_shadow", "notification")
    assert result["status"] == "simulated"
    assert "canary_shadow" in result["display_content"]
    assert shadow_effects_blocked("replay")["notifications"] is True
    assert shadow_effects_blocked("autonomous")["notifications"] is False
