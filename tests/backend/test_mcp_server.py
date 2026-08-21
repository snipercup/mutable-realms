from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.town.seed import seed_town_world
from backend.scenarios.ward.seed import seed_ward_world
from backend.world.mcp_server import (
    get_database_path,
    get_session_binding,
    mcp,
    resolve_actor_entity_id,
    resolve_world_id,
)


def test_mcp_exposes_only_controlled_world_tools_without_database_arguments() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert [tool.name for tool in tools] == [
        "world_status",
        "world_context",
        "world_inspect_entity",
        "world_events",
        "world_move_entity",
        "world_travel_route",
        "world_create_route",
        "world_expand_location",
        "world_treat_and_discharge_patient",
        "world_record_social_interaction",
        "world_record_location_memory",
        "world_consolidate_location_memories",
        "world_transfer_resource",
        "world_update_location",
        "world_validate",
    ]
    for tool in tools:
        assert "database_path" not in tool.inputSchema.get("properties", {})
        assert tool.description

    schemas = {tool.name: tool.inputSchema for tool in tools}
    assert schemas["world_context"]["properties"]["event_limit"] == {
        "default": 10,
        "maximum": 100,
        "minimum": 1,
        "title": "Event Limit",
        "type": "integer",
    }
    assert schemas["world_events"]["properties"]["limit"] == {
        "default": 10,
        "maximum": 100,
        "minimum": 1,
        "title": "Limit",
        "type": "integer",
    }


def test_mcp_database_path_must_be_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MUTABLE_REALMS_DB_PATH", raising=False)

    with pytest.raises(RuntimeError, match="MUTABLE_REALMS_DB_PATH"):
        get_database_path()


def test_mcp_database_path_must_reference_an_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_path = tmp_path / "missing.sqlite3"
    monkeypatch.setenv("MUTABLE_REALMS_DB_PATH", str(missing_path))

    with pytest.raises(RuntimeError, match="does not exist"):
        get_database_path()
    assert not missing_path.exists()


def test_mcp_read_tool_uses_configured_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    monkeypatch.setenv("MUTABLE_REALMS_DB_PATH", str(database_path))

    assert get_database_path() == database_path.resolve()


def test_mcp_session_binding_provides_defaults_and_allows_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MUTABLE_REALMS_WORLD_ID", "ward-world")
    monkeypatch.setenv("MUTABLE_REALMS_PLAYER_ID", "player")

    assert get_session_binding() == ("ward-world", "player")
    assert resolve_world_id(None) == "ward-world"
    assert resolve_actor_entity_id(None) == "player"
    # Explicit overrides are allowed: the narration prompt selects the world.
    assert resolve_world_id("other-world") == "other-world"
    assert resolve_world_id("  other-world  ") == "other-world"
    assert resolve_actor_entity_id("other-actor") == "other-actor"
    with pytest.raises(RuntimeError, match="must not be blank"):
        resolve_world_id("   ")


def test_mcp_world_id_required_without_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MUTABLE_REALMS_WORLD_ID", raising=False)
    monkeypatch.delenv("MUTABLE_REALMS_PLAYER_ID", raising=False)

    with pytest.raises(RuntimeError, match="world_id is required"):
        resolve_world_id(None)


def test_mcp_session_binding_requires_both_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUTABLE_REALMS_WORLD_ID", "ward-world")
    monkeypatch.delenv("MUTABLE_REALMS_PLAYER_ID", raising=False)

    with pytest.raises(RuntimeError, match="configured together"):
        get_session_binding()


def test_bound_session_keeps_world_validation_admin_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MUTABLE_REALMS_WORLD_ID", "ward-world")
    monkeypatch.setenv("MUTABLE_REALMS_PLAYER_ID", "player")

    from backend.world import mcp_server

    with pytest.raises(RuntimeError, match="unbound administration"):
        mcp_server.world_validate()


