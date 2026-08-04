import asyncio
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException
from starlette.requests import Request

from app import config
from app.contracts import ActorContext, ActorType, AuthenticationMethod
from app.security import (
    autonomy_flags,
    browser_cookie_secure,
    correlation_id_for_request,
    hash_token,
    require_owner_or_admin,
    verify_token,
)


def test_argon2id_token_verification_and_no_plaintext_hash():
    token = "tb_test_secret"
    token_hash = hash_token(token)
    assert token_hash.startswith("$argon2id$")
    assert verify_token(token, token_hash)
    assert not verify_token("wrong", token_hash)
    assert token not in token_hash


def test_malformed_correlation_id_gets_replacement():
    request = Request({"type": "http", "method": "GET", "headers": [(b"x-correlation-id", b"not-a-uuid")]})
    replacement = correlation_id_for_request(request)
    assert replacement != uuid4()
    assert len(str(replacement)) == 36


def test_browser_cookie_security_follows_request_scheme():
    http_request = Request({"type": "http", "method": "POST", "scheme": "http", "server": ("localhost", 3000), "path": "/api/auth/session", "headers": []})
    proxy_https_request = Request({"type": "http", "method": "POST", "scheme": "http", "server": ("threadbot.example", 443), "path": "/api/auth/session", "headers": [(b"x-forwarded-proto", b"https")]})
    assert browser_cookie_secure(http_request) is False
    assert browser_cookie_secure(proxy_https_request) is True


def test_local_mode_allows_agents_and_respects_side_effect_flag(monkeypatch):
    monkeypatch.setitem(config._overrides, "security_mode", "local")
    monkeypatch.setitem(config._overrides, "autonomy_enabled", True)
    monkeypatch.setitem(config._overrides, "autonomy_side_effects_enabled", True)
    monkeypatch.setitem(config._overrides, "autonomy_webhooks_enabled", True)
    flags = autonomy_flags()
    assert flags["autonomy_enabled"] is True
    # Side effects may be explicitly enabled in trusted local deployments.
    assert flags["autonomy_side_effects_enabled"] is True
    # Webhooks remain disabled in local mode regardless of the side-effect flag.
    assert flags["autonomy_webhooks_enabled"] is False


def test_owner_admin_role_guard():
    actor = ActorContext(workspace_id=uuid4(), actor_type=ActorType.human, actor_id="u",
                         authentication_method=AuthenticationMethod.admin_token,
                         roles=("viewer",), correlation_id=uuid4())
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_owner_or_admin(actor))
    assert error.value.status_code == 403
