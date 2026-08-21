from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.agent_tools import (
    inspect_entity,
    list_events,
    move_world_entity,
    read_world_status,
    treat_and_discharge_world_patient,
    validate_world_state,
)
from backend.world.mutations import StaleWorldRevision
from tests.backend.general_world import GENERAL_WORLD_ID, seed_general_world


def _seeded_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)
    seed_ward_world(database_path)
    return database_path


def test_status_reports_revision_and_only_supported_mutations(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    generic = read_world_status(database_path, world_id=GENERAL_WORLD_ID)
    ward = read_world_status(database_path, world_id=WARD_WORLD_ID)

    assert generic == {
        "world": {"id": GENERAL_WORLD_ID, "name": "Open World", "revision": 0},
        "available_mutations": [
            "world_move_entity",
            "world_transfer_resource",
            "world_update_location",
            "world_expand_location",
            "world_record_location_memory",
            "world_consolidate_location_memories",
            "world_create_route",
        ],
    }
    assert ward == {
        "world": {"id": WARD_WORLD_ID, "name": "Recovery Ward", "revision": 0},
        "available_mutations": [
            "world_move_entity",
            "world_treat_and_discharge_patient",
            "world_record_social_interaction",
            "world_transfer_resource",
            "world_update_location",
            "world_expand_location",
            "world_record_location_memory",
            "world_consolidate_location_memories",
            "world_create_route",
        ],
    }


def test_inspect_and_events_return_authoritative_read_models(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    entity = inspect_entity(database_path, world_id=GENERAL_WORLD_ID, entity_id="hen")
    events = list_events(database_path, world_id=GENERAL_WORLD_ID, limit=10)

    assert entity["id"] == "hen"
    assert entity["kind"] == "animal"
    assert entity["location_id"] == "ocean-farm"
    assert events == []


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_events_reject_out_of_range_limits(tmp_path: Path, limit: int) -> None:
    database_path = _seeded_database(tmp_path)

    with pytest.raises(ValueError, match="between 1 and 100"):
        list_events(database_path, world_id=GENERAL_WORLD_ID, limit=limit)


@pytest.mark.parametrize("read_operation", ["inspect", "events"])
def test_agent_reads_do_not_create_a_missing_database(tmp_path: Path, read_operation: str) -> None:
    database_path = tmp_path / "missing.sqlite3"

    with pytest.raises(sqlite3.OperationalError):
        if read_operation == "inspect":
            inspect_entity(database_path, world_id="missing", entity_id="missing")
        else:
            list_events(database_path, world_id="missing")

    assert not database_path.exists()


def test_move_tool_delegates_to_revision_checked_operation(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO location_links(world_id, location_a, location_b) "
            "VALUES (?, 'kelp-market', 'ocean-farm')",
            (GENERAL_WORLD_ID,),
        )
        connection.commit()

    result = move_world_entity(
        database_path,
        world_id=GENERAL_WORLD_ID,
        operation_id="move-farmer",
        expected_revision=0,
        entity_id="farmer",
        destination_location_id="kelp-market",
        actor_entity_id="farmer",
    )

    assert result == {
        "already_applied": False,
        "entity_id": "farmer",
        "location_id": "kelp-market",
        "world_revision": 1,
    }
    assert read_world_status(database_path, world_id=GENERAL_WORLD_ID)["world"]["revision"] == 1
    with pytest.raises(StaleWorldRevision):
        move_world_entity(
            database_path,
            world_id=GENERAL_WORLD_ID,
            operation_id="another-move",
            expected_revision=0,
            entity_id="farmer",
            destination_location_id="ocean-farm",
        )


def test_ward_tool_delegates_to_atomic_scenario_operation(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    result = treat_and_discharge_world_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="discharge-patient-1",
        expected_revision=0,
        patient_id="patient-1",
        bed_id="bed-1",
        actor_entity_id="player",
    )

    assert result == {"already_applied": False, "world_revision": 1}
    patient = inspect_entity(database_path, world_id=WARD_WORLD_ID, entity_id="patient-1")
    assert patient["condition"] == "recovered"
    assert patient["disposition"] == "discharged"
    assert patient["location_id"] is None


def test_validation_tool_returns_structured_deterministic_issues(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    with connect_database(database_path) as connection:
        connection.execute("UPDATE worlds SET revision = 3 WHERE id = ?", (GENERAL_WORLD_ID,))
        connection.commit()

    result = validate_world_state(database_path)

    assert result == {
        "valid": False,
        "issues": [
            {
                "code": "world_history_revision_mismatch",
                "message": "World revision 3 has 0 operations and 0 events",
                "entity_id": GENERAL_WORLD_ID,
            }
        ],
    }


def test_validation_does_not_create_a_missing_database(tmp_path: Path) -> None:
    database_path = tmp_path / "missing.sqlite3"

    with pytest.raises(sqlite3.OperationalError):
        validate_world_state(database_path)

    assert not database_path.exists()
