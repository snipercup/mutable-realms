from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from backend.persistence.database import connect_database
from backend.persistence.migrations import (
    MigrationError,
    migrate_database,
    verify_database_schema,
)
from backend.scenarios.town.seed import seed_town_world
from backend.scenarios.ward.seed import seed_ward_world
from backend.world.context import build_world_context
from backend.world.mutations import MutationError, move_entity
from backend.world.queries import WorldQueryError
from backend.world.scenarios import (
    ScenarioError,
    create_scenario,
    remove_scenario,
    set_scenario_element,
    update_scenario,
)
from backend.world.turns import TurnDecision, run_turn
from backend.world.validation import validate_worlds

_COMMANDS = (
    "migrate",
    "seed",
    "validate",
    "backup",
    "move-entity",
    "world-context",
    "world-turn",
    "create-scenario",
    "update-scenario",
    "set-scenario-element",
    "remove-scenario",
)


def _database_path(value: str | None) -> Path:
    configured = value or os.environ.get("MUTABLE_REALMS_DB_PATH")
    if not configured:
        raise ValueError("database path is required; set MUTABLE_REALMS_DB_PATH or pass --db-path")
    return Path(configured)


def _integrity_ok(database_path: Path) -> bool:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return row is not None and row[0] == "ok"


def _backup(database_path: Path, backup_dir: str | None) -> int:
    """Snapshot the authoritative database with the SQLite online backup API.

    The snapshot is consistent even while the single worker is mid-write, so
    WAL/SHM sidecar files need not be copied separately. The artifact is
    verified (integrity, schema history, whole-world validation) before the
    command reports success; a snapshot of an already-corrupt world is kept
    but flagged with a nonzero exit.
    """
    if not database_path.is_file():
        raise ValueError(f"database file does not exist: {database_path}")
    output_dir = Path(backup_dir) if backup_dir else database_path.parent / "backups"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = output_dir / f"{database_path.stem}-{timestamp}.sqlite3"

    source = connect_database(database_path)
    try:
        with sqlite3.connect(backup_path) as target:
            source.backup(target)
    finally:
        source.close()

    if not _integrity_ok(backup_path):
        raise ValueError(f"backup failed integrity check: {backup_path}")
    verify_database_schema(backup_path)

    print(f"Backup written: {backup_path}")
    print(f"SHA-256: {hashlib.sha256(backup_path.read_bytes()).hexdigest()}")
    print("Integrity check: ok")
    print("Schema verification: ok")

    issues = validate_worlds(backup_path)
    if issues:
        for issue in issues:
            entity = f" [{issue.entity_id}]" if issue.entity_id else ""
            print(f"{issue.code}{entity}: {issue.message}", file=sys.stderr)
        print("World validation: FAILED (backup kept; source world needs repair)", file=sys.stderr)
        return 1
    print("World validation: passed")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mutable-realms")
    parser.add_argument("--db-path", help="override MUTABLE_REALMS_DB_PATH")
    parser.add_argument("command", choices=_COMMANDS)
    parser.add_argument("--world-id")
    parser.add_argument("--operation-id")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--entity-id")
    parser.add_argument("--destination-location-id")
    parser.add_argument("--actor-entity-id")
    parser.add_argument("--event-limit", type=int, default=10)
    parser.add_argument("--player-id")
    parser.add_argument("--player-action")
    parser.add_argument("--decision-json")
    parser.add_argument("--turn-operation-id")
    parser.add_argument("--backup-dir", help="override the default backups/ directory")
    parser.add_argument("--scenario-id")
    parser.add_argument("--title")
    parser.add_argument("--description")
    parser.add_argument("--element-type")
    parser.add_argument("--content")
    args = parser.parse_args(argv)

    try:
        database_path = _database_path(args.db_path)
        if args.command == "migrate":
            versions = migrate_database(database_path)
            if versions:
                formatted = ", ".join(f"{version:04d}" for version in versions)
                print(f"Applied migrations: {formatted}")
            else:
                print("Database schema is up to date")
            return 0

        if args.command == "seed":
            if seed_ward_world(database_path):
                print("Seeded deterministic ward world")
            else:
                print("Ward world already exists; no changes applied")
            if seed_town_world(database_path):
                print("Seeded deterministic town world")
            else:
                print("Town world already exists; no changes applied")
            return 0

        if args.command == "move-entity":
            required = {
                "--world-id": args.world_id,
                "--operation-id": args.operation_id,
                "--expected-revision": args.expected_revision,
                "--entity-id": args.entity_id,
                "--destination-location-id": args.destination_location_id,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("move-entity requires " + ", ".join(missing))
            result = move_entity(
                database_path,
                world_id=args.world_id,
                operation_id=args.operation_id,
                expected_revision=args.expected_revision,
                entity_id=args.entity_id,
                destination_location_id=args.destination_location_id,
                actor_entity_id=args.actor_entity_id,
            )
            print(
                json.dumps(
                    {
                        "already_applied": result.already_applied,
                        "entity_id": result.entity_id,
                        "location_id": result.location_id,
                        "world_revision": result.world_revision,
                    },
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "world-context":
            if args.world_id is None:
                raise ValueError("world-context requires --world-id")
            context = build_world_context(
                database_path,
                world_id=args.world_id,
                recent_event_limit=args.event_limit,
            )
            print(json.dumps(context.model_dump(), sort_keys=True))
            return 0

        if args.command == "world-turn":
            required = {
                "--world-id": args.world_id,
                "--player-id": args.player_id,
                "--player-action": args.player_action,
                "--decision-json": args.decision_json,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("world-turn requires " + ", ".join(missing))
            decision_json = args.decision_json
            assert decision_json is not None
            decision = TurnDecision.model_validate(json.loads(decision_json))
            result = run_turn(
                database_path,
                world_id=args.world_id,
                player_id=args.player_id,
                player_action=args.player_action,
                decide=lambda _action, _context: decision,
                operation_id_factory=(
                    (lambda: args.turn_operation_id) if args.turn_operation_id is not None else None
                ),
            )
            payload = {
                "after": result.after.model_dump(mode="json"),
                "attempts": result.attempts,
                "before": result.before.model_dump(mode="json"),
                "decision": result.decision.model_dump(mode="json"),
                "message": result.message,
                "mutation": result.mutation,
                "outcome": result.outcome.value,
            }
            print(json.dumps(payload, sort_keys=True))
            if result.outcome.value in {
                "invalid_action",
                "missing_resource",
                "mutation_rejected",
                "stale_revision",
                "tool_failure",
            }:
                return 1
            return 0

        if args.command == "create-scenario":
            required = {
                "--scenario-id": args.scenario_id,
                "--operation-id": args.operation_id,
                "--title": args.title,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("create-scenario requires " + ", ".join(missing))
            result = create_scenario(
                database_path,
                scenario_id=args.scenario_id,
                operation_id=args.operation_id,
                title=args.title,
                description=args.description,
            )
            print(json.dumps(result, sort_keys=True))
            return 0

        if args.command == "update-scenario":
            required = {
                "--scenario-id": args.scenario_id,
                "--operation-id": args.operation_id,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("update-scenario requires " + ", ".join(missing))
            result = update_scenario(
                database_path,
                scenario_id=args.scenario_id,
                operation_id=args.operation_id,
                title=args.title,
                description=args.description,
            )
            print(json.dumps(result, sort_keys=True))
            return 0

        if args.command == "set-scenario-element":
            required = {
                "--scenario-id": args.scenario_id,
                "--operation-id": args.operation_id,
                "--element-type": args.element_type,
                "--content": args.content,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("set-scenario-element requires " + ", ".join(missing))
            result = set_scenario_element(
                database_path,
                scenario_id=args.scenario_id,
                operation_id=args.operation_id,
                element_type=args.element_type,
                content=args.content,
            )
            print(json.dumps(result, sort_keys=True))
            return 0

        if args.command == "remove-scenario":
            required = {
                "--scenario-id": args.scenario_id,
                "--operation-id": args.operation_id,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError("remove-scenario requires " + ", ".join(missing))
            result = remove_scenario(
                database_path,
                scenario_id=args.scenario_id,
                operation_id=args.operation_id,
            )
            print(json.dumps(result, sort_keys=True))
            return 0

        if args.command == "backup":
            return _backup(database_path, args.backup_dir)

        issues = validate_worlds(database_path)
        if not issues:
            print("World validation passed")
            return 0
        for issue in issues:
            entity = f" [{issue.entity_id}]" if issue.entity_id else ""
            print(f"{issue.code}{entity}: {issue.message}", file=sys.stderr)
        return 1
    except (
        MigrationError,
        MutationError,
        ScenarioError,
        WorldQueryError,
        sqlite3.Error,
        OSError,
        ValueError,
        ValidationError,
        json.JSONDecodeError,
    ) as error:
        print(f"mutable-realms: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
