from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.cli import main
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.world.context import build_world_context
from backend.world.queries import WorldQueryError, read_world
from backend.world.scenarios import (
    ScenarioNotFound,
    create_scenario,
    read_scenario,
    remove_scenario,
    set_scenario_element,
    set_scenario_region,
)
from backend.world.validation import validate_worlds
from backend.world.worlds import (
    WorldAdminConflict,
    WorldAdminNotFound,
    create_world_from_scenario,
    remove_world,
    set_world_element,
    update_world,
    world_provision_player,
)


def _database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    return database_path


def _scenario(database_path: Path, scenario_id: str = "aerthalon") -> None:
    create_scenario(
        database_path,
        scenario_id=scenario_id,
        operation_id="scenario-1",
        title="Aerthalon",
        description="A vast ancient fantasy world.",
    )
    for index, element_type in enumerate(
        ("author_note", "plot_essentials", "opening_scene")
    ):
        set_scenario_element(
            database_path,
            scenario_id=scenario_id,
            operation_id=f"scenario-element-{index + 1}",
            element_type=element_type,
            content=f"{element_type} content.",
        )


def _scenario_with_regions(database_path: Path, scenario_id: str = "aerthalon") -> None:
    _scenario(database_path, scenario_id=scenario_id)
    set_scenario_region(
        database_path,
        scenario_id=scenario_id,
        operation_id="scenario-region-1",
        region_id="virellea",
        level="kingdom",
        title="Virellea",
        description="The fertile heart of Aerthalon.",
        attributes={
            "biomes": ["Grassy Plains"],
            "connected_by_road_to": {"thurnrok": "NW"},
        },
    )
    set_scenario_region(
        database_path,
        scenario_id=scenario_id,
        operation_id="scenario-region-2",
        region_id="virellea-elaris",
        level="city",
        title="Elaris",
        description="Capital of Virellea.",
        parent_region_id="virellea",
    )


def _world_row(database_path: Path, world_id: str) -> dict[str, Any] | None:
    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT id, name, description, source_scenario_id, revision "
            "FROM worlds WHERE id = ?",
            (world_id,),
        ).fetchone()
    return None if row is None else dict(row)


