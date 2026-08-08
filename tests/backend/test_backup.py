from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.cli import main
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.town.seed import TOWN_WORLD_ID, seed_town_world
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.agent_tools import record_world_social_interaction
from backend.world.validation import validate_worlds


def _seeded_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    seed_town_world(database_path)
    return database_path


def _backup_file(database_path: Path) -> Path:
    backups = database_path.parent / "backups"
    artifacts = sorted(backups.glob("*.sqlite3"))
    assert len(artifacts) == 1
    return artifacts[0]


def test_backup_creates_verified_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = _seeded_database(tmp_path)

    assert main(["--db-path", str(database_path), "backup"]) == 0
    captured = capsys.readouterr()
    assert "Backup written" in captured.out
    assert "Integrity check: ok" in captured.out
    assert "Schema verification: ok" in captured.out
    assert "World validation: passed" in captured.out
    assert re.search(r"SHA-256: [0-9a-f]{64}", captured.out) is not None
    assert captured.err == ""

    backup_path = _backup_file(database_path)
    with connect_database(backup_path) as connection:
        worlds = {
            row["id"]: row["revision"]
            for row in connection.execute("SELECT id, revision FROM worlds ORDER BY id")
        }
    assert worlds == {WARD_WORLD_ID: 0, TOWN_WORLD_ID: 0}


def test_backup_preserves_committed_state(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    record_world_social_interaction(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="backup-op-1",
        expected_revision=0,
        actor_entity_id="player",
        subject_entity_id="player",
        object_entity_id="patient-2",
        relationship_category="grateful",
        relationship_delta=10,
        memory="Player promised to look out for Patient 2.",
    )

    assert main(["--db-path", str(database_path), "backup"]) == 0

    backup_path = _backup_file(database_path)
    with connect_database(backup_path) as connection:
        revision = connection.execute(
            "SELECT revision FROM worlds WHERE id = ?", (WARD_WORLD_ID,)
        ).fetchone()["revision"]
        relationship = connection.execute(
            "SELECT category, score FROM relationships "
            "WHERE world_id = ? AND subject_entity_id = ? AND object_entity_id = ?",
            (WARD_WORLD_ID, "player", "patient-2"),
        ).fetchone()
        event_count = connection.execute(
            "SELECT COUNT(*) AS count FROM events WHERE world_id = ?", (WARD_WORLD_ID,)
        ).fetchone()["count"]
    assert revision == 1
    assert (relationship["category"], relationship["score"]) == ("grateful", 10)
    assert event_count >= 1
    assert validate_worlds(backup_path) == []


def test_backup_restore_readback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = _seeded_database(tmp_path)
    backup_dir = tmp_path / "snapshots"

    assert main(["--db-path", str(database_path), "backup", "--backup-dir", str(backup_dir)]) == 0
    capsys.readouterr()

    artifacts = sorted(backup_dir.glob("*.sqlite3"))
    assert len(artifacts) == 1
    restored_path = tmp_path / "restored.sqlite3"
    restored_path.write_bytes(artifacts[0].read_bytes())

    assert main(["--db-path", str(restored_path), "validate"]) == 0
    captured = capsys.readouterr()
    assert "World validation passed" in captured.out
    with connect_database(restored_path) as connection:
        count = connection.execute("SELECT COUNT(*) AS count FROM worlds").fetchone()["count"]
    assert count == 2


def test_backup_flags_corrupt_world_with_nonzero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = _seeded_database(tmp_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "UPDATE entities SET kind = 'item' WHERE id = 'patient-1'"
        )

    assert main(["--db-path", str(database_path), "backup"]) == 1
    captured = capsys.readouterr()
    assert "Backup written" in captured.out
    assert "World validation: FAILED" in captured.err
    assert "character_kind_mismatch" in captured.err
    assert _backup_file(database_path).exists()


def test_backup_fails_clearly_without_database_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.sqlite3"

    assert main(["--db-path", str(missing), "backup"]) == 2
    captured = capsys.readouterr()
    assert "database file does not exist" in captured.err


def test_backup_rejects_non_database_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    not_a_database = tmp_path / "world.sqlite3"
    not_a_database.write_text("this is not a sqlite database")

    assert main(["--db-path", str(not_a_database), "backup"]) == 2
    captured = capsys.readouterr()
    assert "not a database" in captured.err or "database" in captured.err