def test_stdio_server_supports_real_tool_discovery_and_calls(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO worlds(id, name) VALUES ('protocol-world', 'Protocol World')"
        )
        connection.commit()

    async def exercise_server() -> None:
        parameters = StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "backend.world.mcp_server"],
            cwd=Path(__file__).parents[2],
            env={"MUTABLE_REALMS_DB_PATH": str(database_path)},
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "world_status" in [tool.name for tool in tools.tools]

                result = await session.call_tool("world_status", {"world_id": "protocol-world"})
                assert result.isError is False
                assert result.structuredContent == {
                    "available_mutations": ["world_move_entity"],
                    "world": {
                        "id": "protocol-world",
                        "name": "Protocol World",
                        "revision": 0,
                    },
                }

                events = await session.call_tool(
                    "world_events", {"world_id": "protocol-world", "limit": 5}
                )
                assert events.structuredContent == {"events": []}

                for invalid_limit in (0, -1, 101):
                    invalid = await session.call_tool(
                        "world_events",
                        {"world_id": "protocol-world", "limit": invalid_limit},
                    )
                    assert invalid.isError is True

    asyncio.run(exercise_server())


def test_stdio_server_reads_explicit_world_other_than_binding(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    seed_town_world(database_path)

    async def exercise_server() -> None:
        parameters = StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "backend.world.mcp_server"],
            cwd=Path(__file__).parents[2],
            env={
                "MUTABLE_REALMS_DB_PATH": str(database_path),
                "MUTABLE_REALMS_WORLD_ID": "town-world",
                "MUTABLE_REALMS_PLAYER_ID": "sailor",
            },
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                # The session binding is town-world, but an explicit world_id
                # reads the other world — that is how the relayed page selects.
                explicit = await session.call_tool("world_status", {"world_id": "ward-world"})
                assert explicit.isError is False
                assert explicit.structuredContent["world"]["id"] == "ward-world"
                # Omitting world_id falls back to the bound world.
                defaulted = await session.call_tool("world_status", {})
                assert defaulted.isError is False
                assert defaulted.structuredContent["world"]["id"] == "town-world"

    asyncio.run(exercise_server())


def test_stdio_server_applies_and_reports_controlled_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)

    async def exercise_server() -> None:
        parameters = StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "backend.world.mcp_server"],
            cwd=Path(__file__).parents[2],
            env={
                "MUTABLE_REALMS_DB_PATH": str(database_path),
                "MUTABLE_REALMS_WORLD_ID": "ward-world",
                "MUTABLE_REALMS_PLAYER_ID": "player",
            },
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                rejected_world = await session.call_tool(
                    "world_status", {"world_id": "other-world"}
                )
                assert rejected_world.isError is True
                mutation = await session.call_tool(
                    "world_treat_and_discharge_patient",
                    {
                        "world_id": "ward-world",
                        "operation_id": "mcp-discharge-patient-1",
                        "expected_revision": 0,
                        "patient_id": "patient-1",
                        "bed_id": "bed-1",
                    },
                )
                assert mutation.isError is False
                assert mutation.structuredContent == {
                    "already_applied": False,
                    "world_revision": 1,
                }

                social = await session.call_tool(
                    "world_record_social_interaction",
                    {
                        "world_id": "ward-world",
                        "operation_id": "mcp-social-patient-1",
                        "expected_revision": 1,
                        "subject_entity_id": "player",
                        "object_entity_id": "patient-2",
                        "relationship_category": "trusted",
                        "relationship_delta": 10,
                        "memory": "The player supported Patient 2 during the ward round.",
                    },
                )
                assert social.isError is False
                assert social.structuredContent == {
                    "already_applied": False,
                    "world_revision": 2,
                }

                events = await session.call_tool(
                    "world_events", {"world_id": "ward-world", "limit": 2}
                )
                assert events.structuredContent is not None
                assert events.structuredContent["events"][0]["event_type"] == (
                    "social_interaction_recorded"
                )

                validation = await session.call_tool("world_validate", {})
                assert validation.isError is True
                assert validation.content
                assert "unbound administration" in str(validation.content[0])

    asyncio.run(exercise_server())
