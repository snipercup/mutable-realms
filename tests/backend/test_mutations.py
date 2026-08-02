from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.mutations import treat_and_discharge_patient
from backend.world.mutations import (
    MutationConflict,
    MutationNotFound,
    StaleWorldRevision,
    move_entity,
)
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.validation import validate_worlds
from tests.backend.general_world import GENERAL_WORLD_ID, seed_general_world


def _seeded_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    return database_path


def _add_location(database_path: Path, location_id: str = "hall") -> None:
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO locations(id, world_id, name) VALUES (?, ?, ?)",
            (location_id, WARD_WORLD_ID, "Hall"),
        )
        connection.commit()


def test_move_entity_works_in_a_world_without_ward_state(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)

    result = move_entity(
        database_path,
        world_id=GENERAL_WORLD_ID,
        operation_id="visit-market",
        expected_revision=0,
        entity_id="farmer",
        destination_location_id="kelp-market",
        actor_entity_id="farmer",
    )

    assert result.world_revision == 1
    with connect_database(database_path) as connection:
        assert connection.execute(
            "SELECT location_id FROM entity_locations WHERE entity_id = 'farmer'"
        ).fetchone()[0] == "kelp-market"
        assert connection.execute(
            "SELECT event_type FROM events WHERE world_id = ?", (GENERAL_WORLD_ID,)
        ).fetchone()[0] == "entity_moved"
    assert validate_worlds(database_path) == []


def test_generic_validation_does_not_infer_capabilities_from_labels(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)
    with connect_database(database_path) as connection:
        connection.executemany(
            "INSERT INTO entities(id, world_id, kind, name) VALUES (?, ?, ?, ?)",
            [
                ("resting-place", GENERAL_WORLD_ID, "bed", "Kelp Hammock"),
                ("off-scene", GENERAL_WORLD_ID, "character", "Distant Diver"),
            ],
        )
        connection.execute(
            """
            INSERT INTO characters(entity_id, role, disposition)
            VALUES ('off-scene', 'deep-sea-hermit', 'exploring')
            """
        )

    assert validate_worlds(database_path) == []


