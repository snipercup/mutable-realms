from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.town.seed import TOWN_WORLD_ID, seed_town_world
from backend.world.context import build_world_context
from backend.world.links import read_linked_locations
from backend.world.mutations import MutationConflict, move_entity
from backend.world.validation import validate_worlds


def _town_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    assert seed_town_world(database_path)
    return database_path


def test_town_seed_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    database_path = _town_database(tmp_path)

    assert seed_town_world(database_path) is False

    with connect_database(database_path) as connection:
        worlds = connection.execute("SELECT id FROM worlds ORDER BY id").fetchall()
        links = connection.execute(
            "SELECT location_a, location_b FROM location_links ORDER BY location_a"
        ).fetchall()
        player = connection.execute(
            "SELECT location_id FROM entity_locations WHERE entity_id = 'sailor'"
        ).fetchone()[0]

    assert [row[0] for row in worlds] == [TOWN_WORLD_ID]
    assert [tuple(row) for row in links] == [
        ("docks", "market"),
        ("docks", "tavern"),
        ("market", "plaza"),
        ("plaza", "tavern"),
    ]
    assert player == "plaza"
    assert validate_worlds(database_path) == []


def test_context_reports_linked_locations_for_travel_options(tmp_path: Path) -> None:
    database_path = _town_database(tmp_path)

    context = build_world_context(database_path, world_id=TOWN_WORLD_ID)

    assert {loc["id"] for loc in context.current_location.linked_locations} == {
        "market",
        "tavern",
    }


def test_travel_updates_player_location_and_working_set(tmp_path: Path) -> None:
    database_path = _town_database(tmp_path)

    before = build_world_context(database_path, world_id=TOWN_WORLD_ID)
    result = move_entity(
        database_path,
        world_id=TOWN_WORLD_ID,
        operation_id="travel-to-market",
        expected_revision=before.world.revision,
        entity_id="sailor",
        destination_location_id="market",
        actor_entity_id="sailor",
    )

    assert result.already_applied is False
    assert result.location_id == "market"
    after = build_world_context(database_path, world_id=TOWN_WORLD_ID)
    assert after.player.location_id == "market"
    assert after.current_location.id == "market"
    assert {entity.id for entity in after.current_location.entities} == {
        "sailor",
        "town-merchant",
        "town-provisions",
    }
    assert after.world.revision == 1
    assert after.recent_events[0].event_type == "entity_moved"
    assert validate_worlds(database_path) == []


def test_travel_rejects_unlinked_destination(tmp_path: Path) -> None:
    database_path = _town_database(tmp_path)

    with pytest.raises(MutationConflict, match="not adjacent"):
        move_entity(
            database_path,
            world_id=TOWN_WORLD_ID,
            operation_id="direct-to-docks",
            expected_revision=0,
            entity_id="sailor",
            destination_location_id="docks",
            actor_entity_id="sailor",
        )

    with connect_database(database_path) as connection:
        assert connection.execute("SELECT revision FROM worlds").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_travel_retry_is_idempotent(tmp_path: Path) -> None:
    database_path = _town_database(tmp_path)
    arguments = {
        "world_id": TOWN_WORLD_ID,
        "operation_id": "travel-replay",
        "expected_revision": 0,
        "entity_id": "sailor",
        "destination_location_id": "market",
        "actor_entity_id": "sailor",
    }

    first = move_entity(database_path, **arguments)
    replay = move_entity(database_path, **arguments)

    assert first.already_applied is False
    assert replay.already_applied is True
    assert replay.world_revision == 1


def test_read_linked_locations_is_undirected(tmp_path: Path) -> None:
    database_path = _town_database(tmp_path)

    from_plaza = read_linked_locations(
        database_path, world_id=TOWN_WORLD_ID, location_id="plaza"
    )["linked_locations"]
    from_market = read_linked_locations(
        database_path, world_id=TOWN_WORLD_ID, location_id="market"
    )["linked_locations"]

    assert {loc["id"] for loc in from_plaza} == {"market", "tavern"}
    assert {loc["id"] for loc in from_market} == {"docks", "plaza"}


def test_validation_reports_cross_world_location_link(tmp_path: Path) -> None:
    database_path = _town_database(tmp_path)
    with connect_database(database_path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('other-world', 'Other')")
        connection.execute(
            "INSERT INTO locations(id, world_id, name) "
            "VALUES ('other-place', 'other-world', 'Other')"
        )
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO location_links(world_id, location_a, location_b) "
            "VALUES ('town-world', 'docks', 'other-place')"
        )
        connection.commit()

    codes = {issue.code for issue in validate_worlds(database_path)}
    assert "location_link_world_mismatch" in codes


def test_api_readback_reflects_travel(tmp_path: Path) -> None:
    database_path = _town_database(tmp_path)
    move_entity(
        database_path,
        world_id=TOWN_WORLD_ID,
        operation_id="api-travel",
        expected_revision=0,
        entity_id="sailor",
        destination_location_id="tavern",
        actor_entity_id="sailor",
    )

    app = create_app(database_path)

    async def get_player() -> tuple[int, Any]:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(f"/api/worlds/{TOWN_WORLD_ID}/player")
        return response.status_code, response.json()

    status, player = asyncio.run(get_player())
    assert status == 200
    assert player["location_id"] == "tavern"
