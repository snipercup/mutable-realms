from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.queries import get_ward_bed, get_ward_location_state
from backend.world.queries import (
    EntityNotFound,
    LocationNotFound,
    PlayerNotFound,
    WorldNotFound,
    get_current_location,
    get_entity,
    get_location,
    get_player,
    list_recent_events,
)
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from tests.backend.general_world import GENERAL_WORLD_ID, seed_general_world


def _seeded_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    return database_path


def test_reads_current_player_and_location(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    player = get_player(database_path, WARD_WORLD_ID)
    location = get_current_location(database_path, WARD_WORLD_ID)

    assert player == {
        "id": "player",
        "world_id": WARD_WORLD_ID,
        "kind": "character",
        "name": "Player",
        "role": "player",
        "condition": None,
        "disposition": "active",
        "location_id": "ward",
    }
    assert location["id"] == "ward"
    assert location["world_id"] == WARD_WORLD_ID
    assert location["name"] == "Recovery Ward"
    assert location["revision"] == 0
    assert len(location["entities"]) == 13
    ward = get_ward_location_state(database_path, WARD_WORLD_ID, "ward")
    assert ward["bed_count"] == 6
    assert ward["occupied_bed_count"] == 6
    assert [bed["id"] for bed in ward["beds"]] == [
        "bed-1",
        "bed-2",
        "bed-3",
        "bed-4",
        "bed-5",
        "bed-6",
    ]
    assert ward["beds"][0]["occupant"] == {
        "id": "patient-1",
        "name": "Patient 1",
        "role": "patient",
        "condition": "untreated",
        "disposition": "admitted",
    }


def test_generic_reads_do_not_include_ward_capability_state(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)

    player = get_player(database_path, GENERAL_WORLD_ID)
    location = get_current_location(database_path, GENERAL_WORLD_ID)
    animal = get_entity(database_path, GENERAL_WORLD_ID, "hen")

    assert player["id"] == "farmer"
    assert player["location_id"] == "ocean-farm"
    assert location == {
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
    }
    assert animal["kind"] == "animal"
    assert animal["location_id"] == "ocean-farm"


def test_reads_character_and_bed_details(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    patient = get_entity(database_path, WARD_WORLD_ID, "patient-1")
    bed = get_entity(database_path, WARD_WORLD_ID, "bed-1")
    ward_bed = get_ward_bed(database_path, WARD_WORLD_ID, "bed-1")

    assert patient["role"] == "patient"
    assert patient["condition"] == "untreated"
    assert patient["location_id"] == "ward"
    assert bed["kind"] == "bed"
    assert bed["location_id"] == "ward"
    assert "occupant_id" not in bed
    assert ward_bed is not None
    assert ward_bed["occupant_entity_id"] == "patient-1"


def test_location_read_uses_one_sqlite_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = _seeded_database(tmp_path)
    statements: list[str] = []
    from backend.world import queries

    original_connect = queries.connect_database

    def traced_connect(path: Any):
        connection = original_connect(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(queries, "connect_database", traced_connect)

    get_location(database_path, WARD_WORLD_ID, "ward")

    assert "BEGIN" in statements


def test_current_location_uses_one_database_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = _seeded_database(tmp_path)
    from backend.world import queries

    original_connect = queries.connect_database
    connection_count = 0

    def counted_connect(path: Any):
        nonlocal connection_count
        connection_count += 1
        return original_connect(path)

    monkeypatch.setattr(queries, "connect_database", counted_connect)

    get_current_location(database_path, WARD_WORLD_ID)

    assert connection_count == 1


def test_recent_events_are_newest_first_and_limited(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    from backend.scenarios.ward.mutations import treat_and_discharge_patient

    treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="operation-1",
        expected_revision=0,
        patient_id="patient-1",
        bed_id="bed-1",
    )
    treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="operation-2",
        expected_revision=1,
        patient_id="patient-2",
        bed_id="bed-2",
    )

    events = list_recent_events(database_path, WARD_WORLD_ID, limit=1)

    assert len(events) == 1
    assert events[0]["operation_id"] == "operation-2"
    assert events[0]["world_revision"] == 2
    assert events[0]["payload"] == {
        "bed_id": "bed-2",
        "patient_id": "patient-2",
    }


def test_queries_reject_missing_or_mismatched_resources(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    with pytest.raises(PlayerNotFound):
        get_player(database_path, "missing-world")
    with pytest.raises(LocationNotFound):
        get_location(database_path, WARD_WORLD_ID, "missing-location")
    with pytest.raises(EntityNotFound):
        get_entity(database_path, WARD_WORLD_ID, "missing-entity")
    with pytest.raises(WorldNotFound):
        list_recent_events(database_path, "missing-world")
