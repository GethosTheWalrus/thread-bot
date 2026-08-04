from uuid import uuid4
import pytest
from app.services.phase3 import validate_handoff, validate_json_schema
from app.contracts.phase3 import RecommendationCreate

def test_handoff_schema_and_cycle_guards():
    target = uuid4()
    contract = type("Contract", (), {"target_allowlist": [target], "input_schema": {"type": "object", "required": ["subject"]}, "max_depth": 3})()
    validate_handoff(contract, target, {"subject": "status"}, ["run:1"])
    with pytest.raises(ValueError, match="cycle"):
        validate_handoff(contract, target, {"subject": "status"}, [f"agent:{target}"])

def test_handoff_rejects_invalid_payload_and_depth():
    with pytest.raises(ValueError):
        validate_json_schema({"type": "object", "required": ["subject"]}, {})
    target = uuid4()
    contract = type("Contract", (), {"target_allowlist": [], "input_schema": {}, "max_depth": 1})()
    with pytest.raises(ValueError, match="depth"):
        validate_handoff(contract, target, {}, ["run:1"])

def test_recommendations_require_evidence():
    with pytest.raises(ValueError): RecommendationCreate(proposed_diff={"agent_id": str(uuid4())})
    assert RecommendationCreate(evidence={"count": 3}, proposed_diff={"scope": "narrow"}).evidence["count"] == 3
