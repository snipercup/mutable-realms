from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.app.narrator import NarratorError, NarratorStartLocation, NarratorStartResult
from backend.persistence.migrations import migrate_database
from backend.world.characters import (
    CharacterConflict,
    create_player_character,
    list_player_characters,
    read_player_character,
    remove_player_character,
    update_player_character,
)
from backend.world.queries import get_world_map, read_world
from backend.world.scenarios import create_scenario
from backend.world.worlds import create_world_from_scenario, instance_player_character


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "world.sqlite3"
    migrate_database(path)
    return path


def _world(path: Path, world_id: str) -> None:
    create_scenario(
        path, scenario_id=f"scenario-{world_id}", operation_id=f"s-{world_id}", title="Scenario"
    )
    create_world_from_scenario(
        path, world_id=world_id, operation_id=f"w-{world_id}", scenario_id=f"scenario-{world_id}"
    )


def test_character_definition_crud_and_idempotent_create(tmp_path: Path) -> None:
    path = _database(tmp_path)
    first = create_player_character(
        path,
        character_id="fate",
        operation_id="create-1",
        name="Fate",
        basic_info="Human, 24, silver hair",
    )
    replay = create_player_character(
        path,
        character_id="fate",
        operation_id="create-1",
        name="Fate",
        basic_info="Human, 24, silver hair",
    )
    assert first["already_applied"] is False
    assert replay["already_applied"] is True
    assert read_player_character(path, "fate")["basic_info"] == "Human, 24, silver hair"
    update_player_character(
        path,
        character_id="fate",
        operation_id="update-1",
        name="Fate Virellea",
        basic_info="Diplomat",
    )
    assert read_player_character(path, "fate")["name"] == "Fate Virellea"
    assert len(list_player_characters(path)) == 1
    remove_player_character(path, character_id="fate", operation_id="remove-1")
    assert list_player_characters(path) == []


def test_character_definition_rejects_operation_reuse(tmp_path: Path) -> None:
    path = _database(tmp_path)
    create_player_character(path, character_id="fate", operation_id="create-1", name="Fate")
    with pytest.raises(CharacterConflict, match="different request"):
        create_player_character(path, character_id="fate", operation_id="create-1", name="Other")


def test_instance_copies_definition_into_two_independent_worlds(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _world(path, "world-a")
    _world(path, "world-b")
    create_player_character(
        path, character_id="fate", operation_id="create-1", name="Fate", basic_info="Human diplomat"
    )

    first = instance_player_character(
        path,
        world_id="world-a",
        operation_id="instance-a",
        expected_revision=1,
        character_id="fate",
        location_name="Elaris",
    )
    second = instance_player_character(
        path,
        world_id="world-b",
        operation_id="instance-b",
        expected_revision=1,
        character_id="fate",
        location_name="Virellea",
    )
    assert first["world_revision"] == 2
    assert second["world_revision"] == 2
    assert read_world(path, "world-a")["player"]["name"] == "Fate"
    assert read_world(path, "world-b")["player"]["name"] == "Fate"
    assert read_world(path, "world-a")["player"]["location_name"] == "Elaris"
    assert read_world(path, "world-b")["player"]["location_name"] == "Virellea"

    update_player_character(
        path,
        character_id="fate",
        operation_id="update-1",
        name="Fate Updated",
        basic_info="Changed template",
    )
    assert read_world(path, "world-a")["player"]["name"] == "Fate"
    assert read_world(path, "world-b")["player"]["name"] == "Fate"


def test_instance_commits_contextual_start_layout_atomically(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _world(path, "world-a")
    create_player_character(path, character_id="fate", operation_id="create-1", name="Fate")
    layout = [
        {
            "name": "Main Street",
            "description": "A broad street outside the guild.",
            "parent_name": None,
            "link_to_start": False,
        },
        {
            "name": "Adventurer's Guild",
            "description": "Tall doors beneath a brass crest.",
            "parent_name": "Main Street",
            "link_to_start": True,
        },
    ]
    result = instance_player_character(
        path,
        world_id="world-a",
        operation_id="instance-layout",
        expected_revision=1,
        character_id="fate",
        location_name="Main Street",
        location_layout=layout,
    )
    assert result["world_revision"] == 2
    assert read_world(path, "world-a")["player"]["location_name"] == "Main Street"
    import sqlite3

    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM locations WHERE world_id = 'world-a'"
            ).fetchone()[0]
            == 2
        )
        assert tuple(
            connection.execute(
                "SELECT is_map_scope, is_default_scope FROM location_metadata "
                "WHERE world_id = 'world-a' AND location_id = ?",
                (result["location_ids"]["main street"],),
            ).fetchone()
        ) == (1, 1)
        assert (
            connection.execute(
                "SELECT parent_location_id FROM location_containment WHERE child_location_id = ?",
                (result["location_ids"]["adventurer's guild"],),
            ).fetchone()[0]
            == result["location_ids"]["main street"]
        )
        assert (
            connection.execute("SELECT 1 FROM location_links WHERE world_id = 'world-a'").fetchone()
            is not None
        )
    replay = instance_player_character(
        path,
        world_id="world-a",
        operation_id="instance-layout",
        expected_revision=1,
        character_id="fate",
        location_name="Main Street",
        location_layout=layout,
    )
    assert replay["already_applied"] is True


