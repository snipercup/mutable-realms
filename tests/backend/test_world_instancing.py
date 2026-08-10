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
from backend.world.scenarios import (
    ScenarioNotFound,
    create_scenario,
    read_scenario,
    remove_scenario,
    set_scenario_element,
)
from backend.world.validation import validate_worlds
from backend.world.worlds import WorldAdminConflict, create_world_from_scenario


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
