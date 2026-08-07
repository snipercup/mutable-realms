from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from backend.persistence.database import connect_database

_MOVE_EVENT_TYPE = "entity_moved"


class MutationError(RuntimeError):
    """Base error for rejected authoritative mutations."""


class MutationNotFound(MutationError):
    """A requested world entity does not exist."""


class MutationConflict(MutationError):
    """Current state does not satisfy the operation's preconditions."""


class StaleWorldRevision(MutationConflict):
    """The caller based its operation on an obsolete world revision."""


@dataclass(frozen=True)
class MutationResult:
    world_revision: int
    already_applied: bool


@dataclass(frozen=True)
class MoveEntityResult(MutationResult):
    entity_id: str
    location_id: str


def event_id(world_id: str, operation_id: str) -> str:
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, f"mutable-realms:{world_id}:{operation_id}")
    return f"event-{identifier}"


def move_entity(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    entity_id: str,
    destination_location_id: str,
    actor_entity_id: str | None = None,
) -> MoveEntityResult:
    """Atomically move one character between locations."""
    if not operation_id.strip():
        raise MutationConflict("operation ID must not be blank")

    request = {
        "actor_entity_id": actor_entity_id,
        "destination_location_id": destination_location_id,
        "entity_id": entity_id,
        "expected_revision": expected_revision,
    }
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT operation_type, request_json, result_json
                FROM operations
                WHERE world_id = ? AND operation_id = ?
                """,
                (world_id, operation_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["operation_type"] != _MOVE_EVENT_TYPE
                    or existing["request_json"] != request_json
                ):
                    raise MutationConflict("operation ID was already used for a different request")
                connection.rollback()
                stored_result = json.loads(existing["result_json"])
                return MoveEntityResult(
                    world_revision=stored_result["world_revision"],
                    already_applied=True,
                    entity_id=stored_result["entity_id"],
                    location_id=stored_result["location_id"],
                )

            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise MutationNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise StaleWorldRevision(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )

            entity = connection.execute(
                """
                SELECT e.kind, c.entity_id AS character_id, c.disposition,
                       el.location_id
                FROM entities e
                LEFT JOIN characters c ON c.entity_id = e.id
                LEFT JOIN entity_locations el ON el.entity_id = e.id
                WHERE e.id = ? AND e.world_id = ?
                """,
                (entity_id, world_id),
            ).fetchone()
            if entity is None:
                raise MutationNotFound(f"entity not found: {entity_id}")
            if entity["kind"] != "character":
                raise MutationConflict(f"entity is not movable: {entity_id}")
            if entity["character_id"] is None:
                raise MutationConflict(f"character is missing character state: {entity_id}")
            if entity["disposition"] == "discharged":
                raise MutationConflict(f"discharged character is not movable: {entity_id}")
            if entity["location_id"] is None:
                raise MutationConflict(f"entity has no current location: {entity_id}")
            if entity["location_id"] == destination_location_id:
                raise MutationConflict(f"entity is already at location: {destination_location_id}")

            destination = connection.execute(
                "SELECT 1 FROM locations WHERE id = ? AND world_id = ?",
                (destination_location_id, world_id),
            ).fetchone()
            if destination is None:
                raise MutationNotFound(f"location not found: {destination_location_id}")

            linked = connection.execute(
                """SELECT 1 FROM location_links
                WHERE world_id = ? AND ? IN (location_a, location_b)
                  AND ? IN (location_a, location_b)""",
                (world_id, entity["location_id"], destination_location_id),
            ).fetchone()
            if linked is None:
                raise MutationConflict(
                    f"destination is not adjacent: {destination_location_id}"
                )

            occupied_bed = connection.execute(
                "SELECT entity_id FROM beds WHERE occupant_entity_id = ?",
                (entity_id,),
            ).fetchone()
            if occupied_bed is not None:
                raise MutationConflict(
                    f"entity occupies bed {occupied_bed['entity_id']} and cannot move"
                )

            if actor_entity_id is not None:
                actor = connection.execute(
                    "SELECT 1 FROM entities WHERE id = ? AND world_id = ?",
                    (actor_entity_id, world_id),
                ).fetchone()
                if actor is None:
                    raise MutationNotFound(f"actor not found: {actor_entity_id}")

            next_revision = expected_revision + 1
            connection.execute(
                "UPDATE entity_locations SET location_id = ? WHERE entity_id = ?",
                (destination_location_id, entity_id),
            )
            revision_update = connection.execute(
                "UPDATE worlds SET revision = ? WHERE id = ? AND revision = ?",
                (next_revision, world_id, expected_revision),
            )
            if revision_update.rowcount != 1:
                raise StaleWorldRevision("world revision changed during mutation")

            result = {
                "entity_id": entity_id,
                "location_id": destination_location_id,
                "world_revision": next_revision,
            }
            result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
            connection.execute(
                """
                INSERT INTO operations(
                    world_id, operation_id, operation_type, request_json,
                    result_json, completed_revision
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    world_id,
                    operation_id,
                    _MOVE_EVENT_TYPE,
                    request_json,
                    result_json,
                    next_revision,
                ),
            )
            payload_json = json.dumps(
                {
                    "destination_location_id": destination_location_id,
                    "entity_id": entity_id,
                    "source_location_id": entity["location_id"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            connection.execute(
                """
                INSERT INTO events(
                    id, world_id, operation_id, event_type, actor_entity_id,
                    summary, payload_json, world_revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id(world_id, operation_id),
                    world_id,
                    operation_id,
                    _MOVE_EVENT_TYPE,
                    actor_entity_id,
                    f"{entity_id} moved from {entity['location_id']} to {destination_location_id}",
                    payload_json,
                    next_revision,
                ),
            )
            connection.commit()
            return MoveEntityResult(
                world_revision=next_revision,
                already_applied=False,
                entity_id=entity_id,
                location_id=destination_location_id,
            )
        except Exception:
            connection.rollback()
            raise
