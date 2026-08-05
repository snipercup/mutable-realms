from __future__ import annotations

import json
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database
from backend.world.mutations import event_id

_RESOURCE_EVENT_TYPE = "resource_transferred"
_MAX_RESOURCE_TYPE_LENGTH = 100


class ResourceError(RuntimeError):
    """Base error for resource operations."""


class ResourceNotFound(ResourceError):
    """A resource operation resource does not exist."""


class ResourceConflict(ResourceError):
    """A resource operation violates its preconditions."""


def transfer_resource(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    actor_entity_id: str,
    recipient_entity_id: str,
    resource_type: str,
    quantity: int,
    source_entity_id: str | None = None,
) -> dict[str, Any]:
    """Atomically grant or transfer resource units between characters.

    With ``source_entity_id`` omitted the units are granted from the world
    (for example a quest reward). With a source, the units move between two
    characters and the source balance must cover the amount.
    """
    if not operation_id.strip():
        raise ResourceConflict("operation ID must not be blank")
    if not resource_type.strip():
        raise ResourceConflict("resource type must not be blank")
    if len(resource_type) > _MAX_RESOURCE_TYPE_LENGTH:
        raise ResourceConflict(
            f"resource type must be at most {_MAX_RESOURCE_TYPE_LENGTH} characters"
        )
    if quantity <= 0:
        raise ResourceConflict("quantity must be a positive integer")
    request = {
        "actor_entity_id": actor_entity_id,
        "expected_revision": expected_revision,
        "quantity": quantity,
        "recipient_entity_id": recipient_entity_id,
        "resource_type": resource_type,
        "source_entity_id": source_entity_id,
    }
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_type, request_json, result_json FROM operations "
                "WHERE world_id = ? AND operation_id = ?",
                (world_id, operation_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["operation_type"] != _RESOURCE_EVENT_TYPE
                    or existing["request_json"] != request_json
                ):
                    raise ResourceConflict("operation ID was already used for a different request")
                connection.rollback()
                result = json.loads(existing["result_json"])
                result["already_applied"] = True
                return result

            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise ResourceNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise ResourceConflict(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )

            entity_ids = [actor_entity_id, recipient_entity_id]
            if source_entity_id is not None:
                entity_ids.append(source_entity_id)
            placeholders = ",".join("?" for _ in entity_ids)
            entities = connection.execute(
                f"""
                SELECT e.id, e.world_id, e.kind, c.role
                FROM entities e LEFT JOIN characters c ON c.entity_id = e.id
                WHERE e.world_id = ? AND e.id IN ({placeholders})
                """,
                [world_id, *entity_ids],
            ).fetchall()
            by_id = {row["id"]: row for row in entities}
            for label, entity_id in (
                ("actor", actor_entity_id),
                ("recipient", recipient_entity_id),
            ):
                row = by_id.get(entity_id)
                if row is None or row["kind"] != "character" or row["role"] is None:
                    raise ResourceNotFound(f"{label} character not found: {entity_id}")
            if source_entity_id is not None:
                row = by_id.get(source_entity_id)
                if row is None or row["kind"] != "character" or row["role"] is None:
                    raise ResourceNotFound(f"source character not found: {source_entity_id}")
                if source_entity_id == recipient_entity_id:
                    raise ResourceConflict("resource transfer cannot target itself")

            def balance(entity_id: str) -> int:
                row = connection.execute(
                    "SELECT quantity FROM resources "
                    "WHERE world_id = ? AND owner_entity_id = ? AND resource_type = ?",
                    (world_id, entity_id, resource_type),
                ).fetchone()
                return row["quantity"] if row is not None else 0

            recipient_balance = balance(recipient_entity_id)
            source_balance = 0
            if source_entity_id is not None:
                source_balance = balance(source_entity_id)
                if source_balance < quantity:
                    raise ResourceConflict(
                        f"source does not have enough {resource_type}: "
                        f"{source_balance} < {quantity}"
                    )

            next_revision = expected_revision + 1
            operation_result = {"world_revision": next_revision}
            result_json = json.dumps(operation_result, sort_keys=True, separators=(",", ":"))
            event_identifier = event_id(world_id, operation_id)
            connection.execute(
                "UPDATE worlds SET revision = ? WHERE id = ? AND revision = ?",
                (next_revision, world_id, expected_revision),
            )
            connection.execute(
                "INSERT INTO operations("
                "world_id, operation_id, operation_type, request_json, result_json, "
                "completed_revision) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    world_id,
                    operation_id,
                    _RESOURCE_EVENT_TYPE,
                    request_json,
                    result_json,
                    next_revision,
                ),
            )
            payload = {
                "quantity": quantity,
                "recipient_entity_id": recipient_entity_id,
                "resource_type": resource_type,
                "source_entity_id": source_entity_id,
            }
            summary = (
                f"{quantity} {resource_type} transferred from {source_entity_id} "
                f"to {recipient_entity_id}"
                if source_entity_id is not None
                else f"{quantity} {resource_type} granted to {recipient_entity_id}"
            )
            connection.execute(
                """INSERT INTO events(
                    id, world_id, operation_id, event_type, actor_entity_id,
                    summary, payload_json, world_revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_identifier,
                    world_id,
                    operation_id,
                    _RESOURCE_EVENT_TYPE,
                    actor_entity_id,
                    summary,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    next_revision,
                ),
            )
            connection.execute(
                """INSERT INTO resources(
                    world_id, owner_entity_id, resource_type, quantity, updated_event_id
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(world_id, owner_entity_id, resource_type) DO UPDATE SET
                    quantity = excluded.quantity,
                    updated_event_id = excluded.updated_event_id""",
                (
                    world_id,
                    recipient_entity_id,
                    resource_type,
                    recipient_balance + quantity,
                    event_identifier,
                ),
            )
            if source_entity_id is not None:
                connection.execute(
                    """INSERT INTO resources(
                        world_id, owner_entity_id, resource_type, quantity, updated_event_id
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(world_id, owner_entity_id, resource_type) DO UPDATE SET
                        quantity = excluded.quantity,
                        updated_event_id = excluded.updated_event_id""",
                    (
                        world_id,
                        source_entity_id,
                        resource_type,
                        source_balance - quantity,
                        event_identifier,
                    ),
                )
            connection.commit()
            return {"already_applied": False, "world_revision": next_revision}
        except Exception:
            connection.rollback()
            raise


def read_resources(
    database_path: str | Path,
    *,
    world_id: str,
    owner_entity_ids: list[str],
    _connection: sqlite3.Connection | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Read only resource rows owned by the given working-set entities."""
    ids = sorted(set(owner_entity_ids))
    if not ids:
        return {"resources": []}
    placeholders = ",".join("?" for _ in ids)
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with connection_context as connection:
        resources = [
            dict(row)
            for row in connection.execute(
                f"""SELECT owner_entity_id, resource_type, quantity
            FROM resources WHERE world_id = ? AND owner_entity_id IN ({placeholders})
            ORDER BY owner_entity_id, resource_type""",
                [world_id, *ids],
            )
        ]
    return {"resources": resources}