def test_contextual_start_uses_player_location_as_default_map_scope(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _world(path, "world-a")
    create_player_character(path, character_id="fate", operation_id="create-1", name="Fate")
    instance_player_character(
        path,
        world_id="world-a",
        operation_id="instance-layout",
        expected_revision=1,
        character_id="fate",
        location_name="Main Street",
        location_layout=[
            {
                "name": "Main Street",
                "description": "A broad street.",
                "parent_name": None,
                "link_to_start": False,
            },
            {
                "name": "Adventurer's Guild",
                "description": "Guild doors.",
                "parent_name": "Main Street",
                "link_to_start": True,
            },
        ],
    )

    world_map = get_world_map(path, world_id="world-a")

    assert world_map["scope_location"]["id"] == "world-a-start"
    assert world_map["scope_location"]["name"] == "Main Street"
    assert [location["name"] for location in world_map["locations"]] == [
        "Adventurer's Guild",
        "Main Street",
    ]
    assert world_map["player_location_id"] == "world-a-start"
    assert world_map["player_visible_location_id"] == "world-a-start"


def test_world_allows_no_more_than_one_player_instance(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _world(path, "world-a")
    create_player_character(path, character_id="fate", operation_id="create-1", name="Fate")
    create_player_character(path, character_id="other", operation_id="create-2", name="Other")
    instance_player_character(
        path,
        world_id="world-a",
        operation_id="instance-a",
        expected_revision=1,
        character_id="fate",
        location_name="Elaris",
    )
    with pytest.raises(Exception, match="player"):
        instance_player_character(
            path,
            world_id="world-a",
            operation_id="instance-b",
            expected_revision=2,
            character_id="other",
            location_name="Other",
        )


async def _request(app, method: str, path: str, json: dict | None = None):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.request(method, path, json=json)
            return response.status_code, response.json()


def test_player_character_api_crud_and_world_selection(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _world(path, "world-a")
    app = create_app(path)
    status, body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/player-characters",
            {
                "character_id": "fate",
                "name": "Fate",
                "basic_info": "A diplomat",
                "operation_id": "api-create",
            },
        )
    )
    assert status == 201
    assert body["character_id"] == "fate"
    status, body = asyncio.run(_request(app, "GET", "/api/player-characters"))
    assert status == 200
    assert body == [
        {
            "id": "fate",
            "name": "Fate",
            "basic_info": "A diplomat",
            "created_at": body[0]["created_at"],
        }
    ]
    status, body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds/world-a/character-instance",
            {
                "character_id": "fate",
                "location_name": "Elaris",
                "operation_id": "api-instance",
                "expected_revision": 1,
            },
        )
    )
    assert status == 201
    assert body["world_revision"] == 2
    status, body = asyncio.run(
        _request(
            app,
            "PATCH",
            "/api/player-characters/fate",
            {"name": "Changed", "basic_info": "New info", "operation_id": "api-update"},
        )
    )
    assert status == 200
    status, body = asyncio.run(_request(app, "GET", "/api/worlds/world-a"))
    assert body["player"]["name"] == "Fate"
    assert body["player"]["basic_info"] == "A diplomat"
    status, _ = asyncio.run(
        _request(app, "DELETE", "/api/player-characters/fate?operation_id=api-remove")
    )
    assert status == 200
    status, body = asyncio.run(_request(app, "GET", "/api/worlds/world-a"))
    assert body["player"]["name"] == "Fate"


