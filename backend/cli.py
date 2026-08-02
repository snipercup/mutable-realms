from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from backend.persistence.migrations import MigrationError, migrate_database
from backend.scenarios.ward.seed import seed_ward_world
from backend.world.context import build_world_context
from backend.world.mutations import MutationError, move_entity
from backend.world.queries import WorldQueryError
from backend.world.validation import validate_worlds

_COMMANDS = ("migrate", "seed", "validate", "move-entity", "world-context")


def _database_path(value: str | None) -> Path:
    configured = value or os.environ.get("MUTABLE_REALMS_DB_PATH")
    if not configured:
        raise ValueError(
            "database path is required; set MUTABLE_REALMS_DB_PATH or pass --db-path"
        )
    return Path(configured)


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
                raise ValueError(
                    "move-entity requires " + ", ".join(missing)
                )
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
        WorldQueryError,
        sqlite3.Error,
        OSError,
        ValueError,
    ) as error:
        print(f"mutable-realms: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