def _world_elements(database_path: Path, world_id: str) -> list[dict[str, Any]]:
    with connect_database(database_path) as connection:
        rows = connection.execute(
            "SELECT element_type, content FROM world_elements "
            "WHERE world_id = ? ORDER BY element_type",
            (world_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _instance(
    database_path: Path,
    *,
    world_id: str = "aerthalon-campaign",
    operation_id: str = "world-instance-1",
    scenario_id: str = "aerthalon",
) -> dict[str, Any]:
    return create_world_from_scenario(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        scenario_id=scenario_id,
    )


def _add_player_fixture(database_path: Path, world_id: str) -> None:
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO locations (id, world_id, name, description) "
            "VALUES ('guild-city', ?, 'Guild City', 'The first city.')",
            (world_id,),
        )
        connection.execute(
            "INSERT INTO entities (id, world_id, kind, name) "
            "VALUES ('hero', ?, 'character', 'Hero')",
            (world_id,),
        )
        connection.execute(
            "INSERT INTO characters (entity_id, role, disposition) "
            "VALUES ('hero', 'player', 'active')"
        )
        connection.execute(
            "INSERT INTO entity_locations (entity_id, location_id) "
            "VALUES ('hero', 'guild-city')"
        )
        connection.commit()


# --- instancing ------------------------------------------------------------


def test_instancing_copies_title_description_and_elements(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)

    result = _instance(database_path)

    assert result == {
        "already_applied": False,
        "world_id": "aerthalon-campaign",
        "world_revision": 1,
        "source_scenario_id": "aerthalon",
        "copied_elements": ["author_note", "opening_scene", "plot_essentials"],
        "copied_regions": [],
    }
    world = _world_row(database_path, "aerthalon-campaign")
    assert world is not None
    assert world["name"] == "Aerthalon"
    assert world["description"] == "A vast ancient fantasy world."
    assert world["source_scenario_id"] == "aerthalon"
    assert world["revision"] == 1
    assert _world_elements(database_path, "aerthalon-campaign") == [
        {"element_type": "author_note", "content": "author_note content."},
        {"element_type": "opening_scene", "content": "opening_scene content."},
        {"element_type": "plot_essentials", "content": "plot_essentials content."},
    ]


def test_instancing_copies_scenario_regions_into_world(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario_with_regions(database_path)

    result = _instance(database_path)

    assert result["copied_regions"] == ["virellea", "virellea-elaris"]
    world = read_world(database_path, "aerthalon-campaign")
    assert [region["region_id"] for region in world["regions"]] == [
        "virellea",
        "virellea-elaris",
    ]
    virellea = next(r for r in world["regions"] if r["region_id"] == "virellea")
    assert virellea["level"] == "kingdom"
    assert virellea["parent_region_id"] is None
    assert virellea["location_id"] is None
    assert virellea["attributes"]["connected_by_road_to"] == {"thurnrok": "NW"}
    elaris = next(r for r in world["regions"] if r["region_id"] == "virellea-elaris")
    assert elaris["parent_region_id"] == "virellea"
    assert elaris["location_id"] is None


def test_instancing_records_world_created_event(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)
    _instance(database_path, operation_id="world-instance-1")

    with connect_database(database_path) as connection:
        event = connection.execute(
            "SELECT event_type, world_revision, summary, payload_json "
            "FROM events WHERE world_id = 'aerthalon-campaign'"
        ).fetchone()
        operation = connection.execute(
            "SELECT operation_id, operation_type, completed_revision "
            "FROM operations WHERE world_id = 'aerthalon-campaign'"
        ).fetchone()
    assert dict(event)["event_type"] == "world_created"
    assert dict(event)["world_revision"] == 1
    assert "aerthalon" in dict(event)["summary"]
    assert dict(event)["payload_json"] is not None
    assert dict(operation)["operation_id"] == "world-instance-1"
    assert dict(operation)["completed_revision"] == 1


def test_instancing_leaves_scenario_unchanged(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)
    before = read_scenario(database_path, "aerthalon")

    _instance(database_path)

    assert read_scenario(database_path, "aerthalon") == before


def test_instancing_diverges_when_scenario_is_edited(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)
    _instance(database_path)

    set_scenario_element(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-element-9",
        element_type="opening_scene",
        content="The gates have changed forever.",
    )

    elements = _world_elements(database_path, "aerthalon-campaign")
    opening = next(
        element for element in elements if element["element_type"] == "opening_scene"
    )
    assert opening["content"] == "opening_scene content."
    scenario_elements = read_scenario(database_path, "aerthalon")["elements"]
    scenario_opening = next(
        element
        for element in scenario_elements
        if element["element_type"] == "opening_scene"
    )
    assert scenario_opening["content"] == "The gates have changed forever."


def test_instancing_replays_exact_request(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)

    first = _instance(database_path)
    second = _instance(database_path)

    assert first["already_applied"] is False
    assert second["already_applied"] is True
    assert second["world_revision"] == 1
    with connect_database(database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM worlds WHERE id = 'aerthalon-campaign'"
        ).fetchone()["count"]
        event_count = connection.execute(
            "SELECT COUNT(*) AS count FROM events WHERE world_id = 'aerthalon-campaign'"
        ).fetchone()["count"]
    assert count == 1
    assert event_count == 1


def test_instancing_conflicts_on_duplicate_world_id(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)
    _instance(database_path)

    with pytest.raises(WorldAdminConflict, match="already exists"):
        _instance(database_path, operation_id="world-instance-2")


def test_instancing_missing_scenario_raises_not_found(tmp_path: Path) -> None:
    database_path = _database(tmp_path)

    with pytest.raises(ScenarioNotFound):
        _instance(database_path, scenario_id="missing-scenario")


def test_instancing_rejects_invalid_world_id(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)

    with pytest.raises(WorldAdminConflict, match="kebab-case"):
        _instance(database_path, world_id="Not Kebab!")


def test_deleting_scenario_keeps_instanced_world(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)
    _instance(database_path)

    remove_scenario(database_path, scenario_id="aerthalon", operation_id="remove-1")

    world = _world_row(database_path, "aerthalon-campaign")
    assert world is not None
    assert world["name"] == "Aerthalon"
    assert world["source_scenario_id"] is None
    assert len(_world_elements(database_path, "aerthalon-campaign")) == 3
    assert validate_worlds(database_path) == []


# --- context ---------------------------------------------------------------


def test_context_includes_world_metadata_and_elements(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)
    _instance(database_path)
    _add_player_fixture(database_path, "aerthalon-campaign")

    context = build_world_context(database_path, world_id="aerthalon-campaign")

    assert context.world.name == "Aerthalon"
    assert context.world.description == "A vast ancient fantasy world."
    assert context.world.source_scenario_id == "aerthalon"
    assert context.world.revision == 1
    assert [element["element_type"] for element in context.world_elements] == [
        "author_note",
        "opening_scene",
        "plot_essentials",
    ]


def test_validation_flags_world_element_event_mismatch(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)
    _instance(database_path)
    _instance(database_path, world_id="campaign-2", operation_id="world-instance-2")

    with connect_database(database_path) as connection:
        foreign_event = connection.execute(
            "SELECT id FROM events WHERE world_id = 'campaign-2' LIMIT 1"
        ).fetchone()
        assert foreign_event is not None
        connection.execute(
            "UPDATE world_elements SET updated_event_id = ? "
            "WHERE world_id = 'aerthalon-campaign' AND element_type = 'author_note'",
            (foreign_event["id"],),
        )
        connection.commit()

    codes = [issue.code for issue in validate_worlds(database_path)]
    assert "world_element_updated_event_mismatch" in codes


# --- CLI -------------------------------------------------------------------


def test_cli_create_world_from_scenario_roundtrip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = _database(tmp_path)
    db_args = ["--db-path", str(database_path)]
    assert main([*db_args, "create-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-1", "--title", "Aerthalon"]) == 0
    capsys.readouterr()

    assert main([*db_args, "create-world-from-scenario", "--world-id", "campaign-1",
                 "--operation-id", "op-2", "--scenario-id", "aerthalon"]) == 0
    captured = capsys.readouterr()
    assert '"world_revision": 1' in captured.out
    assert '"source_scenario_id": "aerthalon"' in captured.out

    assert main([*db_args, "create-world-from-scenario", "--world-id", "campaign-1",
                 "--operation-id", "op-2", "--scenario-id", "aerthalon"]) == 0
    captured = capsys.readouterr()
    assert '"already_applied": true' in captured.out

    assert main([*db_args, "create-world-from-scenario", "--world-id", "campaign-2",
                 "--operation-id", "op-3", "--scenario-id", "missing"]) == 2
    captured = capsys.readouterr()
    assert "scenario not found" in captured.err


# --- HTTP API --------------------------------------------------------------


async def _request(
    app: Any, method: str, path: str, **kwargs: Any
) -> tuple[int, Any]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.request(method, path, **kwargs)
    return response.status_code, response.json()


def test_world_api_create_from_scenario_roundtrip(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _scenario(database_path)
    app = create_app(database_path)

    status, body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds",
            json={
                "world_id": "campaign-1",
                "scenario_id": "aerthalon",
                "operation_id": "api-instance-1",
            },
        )
    )
    assert status == 201
    assert body["world_id"] == "campaign-1"
    assert body["world_revision"] == 1
    assert body["source_scenario_id"] == "aerthalon"

    status, body = asyncio.run(_request(app, "GET", "/api/worlds"))
    assert status == 200
    created = next(world for world in body if world["id"] == "campaign-1")
    assert created["name"] == "Aerthalon"
    assert created["description"] == "A vast ancient fantasy world."
    assert created["source_scenario_id"] == "aerthalon"

    status, body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds",
            json={
                "world_id": "campaign-1",
                "scenario_id": "aerthalon",
                "operation_id": "api-instance-1",
            },
        )
    )
    assert status == 201
    assert body["already_applied"] is True

    status, _ = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds",
            json={
                "world_id": "campaign-2",
                "scenario_id": "missing",
                "operation_id": "api-instance-2",
            },
        )
    )
    assert status == 404


