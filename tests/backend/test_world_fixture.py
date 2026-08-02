from __future__ import annotations

from pathlib import Path

from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.validation import validate_worlds


def test_seed_creates_deterministic_ward_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)

    assert seed_ward_world(database_path) is True
    assert seed_ward_world(database_path) is False

    with connect_database(database_path) as connection:
        world = connection.execute(
            "SELECT id, revision FROM worlds WHERE id = ?", (WARD_WORLD_ID,)
        ).fetchone()
        player_count = connection.execute(
            "SELECT COUNT(*) FROM characters WHERE role = 'player'"
        ).fetchone()[0]
        patient_count = connection.execute(
            "SELECT COUNT(*) FROM characters WHERE role = 'patient'"
        ).fetchone()[0]
        bed_rows = connection.execute(
            "SELECT entity_id, occupant_entity_id FROM beds ORDER BY entity_id"
        ).fetchall()

    assert tuple(world) == (WARD_WORLD_ID, 0)
    assert player_count == 1
    assert patient_count == 6
    assert [tuple(row) for row in bed_rows] == [
        (f"bed-{number}", f"patient-{number}") for number in range(1, 7)
    ]
    assert validate_worlds(database_path) == []


def test_validation_reports_cross_world_placement(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)

    with connect_database(database_path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('other-world', 'Other')")
        connection.execute(
            "INSERT INTO locations(id, world_id, name) "
            "VALUES ('other-place', 'other-world', 'Other')"
        )
        connection.execute(
            "UPDATE entity_locations SET location_id = 'other-place' WHERE entity_id = 'patient-1'"
        )
        connection.commit()

    issues = validate_worlds(database_path)

    assert any(issue.code == "placement_world_mismatch" for issue in issues)
    assert any(issue.entity_id == "patient-1" for issue in issues)


def test_validation_reports_incoherent_bed_occupancy(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)

    with connect_database(database_path) as connection:
        connection.execute(
            "DELETE FROM entity_locations WHERE entity_id = 'patient-1'"
        )
        connection.commit()

    issues = validate_worlds(database_path)

    assert any(issue.code == "occupant_not_at_bed_location" for issue in issues)
