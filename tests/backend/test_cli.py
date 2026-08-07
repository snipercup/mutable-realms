from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.cli import main
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from tests.backend.general_world import GENERAL_WORLD_ID, seed_general_world


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
    assert "Seeded deterministic town world" in captured.out
    assert "Town world already exists; no changes applied" in captured.out
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
            "INSERT INTO locations(id, world_id, name) VALUES ('hall', 'ward-world', 'Hall')"
        )
        connection.execute(
            "INSERT INTO location_links(world_id, location_a, location_b) "
            "VALUES ('ward-world', 'hall', 'ward')"
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
        assert (
            connection.execute("SELECT revision FROM worlds WHERE id = 'ward-world'").fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0


def test_world_context_command_returns_deterministic_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)

    arguments = [
        "--db-path",
        str(database_path),
        "world-context",
        "--world-id",
        GENERAL_WORLD_ID,
        "--event-limit",
        "1",
    ]
    exit_code = main(arguments)

    assert exit_code == 0
    first_capture = capsys.readouterr()
    output = first_capture.out
    assert first_capture.err == ""
    payload = json.loads(output)
    assert output == json.dumps(payload, sort_keys=True) + "\n"
    assert payload["world"] == {
        "id": GENERAL_WORLD_ID,
        "name": "Open World",
        "revision": 0,
    }
    assert payload["player"]["id"] == "farmer"
    assert payload["current_location"]["id"] == "ocean-farm"
    assert payload["recent_events"] == []

    assert main(arguments) == 0
    second_capture = capsys.readouterr()
    assert second_capture.out == output
    assert second_capture.err == ""


@pytest.mark.parametrize(
    ("world_id", "event_limit", "message"),
    [
        ("missing-world", "10", "was not found"),
        (GENERAL_WORLD_ID, "0", "event limit must be between 1 and 100"),
    ],
)
def test_world_context_command_reports_controlled_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    world_id: str,
    event_limit: str,
    message: str,
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_general_world(database_path)

    exit_code = main(
        [
            "--db-path",
            str(database_path),
            "world-context",
            "--world-id",
            world_id,
            "--event-limit",
            event_limit,
        ]
    )

    capture = capsys.readouterr()
    assert exit_code == 2
    assert capture.out == ""
    assert capture.err.startswith("mutable-realms: ")
    assert message in capture.err
    assert "Traceback" not in capture.err


def test_world_turn_command_runs_structured_ward_turn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    from backend.scenarios.ward.seed import seed_ward_world

    assert seed_ward_world(database_path)

    exit_code = main(
        [
            "--db-path",
            str(database_path),
            "world-turn",
            "--world-id",
            "ward-world",
            "--player-id",
            "player",
            "--player-action",
            "Treat the patient in the first bed.",
            "--turn-operation-id",
            "cli-turn-1",
            "--decision-json",
            json.dumps(
                {
                    "kind": "perform_one_supported_operation",
                    "operation": {
                        "operation_type": "world_treat_and_discharge_patient",
                        "patient_id": "patient-1",
                        "bed_id": "bed-1",
                    },
                }
            ),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "success"
    assert payload["mutation"] == {"already_applied": False, "world_revision": 1}
    assert payload["after"]["world"]["revision"] == 1
    assert payload["after"]["recent_events"][0]["operation_id"] == "cli-turn-1"


def test_world_turn_command_returns_failure_status_for_rejected_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    from backend.scenarios.ward.seed import seed_ward_world

    assert seed_ward_world(database_path)
    exit_code = main(
        [
            "--db-path",
            str(database_path),
            "world-turn",
            "--world-id",
            "ward-world",
            "--player-id",
            "player",
            "--player-action",
            "Treat the wrong bed.",
            "--decision-json",
            json.dumps(
                {
                    "kind": "perform_one_supported_operation",
                    "operation": {
                        "operation_type": "world_treat_and_discharge_patient",
                        "patient_id": "patient-1",
                        "bed_id": "bed-2",
                    },
                }
            ),
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "mutation_rejected"