def test_read_world_returns_metadata_and_elements(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)

    detail = read_world(database_path, "campaign-1")

    assert detail["name"] == "Aerthalon"
    assert detail["description"] == "A vast ancient fantasy world."
    assert detail["source_scenario_id"] == "aerthalon"
    assert detail["revision"] == 1
    element_types = [element["element_type"] for element in detail["elements"]]
    assert element_types == ["author_note", "opening_scene", "plot_essentials"]
    with pytest.raises(WorldQueryError):
        read_world(database_path, "missing")


def test_world_api_detail_endpoint(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)
    app = create_app(database_path)

    status, body = asyncio.run(_request(app, "GET", "/api/worlds/campaign-1"))
    assert status == 200
    assert body["name"] == "Aerthalon"
    assert body["source_scenario_id"] == "aerthalon"
    assert len(body["elements"]) == 3
    assert body["elements"][0]["element_type"] == "author_note"

    status, _ = asyncio.run(_request(app, "GET", "/api/worlds/missing"))
    assert status == 404


# --- player provisioning ---------------------------------------------------


def _world_without_player(database_path: Path, world_id: str = "campaign-1") -> None:
    _scenario(database_path)
    _instance(database_path, world_id=world_id)


def test_provision_player_creates_player_and_starting_location(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    _world_without_player(database_path)

    result = world_provision_player(
        database_path,
        world_id="campaign-1",
        operation_id="provision-1",
        expected_revision=1,
        player_name="fate",
        location_name="Settlement",
    )

    assert result["world_revision"] == 2
    assert result["player_id"] == "campaign-1-player"
    assert result["location_id"] == "campaign-1-start"
    with connect_database(database_path) as connection:
        player = connection.execute(
            "SELECT e.name, c.role FROM entities e "
            "JOIN characters c ON c.entity_id = e.id "
            "WHERE e.id = 'campaign-1-player'"
        ).fetchone()
        assert dict(player) == {"name": "fate", "role": "player"}
        placement = connection.execute(
            "SELECT location_id FROM entity_locations "
            "WHERE entity_id = 'campaign-1-player'"
        ).fetchone()
        assert dict(placement)["location_id"] == "campaign-1-start"
        event = connection.execute(
            "SELECT event_type, world_revision FROM events "
            "WHERE world_id = 'campaign-1' AND event_type = 'player_provisioned'"
        ).fetchone()
        assert dict(event)["world_revision"] == 2
    # the world now reads as playable: player visible in detail, context builds
    detail = read_world(database_path, "campaign-1")
    assert detail["player"]["name"] == "fate"
    assert detail["player"]["location_name"] == "Settlement"
    context = build_world_context(database_path, world_id="campaign-1")
    assert context.player.id == "campaign-1-player"
    assert validate_worlds(database_path) == []


def test_provision_player_conflicts_and_validates(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _world_without_player(database_path)

    world_provision_player(
        database_path,
        world_id="campaign-1",
        operation_id="provision-2",
        expected_revision=1,
        player_name="fate",
        location_name="Settlement",
    )
    with pytest.raises(WorldAdminConflict, match="already has a player"):
        world_provision_player(
            database_path,
            world_id="campaign-1",
            operation_id="provision-3",
            expected_revision=2,
            player_name="fate",
            location_name="Settlement",
        )
    with pytest.raises(WorldAdminConflict, match="expected world revision"):
        world_provision_player(
            database_path,
            world_id="campaign-1",
            operation_id="provision-4",
            expected_revision=1,
            player_name="other",
            location_name="Settlement",
        )
    with pytest.raises(WorldAdminConflict, match="player name must not be blank"):
        world_provision_player(
            database_path,
            world_id="campaign-1",
            operation_id="provision-5",
            expected_revision=2,
            player_name="   ",
            location_name="Settlement",
        )
    with pytest.raises(WorldAdminNotFound):
        world_provision_player(
            database_path,
            world_id="missing",
            operation_id="provision-6",
            expected_revision=0,
            player_name="fate",
            location_name="Settlement",
        )


def test_provision_player_replays_exact_request(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _world_without_player(database_path)

    first = world_provision_player(
        database_path,
        world_id="campaign-1",
        operation_id="provision-7",
        expected_revision=1,
        player_name="fate",
        location_name="Settlement",
    )
    second = world_provision_player(
        database_path,
        world_id="campaign-1",
        operation_id="provision-7",
        expected_revision=1,
        player_name="fate",
        location_name="Settlement",
    )
    assert first["already_applied"] is False
    assert second["already_applied"] is True
    with connect_database(database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM entities WHERE world_id = 'campaign-1'"
        ).fetchone()["count"]
    assert count == 1


def test_provision_player_reuses_name_across_worlds(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _world_without_player(database_path, world_id="campaign-1")
    _instance(database_path, world_id="campaign-2", operation_id="world-instance-2")

    world_provision_player(
        database_path,
        world_id="campaign-1",
        operation_id="provision-8",
        expected_revision=1,
        player_name="fate",
        location_name="Settlement",
    )
    world_provision_player(
        database_path,
        world_id="campaign-2",
        operation_id="provision-9",
        expected_revision=1,
        player_name="fate",
        location_name="Camp",
    )
    with connect_database(database_path) as connection:
        players = connection.execute(
            "SELECT e.world_id, e.name FROM entities e "
            "JOIN characters c ON c.entity_id = e.id "
            "WHERE c.role = 'player' ORDER BY e.world_id"
        ).fetchall()
    assert [dict(row) for row in players] == [
        {"name": "fate", "world_id": "campaign-1"},
        {"name": "fate", "world_id": "campaign-2"},
    ]


def test_cli_and_api_provision_player(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database_path = _database(tmp_path)
    db_args = ["--db-path", str(database_path)]
    assert main([*db_args, "create-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-1", "--title", "Aerthalon"]) == 0
    capsys.readouterr()
    assert main([*db_args, "create-world-from-scenario", "--world-id", "campaign-1",
                 "--operation-id", "op-2", "--scenario-id", "aerthalon"]) == 0
    capsys.readouterr()

    assert main([*db_args, "provision-player", "--world-id", "campaign-1",
                 "--operation-id", "op-3", "--expected-revision", "1",
                 "--player-name", "fate", "--location-name", "Settlement"]) == 0
    captured = capsys.readouterr()
    assert '"world_revision": 2' in captured.out
    assert "campaign-1-player" in captured.out

    assert main([*db_args, "provision-player", "--world-id", "campaign-1",
                 "--operation-id", "op-4", "--expected-revision", "2",
                 "--player-name", "fate", "--location-name", "Settlement"]) == 2
    captured = capsys.readouterr()
    assert "already has a player" in captured.err

    app = create_app(database_path)
    status, body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds/campaign-2/player",
            json={
                "player_name": "fate",
                "location_name": "Camp",
                "operation_id": "api-provision-1",
                "expected_revision": 0,
            },
        )
    )
    # campaign-2 does not exist yet; create it first
    assert status == 404


# --- world management: update / set element / remove -----------------------


def _instanced(database_path: Path, world_id: str = "campaign-1") -> None:
    _scenario(database_path)
    _instance(database_path, world_id=world_id)


def test_update_world_sets_title_and_description(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)

    result = update_world(
        database_path,
        world_id="campaign-1",
        operation_id="update-1",
        expected_revision=1,
        title="Aerthalon Reborn",
        description=None,
    )

    assert result == {
        "already_applied": False,
        "world_id": "campaign-1",
        "world_revision": 2,
    }
    world = _world_row(database_path, "campaign-1")
    assert world is not None
    assert world["name"] == "Aerthalon Reborn"
    assert world["description"] == "A vast ancient fantasy world."
    assert world["revision"] == 2
    with connect_database(database_path) as connection:
        event = connection.execute(
            "SELECT event_type, world_revision FROM events "
            "WHERE world_id = 'campaign-1' AND event_type = 'world_updated'"
        ).fetchone()
    assert dict(event)["world_revision"] == 2


def test_update_world_requires_a_field_and_rejects_stale_revision(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)

    with pytest.raises(WorldAdminConflict, match="title or description"):
        update_world(
            database_path,
            world_id="campaign-1",
            operation_id="update-2",
            expected_revision=1,
        )
    with pytest.raises(WorldAdminConflict, match="expected world revision"):
        update_world(
            database_path,
            world_id="campaign-1",
            operation_id="update-3",
            expected_revision=9,
            title="Wrong revision",
        )
    row = _world_row(database_path, "campaign-1")
    assert row is not None
    assert row["revision"] == 1


def test_update_world_replays_exact_request(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)

    first = update_world(
        database_path,
        world_id="campaign-1",
        operation_id="update-4",
        expected_revision=1,
        title="Renamed",
    )
    second = update_world(
        database_path,
        world_id="campaign-1",
        operation_id="update-4",
        expected_revision=1,
        title="Renamed",
    )
    assert first["already_applied"] is False
    assert second["already_applied"] is True
    row = _world_row(database_path, "campaign-1")
    assert row is not None
    assert row["revision"] == 2


def test_set_world_element_upserts_and_links_event(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)

    result = set_world_element(
        database_path,
        world_id="campaign-1",
        operation_id="element-1",
        expected_revision=1,
        element_type="opening_scene",
        content="The gates have changed forever.",
    )

    assert result["world_revision"] == 2
    elements = _world_elements(database_path, "campaign-1")
    opening = next(
        element for element in elements if element["element_type"] == "opening_scene"
    )
    assert opening["content"] == "The gates have changed forever."
    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT we.updated_event_id, ev.event_type "
            "FROM world_elements we "
            "JOIN events ev ON ev.id = we.updated_event_id "
            "WHERE we.world_id = 'campaign-1' AND we.element_type = 'opening_scene'"
        ).fetchone()
    assert dict(row)["event_type"] == "world_element_updated"
    assert validate_worlds(database_path) == []


def test_set_world_element_does_not_touch_scenario(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)

    set_world_element(
        database_path,
        world_id="campaign-1",
        operation_id="element-2",
        expected_revision=1,
        element_type="opening_scene",
        content="World-only opening.",
    )

    scenario_elements = read_scenario(database_path, "aerthalon")["elements"]
    scenario_opening = next(
        element
        for element in scenario_elements
        if element["element_type"] == "opening_scene"
    )
    assert scenario_opening["content"] == "opening_scene content."
    elements = _world_elements(database_path, "campaign-1")
    world_opening = next(
        element for element in elements if element["element_type"] == "opening_scene"
    )
    assert world_opening["content"] == "World-only opening."


def test_set_world_element_validates_type_and_content(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)

    with pytest.raises(WorldAdminConflict, match="element type"):
        set_world_element(
            database_path,
            world_id="campaign-1",
            operation_id="element-3",
            expected_revision=1,
            element_type="character_sheet",
            content="nope",
        )
    with pytest.raises(WorldAdminConflict, match="at most 20000"):
        set_world_element(
            database_path,
            world_id="campaign-1",
            operation_id="element-4",
            expected_revision=1,
            element_type="author_note",
            content="x" * 20_001,
        )


def test_remove_world_cascades_all_state_and_keeps_scenario(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)
    _add_player_fixture(database_path, "campaign-1")
    set_world_element(
        database_path,
        world_id="campaign-1",
        operation_id="element-5",
        expected_revision=1,
        element_type="author_note",
        content="Note.",
    )
    _instance(database_path, world_id="campaign-2", operation_id="world-instance-2")

    result = remove_world(
        database_path,
        world_id="campaign-1",
        operation_id="remove-1",
        expected_revision=2,
    )

    assert result["removed"] is True
    assert result["world_revision"] == 2
    with connect_database(database_path) as connection:
        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE world_id = 'campaign-1'"
            ).fetchone()["count"]
            for table in (
                "locations",
                "entities",
                "world_elements",
                "operations",
                "events",
            )
        }
        entity_locations = connection.execute(
            "SELECT COUNT(*) AS count FROM entity_locations el "
            "JOIN entities e ON e.id = el.entity_id "
            "WHERE e.world_id = 'campaign-1'"
        ).fetchone()["count"]
    assert counts == {
        "locations": 0,
        "entities": 0,
        "world_elements": 0,
        "operations": 0,
        "events": 0,
    }
    assert entity_locations == 0
    assert _world_row(database_path, "campaign-2") is not None
    assert read_scenario(database_path, "aerthalon")["title"] == "Aerthalon"
    assert validate_worlds(database_path) == []