def test_narrator_world_start_instances_selected_character_and_replays(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _world(path, "world-a")
    create_player_character(
        path, character_id="fate", operation_id="create-1", name="Fate", basic_info="Diplomat"
    )
    calls = {"count": 0}

    def starter(world_id: str, world: dict, character: dict) -> NarratorStartResult:
        calls["count"] += 1
        assert world_id == "world-a"
        assert world["player"] is None
        assert character["id"] == "fate"
        return NarratorStartResult(
            "Elaris",
            "A moonlit guild square.",
            "You arrive beneath silver lanterns.",
            locations=(
                NarratorStartLocation("Elaris", "A square.", None, False),
                NarratorStartLocation("Guild Hall", "Guild doors.", "Elaris", True),
                NarratorStartLocation(
                    "North Road", "A road north.", None, False, "boundary", "north", "mid"
                ),
            ),
        )

    app = create_app(path, start_narrator=starter)
    payload = {"character_id": "fate", "operation_id": "start-1", "expected_revision": 1}
    status, body = asyncio.run(_request(app, "POST", "/api/worlds/world-a/start", payload))
    assert status == 201
    assert body["narration"] == "You arrive beneath silver lanterns."
    assert body["location_name"] == "Elaris"
    assert body["revision_before"] == 1
    assert body["revision_after"] == 2
    assert calls["count"] == 1
    import json
    import sqlite3

    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            "SELECT result_json FROM operations WHERE world_id = ? AND operation_id = ?",
            ("world-a", "start-1"),
        ).fetchone()[0]
    assert json.loads(stored)["narration"] == "You arrive beneath silver lanterns."

    status, replay = asyncio.run(_request(app, "POST", "/api/worlds/world-a/start", payload))
    assert status == 201
    assert replay == body
    assert calls["count"] == 1
    status, conflict = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds/world-a/start",
            {**payload, "expected_revision": 0},
        )
    )
    assert status == 409
    assert "different request" in conflict["detail"]
    world = read_world(path, "world-a")
    assert world["player"]["name"] == "Fate"
    assert world["player"]["location_name"] == "Elaris"
    world_map = get_world_map(path, world_id="world-a")
    north_road = next(item for item in world_map["locations"] if item["name"] == "North Road")
    assert north_road["geography_role"] == "boundary"
    assert north_road["direction"] == "north"
    assert north_road["range_band"] == "mid"
    with sqlite3.connect(path) as connection:
        assert [
            row[0]
            for row in connection.execute(
                "SELECT name FROM locations WHERE world_id = ? ORDER BY name", ("world-a",)
            )
        ] == ["Elaris", "Guild Hall", "North Road"]
        assert (
            connection.execute(
                "SELECT 1 FROM location_containment WHERE world_id = ? AND parent_location_id = ?",
                ("world-a", "world-a-start"),
            ).fetchone()
            is not None
        )
        assert connection.execute(
            "SELECT geography_role, direction, range_band FROM location_metadata "
            "WHERE world_id = ? AND location_id = ?",
            ("world-a", "world-a-start-4"),
        ).fetchone() == ("boundary", "north", "mid")


def test_narrator_world_start_failure_leaves_world_playerless(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _world(path, "world-a")
    create_player_character(path, character_id="fate", operation_id="create-1", name="Fate")

    def starter(world_id: str, world: dict, character: dict) -> NarratorStartResult:
        raise NarratorError(
            "narration agent returned invalid start JSON",
            category="invalid_start_response",
        )

    app = create_app(path, start_narrator=starter)
    status, body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds/world-a/start",
            {"character_id": "fate", "operation_id": "start-1", "expected_revision": 1},
        )
    )
    assert status == 502
    assert body["detail"] == "narration agent returned an invalid start response"
    assert read_world(path, "world-a")["player"] is None
