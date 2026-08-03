from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database
from backend.world.mutations import event_id

_SOCIAL_EVENT_TYPE = "social_interaction_recorded"
_MAX_MEMORY_LENGTH = 500


class SocialError(RuntimeError):
    """Base error for social-state operations."""


class SocialNotFound(SocialError):
    """A social operation resource does not exist."""


class SocialConflict(SocialError):
    """A social operation violates its preconditions."""


def memory_id(world_id: str, operation_id: str) -> str:
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, f"mutable-realms:memory:{world_id}:{operation_id}")
    return f"memory-{identifier}"


def record_social_interaction(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    actor_entity_id: str,
    subject_entity_id: str,
    object_entity_id: str,
    relationship_category: str,
    relationship_delta: int,
    memory: str,
) -> dict[str, Any]:
    """Atomically update one relationship and store one concise event-linked memory."""
    if not operation_id.strip():
        raise SocialConflict("operation ID must not be blank")
    if not relationship_category.strip():
        raise SocialConflict("category must not be blank")
    if not memory.strip():
        raise SocialConflict("memory must not be blank")
    if len(memory) > _MAX_MEMORY_LENGTH:
        raise SocialConflict("memory must be at most 500 characters")
    if not -100 <= relationship_delta <= 100:
        raise SocialConflict("relationship delta must be between -100 and 100")
    request = {
        "actor_entity_id": actor_entity_id,
        "expected_revision": expected_revision,
        "memory": memory,
        "object_entity_id": object_entity_id,
        "relationship_category": relationship_category,
        "relationship_delta": relationship_delta,
        "subject_entity_id": subject_entity_id,
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
                    existing["operation_type"] != _SOCIAL_EVENT_TYPE
                    or existing["request_json"] != request_json
                ):
                    raise SocialConflict("operation ID was already used for a different request")
                connection.rollback()
                result = json.loads(existing["result_json"])
                result["already_applied"] = True
                return result

            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise SocialNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise SocialConflict(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )

            entities = connection.execute(
                """
                SELECT e.id, e.world_id, e.kind, c.role
                FROM entities e LEFT JOIN characters c ON c.entity_id = e.id
                WHERE e.world_id = ? AND e.id IN (?, ?, ?)
                """,
                (world_id, actor_entity_id, subject_entity_id, object_entity_id),
            ).fetchall()
            by_id = {row["id"]: row for row in entities}
            for label, entity_id in (
                ("actor", actor_entity_id),
                ("subject", subject_entity_id),
                ("object", object_entity_id),
            ):
                row = by_id.get(entity_id)
                if row is None or row["kind"] != "character" or row["role"] is None:
                    raise SocialNotFound(f"{label} character not found: {entity_id}")
            if subject_entity_id == object_entity_id:
                raise SocialConflict("relationship cannot target itself")

            prior = connection.execute(
                """SELECT score FROM relationships
                WHERE world_id = ? AND subject_entity_id = ? AND object_entity_id = ?""",
                (world_id, subject_entity_id, object_entity_id),
            ).fetchone()
            current_score = prior["score"] if prior is not None else 0
            next_score = current_score + relationship_delta
            if not -100 <= next_score <= 100:
                raise SocialConflict("relationship score must remain between -100 and 100")

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
                    _SOCIAL_EVENT_TYPE,
                    request_json,
                    result_json,
                    next_revision,
                ),
            )
            payload = {
                "memory_id": memory_id(world_id, operation_id),
                "object_entity_id": object_entity_id,
                "relationship_category": relationship_category,
                "relationship_delta": relationship_delta,
                "relationship_score": next_score,
                "subject_entity_id": subject_entity_id,
            }
            connection.execute(
                """INSERT INTO events(
                    id, world_id, operation_id, event_type, actor_entity_id,
                    summary, payload_json, world_revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_identifier,
                    world_id,
                    operation_id,
                    _SOCIAL_EVENT_TYPE,
                    actor_entity_id,
                    f"{subject_entity_id} relationship with {object_entity_id} "
                    f"became {relationship_category}",
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    next_revision,
                ),
            )
            connection.execute(
                """INSERT INTO relationships(
                    world_id, subject_entity_id, object_entity_id, category, score,
                    updated_event_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(world_id, subject_entity_id, object_entity_id) DO UPDATE SET
                    category = excluded.category,
                    score = excluded.score,
                    updated_event_id = excluded.updated_event_id""",
                (
                    world_id,
                    subject_entity_id,
                    object_entity_id,
                    relationship_category,
                    next_score,
                    event_identifier,
                ),
            )
            connection.execute(
                "INSERT INTO memories(id, world_id, entity_id, event_id, content) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    memory_id(world_id, operation_id),
                    world_id,
                    subject_entity_id,
                    event_identifier,
                    memory.strip(),
                ),
            )
            connection.commit()
            return {"already_applied": False, "world_revision": next_revision}
        except Exception:
            connection.rollback()
            raise


def read_social_context(
    database_path: str | Path,
    *,
    world_id: str,
    viewer_entity_id: str,
    related_entity_ids: list[str],
    _connection: sqlite3.Connection | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Read only relationships and memories relevant to the current working set."""
    ids = sorted(set(related_entity_ids) | {viewer_entity_id})
    if not ids:
        return {"relationships": [], "memories": []}
    placeholders = ",".join("?" for _ in ids)
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with connection_context as connection:
        relationships = [
            dict(row)
            for row in connection.execute(
                f"""SELECT subject_entity_id, object_entity_id, category, score
            FROM relationships WHERE world_id = ?
              AND subject_entity_id IN ({placeholders})
              AND object_entity_id IN ({placeholders})
            ORDER BY subject_entity_id, object_entity_id""",
                [world_id, *ids, *ids],
            )
        ]
        memories = [
            dict(row)
            for row in connection.execute(
                f"""SELECT id, entity_id, event_id, content,
                       (SELECT world_revision FROM events
                        WHERE id = memories.event_id) AS world_revision
            FROM memories WHERE world_id = ? AND entity_id IN ({placeholders})
            ORDER BY world_revision DESC, id LIMIT 50""",
                [world_id, *ids],
            )
        ]
    return {"relationships": relationships, "memories": memories}