def test_remove_world_cascades_nested_location_containment(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)
    with connect_database(database_path) as connection:
        connection.executemany(
            "INSERT INTO locations(id, world_id, name, description) "
            "VALUES (?, 'campaign-1', ?, '')",
            [("main-street", "Main Street"), ("guild", "Adventurer's Guild")],
        )
        connection.execute(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES ('campaign-1', 'guild', 'main-street')"
        )
        connection.commit()

    result = remove_world(
        database_path,
        world_id="campaign-1",
        operation_id="remove-nested",
        expected_revision=1,
    )

    assert result["removed"] is True
    with connect_database(database_path) as connection:
        assert connection.execute("SELECT 1 FROM worlds WHERE id = 'campaign-1'").fetchone() is None


def test_remove_world_stale_revision_and_missing(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)

    with pytest.raises(WorldAdminConflict, match="expected world revision"):
        remove_world(
            database_path,
            world_id="campaign-1",
            operation_id="remove-2",
            expected_revision=9,
        )
    with pytest.raises(WorldAdminNotFound):
        remove_world(
            database_path,
            world_id="missing",
            operation_id="remove-3",
            expected_revision=0,
        )
    assert _world_row(database_path, "campaign-1") is not None


def test_cli_world_management_roundtrip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = _database(tmp_path)
    db_args = ["--db-path", str(database_path)]
    assert main([*db_args, "create-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-1", "--title", "Aerthalon"]) == 0
    capsys.readouterr()
    assert main([*db_args, "create-world-from-scenario", "--world-id", "campaign-1",
                 "--operation-id", "op-2", "--scenario-id", "aerthalon"]) == 0
    capsys.readouterr()

    assert main([*db_args, "update-world", "--world-id", "campaign-1",
                 "--operation-id", "op-3", "--expected-revision", "1",
                 "--title", "Aerthalon Reborn"]) == 0
    assert main([*db_args, "set-world-element", "--world-id", "campaign-1",
                 "--operation-id", "op-4", "--expected-revision", "2",
                 "--element-type", "opening_scene", "--content", "New opening."]) == 0
    captured = capsys.readouterr()
    assert '"world_revision": 3' in captured.out

    assert main([*db_args, "remove-world", "--world-id", "campaign-1",
                 "--operation-id", "op-5", "--expected-revision", "3"]) == 0
    captured = capsys.readouterr()
    assert '"removed": true' in captured.out

    assert main([*db_args, "remove-world", "--world-id", "campaign-1",
                 "--operation-id", "op-6", "--expected-revision", "3"]) == 2
    captured = capsys.readouterr()
    assert "world not found" in captured.err