def test_move_entity_persists_placement_operation_and_event(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    _add_location(database_path)

    result = move_entity(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="move-player-1",
        expected_revision=0,
        entity_id="player",
        destination_location_id="hall",
        actor_entity_id="player",
    )

    assert result.world_revision == 1
    assert result.already_applied is False
    assert result.entity_id == "player"
    assert result.location_id == "hall"
    with connect_database(database_path) as connection:
        placement = connection.execute(
            "SELECT location_id FROM entity_locations WHERE entity_id = 'player'"
        ).fetchone()[0]
        operation = connection.execute(
            "SELECT operation_type, request_json, result_json FROM operations"
        ).fetchone()
        event = connection.execute(
            "SELECT event_type, actor_entity_id, payload_json, world_revision FROM events"
        ).fetchone()

    assert placement == "hall"
    assert operation["operation_type"] == "entity_moved"
    assert json.loads(operation["request_json"]) == {
        "actor_entity_id": "player",
        "destination_location_id": "hall",
        "entity_id": "player",
        "expected_revision": 0,
    }
    assert json.loads(operation["result_json"]) == {
        "entity_id": "player",
        "location_id": "hall",
        "world_revision": 1,
    }
    assert tuple(event[:2]) == ("entity_moved", "player")
    assert json.loads(event["payload_json"]) == {
        "destination_location_id": "hall",
        "entity_id": "player",
        "source_location_id": "ward",
    }
    assert event["world_revision"] == 1
    assert validate_worlds(database_path) == []


def test_move_entity_retry_is_idempotent_and_changed_request_conflicts(
    tmp_path: Path,
) -> None:
    database_path = _seeded_database(tmp_path)
    _add_location(database_path)
    arguments = {
        "world_id": WARD_WORLD_ID,
        "operation_id": "move-player-1",
        "expected_revision": 0,
        "entity_id": "player",
        "destination_location_id": "hall",
        "actor_entity_id": "player",
    }

    first = move_entity(database_path, **arguments)
    retry = move_entity(database_path, **arguments)

    assert first.already_applied is False
    assert retry.already_applied is True
    assert retry.world_revision == 1
    with pytest.raises(MutationConflict, match="operation ID"):
        move_entity(database_path, **{**arguments, "expected_revision": 1})
    with connect_database(database_path) as connection:
        assert connection.execute("SELECT revision FROM worlds").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_move_entity_rejects_stale_and_invariant_breaking_moves(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    _add_location(database_path)
    with connect_database(database_path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('other-world', 'Other')")
        connection.execute(
            "INSERT INTO locations(id, world_id, name) "
            "VALUES ('other-location', 'other-world', 'Other')"
        )
        connection.commit()

    with pytest.raises(StaleWorldRevision):
        move_entity(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="stale-move",
            expected_revision=1,
            entity_id="player",
            destination_location_id="hall",
        )
    with pytest.raises(MutationNotFound, match="location"):
        move_entity(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="cross-world-move",
            expected_revision=0,
            entity_id="player",
            destination_location_id="other-location",
        )
    with pytest.raises(MutationConflict, match="occupies bed"):
        move_entity(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="patient-move",
            expected_revision=0,
            entity_id="patient-1",
            destination_location_id="hall",
        )

    with connect_database(database_path) as connection:
        assert connection.execute("SELECT revision FROM worlds").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute(
            "SELECT location_id FROM entity_locations WHERE entity_id = 'player'"
        ).fetchone()[0] == "ward"


def test_move_entity_rejects_character_entity_without_character_state(
    tmp_path: Path,
) -> None:
    database_path = _seeded_database(tmp_path)
    _add_location(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO entities(id, world_id, kind, name) "
            "VALUES ('incomplete', 'ward-world', 'character', 'Incomplete')"
        )
        connection.execute(
            "INSERT INTO entity_locations(entity_id, location_id) "
            "VALUES ('incomplete', 'ward')"
        )
        connection.commit()

    with pytest.raises(MutationConflict, match="missing character state"):
        move_entity(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="move-incomplete",
            expected_revision=0,
            entity_id="incomplete",
            destination_location_id="hall",
        )

    issues = validate_worlds(database_path)
    assert any(
        issue.code == "missing_character_state" and issue.entity_id == "incomplete"
        for issue in issues
    )


def test_move_entity_history_failure_rolls_back_placement(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    _add_location(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_move_event BEFORE INSERT ON events
            BEGIN
                SELECT RAISE(ABORT, 'move event rejected');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="move event rejected"):
        move_entity(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="move-player-1",
            expected_revision=0,
            entity_id="player",
            destination_location_id="hall",
        )

    with connect_database(database_path) as connection:
        assert connection.execute("SELECT revision FROM worlds").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
        assert connection.execute(
            "SELECT location_id FROM entity_locations WHERE entity_id = 'player'"
        ).fetchone()[0] == "ward"


def test_treat_and_discharge_persists_complete_transition(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    result = treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="operation-1",
        expected_revision=0,
        patient_id="patient-1",
        bed_id="bed-1",
        actor_entity_id="player",
    )

    assert result.world_revision == 1
    assert result.already_applied is False

    # A new connection represents application recreation against the same file.
    with connect_database(database_path) as connection:
        world_revision = connection.execute(
            "SELECT revision FROM worlds WHERE id = ?", (WARD_WORLD_ID,)
        ).fetchone()[0]
        patient = connection.execute(
            "SELECT condition, disposition FROM characters WHERE entity_id = 'patient-1'"
        ).fetchone()
        placement = connection.execute(
            "SELECT location_id FROM entity_locations WHERE entity_id = 'patient-1'"
        ).fetchone()
        bed_occupant = connection.execute(
            "SELECT occupant_entity_id FROM beds WHERE entity_id = 'bed-1'"
        ).fetchone()[0]
        occupied_beds = connection.execute(
            "SELECT COUNT(*) FROM beds WHERE occupant_entity_id IS NOT NULL"
        ).fetchone()[0]
        event = connection.execute(
            "SELECT operation_id, event_type, world_revision FROM events"
        ).fetchone()
        operation = connection.execute(
            "SELECT request_json, result_json, completed_revision FROM operations"
        ).fetchone()

    assert world_revision == 1
    assert tuple(patient) == ("recovered", "discharged")
    assert placement is None
    assert bed_occupant is None
    assert occupied_beds == 5
    assert tuple(event) == ("operation-1", "patient_treated_and_discharged", 1)
    assert json.loads(operation["request_json"]) == {
        "actor_entity_id": "player",
        "bed_id": "bed-1",
        "expected_revision": 0,
        "patient_id": "patient-1",
    }
    assert json.loads(operation["result_json"]) == {"world_revision": 1}
    assert operation["completed_revision"] == 1
    assert validate_worlds(database_path) == []


def test_duplicate_operation_is_an_idempotent_retry(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    arguments = {
        "world_id": WARD_WORLD_ID,
        "operation_id": "operation-1",
        "expected_revision": 0,
        "patient_id": "patient-1",
        "bed_id": "bed-1",
        "actor_entity_id": "player",
    }

    first = treat_and_discharge_patient(database_path, **arguments)
    second = treat_and_discharge_patient(database_path, **arguments)

    assert first.already_applied is False
    assert second.already_applied is True
    assert second.world_revision == 1
    with connect_database(database_path) as connection:
        assert connection.execute("SELECT revision FROM worlds").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_reusing_operation_id_for_different_request_is_rejected(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="operation-1",
        expected_revision=0,
        patient_id="patient-1",
        bed_id="bed-1",
    )

    with pytest.raises(MutationConflict, match="operation ID"):
        treat_and_discharge_patient(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="operation-1",
            expected_revision=999,
            patient_id="patient-1",
            bed_id="bed-1",
        )


def test_stale_revision_and_wrong_occupant_do_not_mutate(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    with pytest.raises(StaleWorldRevision):
        treat_and_discharge_patient(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="stale-operation",
            expected_revision=5,
            patient_id="patient-1",
            bed_id="bed-1",
        )
    with pytest.raises(MutationConflict, match="does not occupy"):
        treat_and_discharge_patient(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="wrong-bed-operation",
            expected_revision=0,
            patient_id="patient-2",
            bed_id="bed-1",
        )
    with pytest.raises(MutationNotFound, match="missing-patient"):
        treat_and_discharge_patient(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="missing-patient-operation",
            expected_revision=0,
            patient_id="missing-patient",
            bed_id="bed-1",
        )

    with connect_database(database_path) as connection:
        assert connection.execute("SELECT revision FROM worlds").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM beds WHERE occupant_entity_id IS NOT NULL"
        ).fetchone()[0] == 6


def test_event_failure_rolls_back_all_state_changes(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    with connect_database(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_events BEFORE INSERT ON events
            BEGIN
                SELECT RAISE(ABORT, 'event rejected for rollback test');
            END
            """
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="event rejected"):
        treat_and_discharge_patient(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="operation-1",
            expected_revision=0,
            patient_id="patient-1",
            bed_id="bed-1",
        )

    with connect_database(database_path) as connection:
        assert connection.execute("SELECT revision FROM worlds").fetchone()[0] == 0
        assert connection.execute(
            "SELECT condition FROM characters WHERE entity_id = 'patient-1'"
        ).fetchone()[0] == "untreated"
        assert connection.execute(
            "SELECT occupant_entity_id FROM beds WHERE entity_id = 'bed-1'"
        ).fetchone()[0] == "patient-1"
        assert connection.execute(
            "SELECT location_id FROM entity_locations WHERE entity_id = 'patient-1'"
        ).fetchone()[0] == "ward"


def test_validation_requires_one_operation_and_event_per_world_revision(
    tmp_path: Path,
) -> None:
    database_path = _seeded_database(tmp_path)
    treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="operation-1",
        expected_revision=0,
        patient_id="patient-1",
        bed_id="bed-1",
    )
    with connect_database(database_path) as connection:
        connection.execute("DELETE FROM events")
        connection.commit()

    codes = {issue.code for issue in validate_worlds(database_path)}

    assert "world_history_revision_mismatch" in codes


def test_validation_requires_event_to_match_operation_and_actor_world(
    tmp_path: Path,
) -> None:
    database_path = _seeded_database(tmp_path)
    treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="operation-1",
        expected_revision=0,
        patient_id="patient-1",
        bed_id="bed-1",
        actor_entity_id="player",
    )
    with connect_database(database_path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('other-world', 'Other')")
        connection.execute(
            "INSERT INTO entities(id, world_id, kind, name) "
            "VALUES ('other-actor', 'other-world', 'character', 'Other Actor')"
        )
        connection.execute(
            "UPDATE events SET event_type = 'changed', actor_entity_id = 'other-actor'"
        )
        connection.commit()

    codes = {issue.code for issue in validate_worlds(database_path)}

    assert "event_operation_mismatch" in codes
    assert "event_actor_world_mismatch" in codes
