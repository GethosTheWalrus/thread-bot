from app.autonomy_hashing import approval_request_hash
from app.connectors.webhook import verify_signed_webhook
from app.policy.engine import evaluate_policy
from app.security import origin_chain_allows
from app.policy.engine import explain_risk
from app.policy.approval_presets import evaluate_approval_preset
from app.state_service import state_diff
from app.notifications.dispatcher import dispatch
from app.contracts.phase2 import ApprovalResponse
from app.models.foundation_models import Base as FoundationBase
import hashlib
import hmac


def test_signed_webhook_rejects_replay_and_accepts_canonical_signature():
    body = b'{"type":"change"}'; secret = "secret"; timestamp = "1000"; nonce = "n1"
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + nonce.encode() + b"." + body, hashlib.sha256).hexdigest()
    used = set()
    assert verify_signed_webhook(body, digest, secret, timestamp, nonce, now=1000, used_nonces=used)
    assert not verify_signed_webhook(body, digest, secret, timestamp, nonce, now=1000, used_nonces=used)


def test_policy_deny_precedes_approval_and_allow():
    result = evaluate_policy({"tool_identity": "discord:post"}, [{"scope": "*", "effect": "allow"}, {"scope": "*", "effect": "require_approval", "priority": 2}, {"scope": "*", "effect": "deny", "priority": 3}])
    assert result["effect"] == "deny"


def test_approval_hash_and_origin_chain_are_stable_and_bounded():
    assert approval_request_hash("tool", {"a": 1}, {}, "v1", "p1", "expiry") == approval_request_hash("tool", {"a": 1}, {}, "v1", "p1", "expiry")
    assert approval_request_hash("tool", {"a": 1}, {}, "v1", "p1", "expiry", "binding-a") != approval_request_hash("tool", {"a": 1}, {}, "v1", "p1", "expiry", "binding-b")
    assert origin_chain_allows(["connector:x"], "connector:x") == (False, "self_origin")
    assert origin_chain_allows([], "connector:x") == (True, None)


def test_external_risk_defaults_fail_closed():
    assert explain_risk("mcp:server:tool")["risk_level"] == "unknown"
    assert explain_risk("reachy:speak")["risk_level"] == "critical"
    assert explain_risk("discord:post")["requires_approval"] is True
    assert explain_risk("temporal:terminate")["requires_approval"] is True


def test_understandable_approval_presets_apply_server_classification():
    assert evaluate_approval_preset("builtin:calculator", "effectful")["effect"] == "allow"
    assert evaluate_approval_preset("builtin:generate_image", "effectful")["effect"] == "require_approval"
    assert evaluate_approval_preset("builtin:handoff_to_agent", "effectful")["effect"] == "require_approval"
    assert evaluate_approval_preset("mcp:server:lookup", "effectful")["effect"] == "require_approval"
    assert evaluate_approval_preset("reachy:move", "effectful")["effect"] == "require_approval"
    assert evaluate_approval_preset("builtin:calculator", "all")["effect"] == "require_approval"
    assert evaluate_approval_preset("mcp:server:write", "never")["effect"] == "allow"
    assert evaluate_approval_preset("reachy:move", "never")["effect"] == "allow"
    assert evaluate_approval_preset("unknown:tool", "never")["effect"] == "deny"
    read_only = {"risk_level": "low", "category": "read", "effectful": False}
    effectful = {"risk_level": "unknown", "category": "write", "effectful": True}
    assert evaluate_approval_preset("mcp:DuckDuckGo:search", "effectful", read_only)["effect"] == "allow"
    assert evaluate_approval_preset("mcp:DuckDuckGo:search", "all", read_only)["effect"] == "require_approval"
    assert evaluate_approval_preset("mcp:DuckDuckGo:search", "effectful", effectful)["effect"] == "require_approval"


def test_state_diff_is_canonical_and_only_contains_changes():
    value = state_diff({"a": 1, "same": True}, {"a": 2, "same": True, "b": "new"})
    assert value["diff"] == {"a": {"before": 1, "after": 2}, "b": {"before": None, "after": "new"}}


def test_thread_notification_is_gated_before_any_write(monkeypatch):
    monkeypatch.setattr("app.notifications.dispatcher.security_mode", lambda: "local")
    assert __import__("asyncio").run(dispatch({"channel": "thread"}, {"message": "x"}))["delivered"] is False
    monkeypatch.setattr("app.notifications.dispatcher.security_mode", lambda: "admin_token")
    monkeypatch.setattr("app.notifications.dispatcher.autonomy_flags", lambda: {"autonomy_side_effects_enabled": True})
    result = __import__("asyncio").run(dispatch({"channel": "thread"}, {"message": "x"}))
    assert result == {"delivered": True, "channel": "thread", "write_thread": True}


def test_approval_contract_exposes_redacted_display_metadata_and_credential_fk():
    fields = ApprovalResponse.model_fields
    assert {"run_id", "target", "redacted_arguments", "policy_explanation"} <= set(fields)
    assert "fk_credentials_active_version_id_credential_versions" in {
        constraint.name for constraint in FoundationBase.metadata.tables["credentials"].foreign_keys
    }
