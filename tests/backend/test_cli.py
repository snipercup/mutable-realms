from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.cli import main
from backend.persistence.database import connect_database


def test_migrate_seed_and_validate_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "world.sqlite3"
    db_args = ["--db-path", str(database_path)]

    assert main([*db_args, "migrate"]) == 0
    assert main([*db_args, "seed"]) == 0
    assert main([*db_args, "seed"]) == 0
    assert main([*db_args, "validate"]) == 0

    captured = capsys.readouterr()
    assert "Applied migrations: 0001" in captured.out
    assert "Seeded deterministic ward world" in captured.out
    assert "Ward world already exists; no changes applied" in captured.out
    assert "World validation passed" in captured.out
    assert captured.err == ""


def test_migrate_uses_database_path_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "from-environment.sqlite3"
    monkeypatch.setenv("MUTABLE_REALMS_DB_PATH", str(database_path))

    assert main(["migrate"]) == 0
    assert database_path.exists()


def test_command_fails_clearly_without_database_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("MUTABLE_REALMS_DB_PATH", raising=False)

    assert main(["migrate"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "MUTABLE_REALMS_DB_PATH" in captured.err


def test_validate_returns_failure_for_invalid_world(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "world.sqlite3"
    db_args = ["--db-path", str(database_path)]
    assert main([*db_args, "migrate"]) == 0
    assert main([*db_args, "seed"]) == 0

    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM entity_locations WHERE entity_id = 'patient-1'")

    capsys.readouterr()
    assert main([*db_args, "validate"]) == 1
    captured = capsys.readouterr()
    assert "occupant_not_at_bed_location" in captured.err


def test_move_entity_command_returns_authoritative_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "world.sqlite3"
    db_args = ["--db-path", str(database_path)]
    assert main([*db_args, "migrate"]) == 0
    assert main([*db_args, "seed"]) == 0
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO locations(id, world_id, name) "
            "VALUES ('hall', 'ward-world', 'Hall')"
        )
        connection.commit()
    capsys.readouterr()

    exit_code = main(
        [
            *db_args,
            "move-entity",
            "--world-id",
            "ward-world",
            "--operation-id",
            "move-player-1",
            "--expected-revision",
            "0",
            "--entity-id",
            "player",
            "--destination-location-id",
            "hall",
            "--actor-entity-id",
            "player",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "already_applied": False,
        "entity_id": "player",
        "location_id": "hall",
        "world_revision": 1,
    }


def test_move_entity_command_reports_stale_revision_without_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "world.sqlite3"
    db_args = ["--db-path", str(database_path)]
    assert main([*db_args, "migrate"]) == 0
    assert main([*db_args, "seed"]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            *db_args,
            "move-entity",
            "--world-id",
            "ward-world",
            "--operation-id",
            "stale-move",
            "--expected-revision",
            "1",
            "--entity-id",
            "player",
            "--destination-location-id",
            "missing-location",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "expected world revision 1, found 0" in captured.err
    with connect_database(database_path) as connection:
        assert connection.execute(
            "SELECT revision FROM worlds WHERE id = 'ward-world'"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
