import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app import discord_integration
from app.database import crud


def test_discord_tool_defaults_preserve_tool_level_enables(monkeypatch):
    selected_server_id = uuid4()
    disabled_server_id = uuid4()
    guild_overrides = [
        SimpleNamespace(
            server_id=selected_server_id,
            tool_name="calculate_dps",
            enabled=True,
        ),
        SimpleNamespace(
            server_id=selected_server_id,
            tool_name="optimize_gear",
            enabled=True,
        ),
    ]
    captured = []

    async def get_discord_server_tool_overrides(_db, _guild_id):
        return guild_overrides

    async def get_mcp_servers(_db):
        return [
            SimpleNamespace(id=selected_server_id),
            SimpleNamespace(id=disabled_server_id),
        ]

    async def set_thread_tool_overrides(_db, _thread_id, overrides):
        captured.extend(overrides)

    monkeypatch.setattr(crud, "get_discord_server_tool_overrides", get_discord_server_tool_overrides)
    monkeypatch.setattr(crud, "get_mcp_servers", get_mcp_servers)
    monkeypatch.setattr(crud, "set_thread_tool_overrides", set_thread_tool_overrides)

    asyncio.run(discord_integration.apply_discord_server_tool_defaults(object(), uuid4(), "guild"))

    selected = [row for row in captured if row["server_id"] == selected_server_id]
    assert selected == [
        {"server_id": selected_server_id, "tool_name": None, "enabled": False},
        {"server_id": selected_server_id, "tool_name": "calculate_dps", "enabled": True},
        {"server_id": selected_server_id, "tool_name": "optimize_gear", "enabled": True},
    ]
    assert {"server_id": disabled_server_id, "tool_name": None, "enabled": False} in captured


def test_discord_tool_defaults_preserve_server_and_tool_rows(monkeypatch):
    server_id = uuid4()
    guild_overrides = [
        SimpleNamespace(server_id=server_id, tool_name=None, enabled=True),
        SimpleNamespace(server_id=server_id, tool_name="effectful_tool", enabled=False),
    ]
    captured = []

    async def get_discord_server_tool_overrides(_db, _guild_id):
        return guild_overrides

    async def get_mcp_servers(_db):
        return [SimpleNamespace(id=server_id)]

    async def set_thread_tool_overrides(_db, _thread_id, overrides):
        captured.extend(overrides)

    monkeypatch.setattr(crud, "get_discord_server_tool_overrides", get_discord_server_tool_overrides)
    monkeypatch.setattr(crud, "get_mcp_servers", get_mcp_servers)
    monkeypatch.setattr(crud, "set_thread_tool_overrides", set_thread_tool_overrides)

    asyncio.run(discord_integration.apply_discord_server_tool_defaults(object(), uuid4(), "guild"))

    assert captured == [
        {"server_id": server_id, "tool_name": None, "enabled": True},
        {"server_id": server_id, "tool_name": "effectful_tool", "enabled": False},
    ]


def test_discord_tool_defaults_disable_servers_without_guild_rows(monkeypatch):
    server_id = uuid4()
    captured = []

    async def get_discord_server_tool_overrides(_db, _guild_id):
        return []

    async def get_mcp_servers(_db):
        return [SimpleNamespace(id=server_id)]

    async def set_thread_tool_overrides(_db, _thread_id, overrides):
        captured.extend(overrides)

    monkeypatch.setattr(crud, "get_discord_server_tool_overrides", get_discord_server_tool_overrides)
    monkeypatch.setattr(crud, "get_mcp_servers", get_mcp_servers)
    monkeypatch.setattr(crud, "set_thread_tool_overrides", set_thread_tool_overrides)

    asyncio.run(discord_integration.apply_discord_server_tool_defaults(object(), uuid4(), "guild"))

    assert captured == [
        {"server_id": server_id, "tool_name": None, "enabled": False},
    ]