def test_world_api_management_roundtrip(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _instanced(database_path)
    app = create_app(database_path)

    status, _ = asyncio.run(
        _request(
            app,
            "PATCH",
            "/api/worlds/campaign-1",
            json={
                "title": "Aerthalon Reborn",
                "operation_id": "api-update-1",
                "expected_revision": 1,
            },
        )
    )
    assert status == 200

    status, _ = asyncio.run(
        _request(
            app,
            "PUT",
            "/api/worlds/campaign-1/elements/opening_scene",
            json={
                "content": "API opening.",
                "operation_id": "api-element-1",
                "expected_revision": 2,
            },
        )
    )
    assert status == 200

    status, body = asyncio.run(_request(app, "GET", "/api/worlds"))
    assert status == 200
    world = next(item for item in body if item["id"] == "campaign-1")
    assert world["name"] == "Aerthalon Reborn"
    assert world["revision"] == 3

    status, body = asyncio.run(
        _request(
            app,
            "PATCH",
            "/api/worlds/campaign-1",
            json={
                "title": "Stale",
                "operation_id": "api-update-2",
                "expected_revision": 1,
            },
        )
    )
    assert status == 409
    assert "expected world revision" in body["detail"]

    status, _ = asyncio.run(
        _request(
            app,
            "DELETE",
            "/api/worlds/campaign-1?operation_id=api-remove-1&expected_revision=3",
        )
    )
    assert status == 200

    status, _ = asyncio.run(
        _request(
            app,
            "DELETE",
            "/api/worlds/campaign-1?operation_id=api-remove-2&expected_revision=3",
        )
    )
    assert status == 404
