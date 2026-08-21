from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.mutations import treat_and_discharge_patient
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.context import build_world_context
from backend.world.queries import LocationNotFound, PlayerNotFound, WorldNotFound
from tests.backend.general_world import GENERAL_WORLD_ID, seed_general_world


def test_builds_scenario_neutral_context_for_current_location(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)

    context = build_world_context(database_path, world_id=GENERAL_WORLD_ID)

    assert context.model_dump() == {
        "world": {
            "id": GENERAL_WORLD_ID,
            "name": "Open World",
            "revision": 0,
            "description": None,
            "source_scenario_id": None,
        },
        "player": {
            "id": "farmer",
            "world_id": GENERAL_WORLD_ID,
            "kind": "character",
            "name": "The Farmer",
            "role": "player",
            "condition": None,
            "disposition": "active",
            "location_id": "ocean-farm",
        },
        "current_location": {
            "id": "ocean-farm",
            "world_id": GENERAL_WORLD_ID,
            "name": "Ocean Farm",
            "description": "A farm on the ocean floor.",
            "revision": 0,
            "entities": [
                {
                    "id": "basket",
                    "kind": "item",
                    "name": "Egg Basket",
                    "role": None,
                    "condition": None,
                    "disposition": None,
                },
                {
                    "id": "farmer",
                    "kind": "character",
                    "name": "The Farmer",
                    "role": "player",
                    "condition": None,
                    "disposition": "active",
                },
                {
                    "id": "hen",
                    "kind": "animal",
                    "name": "Henrietta",
                    "role": None,
                    "condition": None,
                    "disposition": None,
                },
            ],
            "properties": [],
            "memories": [],
            "linked_locations": [],
        },
        "location_breadcrumbs": [],
        "map_scope": None,
        "region_framework": [],
        "recent_events": [],
        "relationships": [],
        "memories": [],
        "resources": [],
        "world_elements": [],
    }


def test_context_includes_containment_breadcrumb_and_preferred_scope(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)
    from backend.persistence.database import connect_database

    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO locations(id, world_id, name, description) "
            "VALUES ('seafloor-road', ?, 'Seafloor Road', '')",
            (GENERAL_WORLD_ID,),
        )
        connection.execute(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES (?, 'ocean-farm', 'seafloor-road')",
            (GENERAL_WORLD_ID,),
        )
        connection.execute(
            "INSERT INTO location_metadata("
            "world_id, location_id, kind, is_map_scope, is_default_scope) "
            "VALUES (?, 'seafloor-road', 'street', 1, 1)",
            (GENERAL_WORLD_ID,),
        )
        connection.commit()

    context = build_world_context(database_path, world_id=GENERAL_WORLD_ID)

    assert [item.id for item in context.location_breadcrumbs] == ["seafloor-road"]
    assert context.map_scope is not None
    assert context.map_scope.id == "seafloor-road"
    assert context.current_location.linked_locations == []


@pytest.mark.parametrize("limit", [0, 101])
def test_rejects_event_limits_outside_explicit_bounds(tmp_path: Path, limit: int) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)

    with pytest.raises(ValueError, match="recent event limit must be between 1 and 100"):
        build_world_context(
            database_path,
            world_id=GENERAL_WORLD_ID,
            recent_event_limit=limit,
        )


def test_context_uses_one_read_only_sqlite_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)
    statements: list[str] = []
    connection_count = 0
    from backend.world import context as context_module
    from backend.world import queries as queries_module

    original_connect = context_module.connect_readonly_database

    def traced_connect(path: Any):
        nonlocal connection_count
        connection_count += 1
        connection = original_connect(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(context_module, "connect_readonly_database", traced_connect)
    monkeypatch.setattr(queries_module, "connect_readonly_database", traced_connect)

    build_world_context(database_path, world_id=GENERAL_WORLD_ID)

    assert connection_count == 1
    assert "BEGIN" in statements
    assert all(
        statement.lstrip().upper().startswith(("BEGIN", "SELECT", "WITH"))
        for statement in statements
    )


def test_context_limits_newest_first_events_without_ward_projection(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="discharge-1",
        expected_revision=0,
        patient_id="patient-1",
        bed_id="bed-1",
    )
    treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="discharge-2",
        expected_revision=1,
        patient_id="patient-2",
        bed_id="bed-2",
    )

    context = build_world_context(database_path, world_id=WARD_WORLD_ID, recent_event_limit=1)
    payload = context.model_dump()

    assert context.world.revision == 2
    assert context.current_location.revision == 2
    assert [event.operation_id for event in context.recent_events] == ["discharge-2"]
    assert "beds" not in payload["current_location"]
    assert "bed_count" not in payload["current_location"]
    assert "occupied_bed_count" not in payload["current_location"]


def test_context_reports_missing_authoritative_resources(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)

    with pytest.raises(WorldNotFound):
        build_world_context(database_path, world_id="missing-world")

    seed_general_world(database_path)
    from backend.persistence.database import connect_database

    with connect_database(database_path) as connection:
        connection.execute("DELETE FROM characters WHERE entity_id = 'farmer'")
        connection.commit()
    with pytest.raises(PlayerNotFound):
        build_world_context(database_path, world_id=GENERAL_WORLD_ID)

    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO characters(entity_id, role, disposition) "
            "VALUES ('farmer', 'player', 'active')"
        )
        connection.execute("DELETE FROM entity_locations WHERE entity_id = 'farmer'")
        connection.commit()
    with pytest.raises(LocationNotFound):
        build_world_context(database_path, world_id=GENERAL_WORLD_ID)


def test_context_does_not_create_a_missing_database(tmp_path: Path) -> None:
    database_path = tmp_path / "missing" / "world.sqlite3"

    with pytest.raises(sqlite3.OperationalError):
        build_world_context(database_path, world_id="missing-world")

    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_context_connection_rejects_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)
    from backend.world import context as context_module

    original_get_player = context_module.get_player

    def attempted_write(
        database_path: Any,
        world_id: str,
        *,
        _connection: Any,
    ):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            _connection.execute("UPDATE worlds SET name = 'Changed' WHERE id = ?", (world_id,))
        return original_get_player(database_path, world_id, _connection=_connection)

    monkeypatch.setattr(context_module, "get_player", attempted_write)

    context = build_world_context(database_path, world_id=GENERAL_WORLD_ID)

    assert context.world.name == "Open World"


def test_context_reads_committed_wal_state_without_mutating_world_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)
    from backend.persistence.database import connect_database

    with connect_database(database_path) as writer:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute(
            "UPDATE worlds SET name = 'Open World Updated', revision = 1 WHERE id = ?",
            (GENERAL_WORLD_ID,),
        )
        writer.commit()
        authoritative_before = tuple(
            writer.execute(
                "SELECT name, revision FROM worlds WHERE id = ?",
                (GENERAL_WORLD_ID,),
            ).fetchone()
        )

        context = build_world_context(database_path, world_id=GENERAL_WORLD_ID)

        authoritative_after = tuple(
            writer.execute(
                "SELECT name, revision FROM worlds WHERE id = ?",
                (GENERAL_WORLD_ID,),
            ).fetchone()
        )

    assert context.world.name == "Open World Updated"
    assert context.world.revision == 1
    assert context.current_location.revision == 1
    assert authoritative_after == authoritative_before
