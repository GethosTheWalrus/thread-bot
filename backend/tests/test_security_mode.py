from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app import config
from app.api import routes
from app.contracts import ActorContext, ActorType, AuthenticationMethod
from app.models.foundation_models import ApiToken
from app.models.schemas import SecurityModeRequest
from app.security import LOCAL_WORKSPACE_ID, cors_origin_allowed, verify_token


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.added = []
        self.settings = {}

    async def execute(self, _query):
        return _Result([row for row in self.rows if row.revoked_at is None])

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.rows.extend(self.added)


@pytest.mark.asyncio
async def test_security_mode_rotation_revokes_tokens_and_sets_secure_cookie(monkeypatch):
    config._overrides.pop("security_mode", None)
    old = ApiToken(workspace_id=LOCAL_WORKSPACE_ID, actor_id="old", token_hash="hash", token_prefix="tb_old", roles=["admin"])
    db = _Db([old])
    monkeypatch.setattr(routes, "upsert_settings", _upsert_settings)

    actor = ActorContext(workspace_id=LOCAL_WORKSPACE_ID, actor_type=ActorType.human, actor_id="local-owner",
                         authentication_method=AuthenticationMethod.local, roles=("owner", "admin"), correlation_id=uuid4())
    request = Request({"type": "http", "method": "PATCH", "scheme": "http", "headers": [(b"x-forwarded-proto", b"https")]})
    response = Response()
    result = await routes.update_security_mode(SecurityModeRequest(mode="admin_token"), request, response, db, actor)

    assert result.mode == "admin_token"
    assert result.token and result.token.startswith("tb_")
    assert old.revoked_at is not None
    created = db.added[0]
    assert created.roles == ["owner", "admin"]
    assert created.token_hash != result.token
    assert verify_token(result.token, created.token_hash)
    assert config.get_setting("SECURITY_MODE") == "admin_token"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie

    response2 = Response()
    result2 = await routes.update_security_mode(SecurityModeRequest(mode="admin_token"), request, response2, db, actor)
    assert result2.token != result.token
    assert created.revoked_at is not None

    response3 = Response()
    local_result = await routes.update_security_mode(SecurityModeRequest(mode="local"), request, response3, db, actor)
    assert local_result.mode == "local"
    assert config.get_setting("SECURITY_MODE") == "local"
    assert "Max-Age=0" in response3.headers["set-cookie"]


async def _upsert_settings(db, settings):
    db.settings.update(settings)


@pytest.mark.asyncio
async def test_sliding_session_does_not_overwrite_rotated_cookie(monkeypatch):
    from app.main import security_middleware

    monkeypatch.setitem(config._overrides, "security_mode", "admin_token")
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "path": "/health",
        "query_string": b"",
        "headers": [(b"cookie", b"threadbot_session=tb_old")],
    })

    async def call_next(_request):
        response = Response()
        response.set_cookie("threadbot_session", "tb_new", httponly=True)
        return response

    response = await security_middleware(request, call_next)
    cookies = response.headers.getlist("set-cookie")
    assert len(cookies) == 1
    assert "threadbot_session=tb_new" in cookies[0]


def test_runtime_cors_allows_explicit_and_same_origin_wildcard(monkeypatch):
    monkeypatch.setitem(config._overrides, "security_mode", "admin_token")
    monkeypatch.setitem(config._overrides, "cors_origins", "https://console.example")
    assert cors_origin_allowed("https://console.example", "https", "api.example")
    assert not cors_origin_allowed("https://other.example", "https", "api.example")

    monkeypatch.setitem(config._overrides, "cors_origins", "*")
    assert cors_origin_allowed("https://app.example", "https", "app.example")
    assert not cors_origin_allowed("https://other.example", "https", "app.example")
