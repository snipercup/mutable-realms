from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database
from backend.world.mutations import event_id

_EXPANSION_EVENT = "location_expanded"
_DEFAULT_MAX_LOCATIONS = 100
_MAX_ID_LENGTH = 100
_MAX_NAME_LENGTH = 200
_MAX_DESCRIPTION_LENGTH = 2000


class ExpansionError(RuntimeError):
    """Base error for controlled location expansion."""


class ExpansionNotFound(ExpansionError):
    """A referenced expansion resource does not exist."""


class ExpansionConflict(ExpansionError):
    """An expansion proposal violates an authoritative invariant."""


def _clean(value: str, label: str, maximum: int = _MAX_ID_LENGTH) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ExpansionConflict(f"{label} must not be blank")
    if len(cleaned) > maximum:
        raise ExpansionConflict(f"{label} must be at most {maximum} characters")
    return cleaned


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _existing_operation(
    connection: sqlite3.Connection, world_id: str, operation_id: str, request_json: str
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT operation_type, request_json, result_json FROM operations "
        "WHERE world_id = ? AND operation_id = ?",
        (world_id, operation_id),
    ).fetchone()
    if row is None:
        return None
    if row["operation_type"] != _EXPANSION_EVENT or row["request_json"] != request_json:
        raise ExpansionConflict("operation ID was already used for a different request")
    result = json.loads(row["result_json"])
    result["already_applied"] = True
    return result


def propose_location_expansion(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    proposal_id: str,
    location_id: str,
    anchor_location_id: str,
    name: str,
    description: str = "",
    parent_location_id: str | None = None,
    connect_to_anchor: bool = False,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Atomically accept one bounded narrator expansion proposal."""
    world_id = _clean(world_id, "world ID")
    operation_id = _clean(operation_id, "operation ID")
    proposal_id = _clean(proposal_id, "proposal ID")
    location_id = _clean(location_id, "location ID")
    anchor_location_id = _clean(anchor_location_id, "anchor location ID")
    name = _clean(name, "location name", _MAX_NAME_LENGTH)
    description = description.strip()
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        raise ExpansionConflict(
            f"location description must be at most {_MAX_DESCRIPTION_LENGTH} characters"
        )
    if parent_location_id is not None:
        parent_location_id = _clean(parent_location_id, "parent location ID")
    request = {
        "actor_entity_id": actor_entity_id,
        "anchor_location_id": anchor_location_id,
        "connect_to_anchor": connect_to_anchor,
        "description": description,
        "expected_revision": expected_revision,
        "location_id": location_id,
        "name": name,
        "parent_location_id": parent_location_id,
        "proposal_id": proposal_id,
    }
    request_json = _json(request)

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _existing_operation(connection, world_id, operation_id, request_json)
            if replay is not None:
                connection.rollback()
                return replay

            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise ExpansionNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise ExpansionConflict(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )
            existing_proposal = connection.execute(
                "SELECT 1 FROM world_expansion_proposals WHERE world_id = ? AND proposal_id = ?",
                (world_id, proposal_id),
            ).fetchone()
            if existing_proposal is not None:
                raise ExpansionConflict("proposal ID was already used for a different request")
            anchor = connection.execute(
                "SELECT 1 FROM locations WHERE world_id = ? AND id = ?",
                (world_id, anchor_location_id),
            ).fetchone()
            if anchor is None:
                raise ExpansionNotFound(f"anchor location not found: {anchor_location_id}")
            if (
                actor_entity_id is not None
                and connection.execute(
                    "SELECT 1 FROM entities WHERE world_id = ? AND id = ?",
                    (world_id, actor_entity_id),
                ).fetchone()
                is None
            ):
                raise ExpansionNotFound(f"actor not found: {actor_entity_id}")
            if connection.execute(
                "SELECT 1 FROM locations WHERE world_id = ? AND id = ?",
                (world_id, location_id),
            ).fetchone():
                raise ExpansionConflict(f"location ID already exists: {location_id}")
            if connection.execute(
                "SELECT 1 FROM locations WHERE world_id = ? AND lower(trim(name)) = lower(trim(?))",
                (world_id, name),
            ).fetchone():
                raise ExpansionConflict(f"location name already exists: {name}")
            if (
                parent_location_id is not None
                and connection.execute(
                    "SELECT 1 FROM locations WHERE world_id = ? AND id = ?",
                    (world_id, parent_location_id),
                ).fetchone()
                is None
            ):
                raise ExpansionNotFound(f"parent location not found: {parent_location_id}")
            limit_row = connection.execute(
                "SELECT max_locations FROM world_expansion_limits WHERE world_id = ?",
                (world_id,),
            ).fetchone()
            maximum = limit_row["max_locations"] if limit_row else _DEFAULT_MAX_LOCATIONS
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM world_expansion_proposals WHERE world_id = ?",
                (world_id,),
            ).fetchone()["count"]
            if count >= maximum:
                raise ExpansionConflict("location expansion budget is exhausted")

            next_revision = expected_revision + 1
            result = {
                "already_applied": False,
                "location_id": location_id,
                "proposal_id": proposal_id,
                "world_id": world_id,
                "world_revision": next_revision,
            }
            event_identifier = event_id(world_id, operation_id)
            connection.execute(
                "INSERT INTO operations("
                "world_id, operation_id, operation_type, request_json, result_json, "
                "completed_revision) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    world_id,
                    operation_id,
                    _EXPANSION_EVENT,
                    request_json,
                    _json({k: v for k, v in result.items() if k != "already_applied"}),
                    next_revision,
                ),
            )
            connection.execute(
                "INSERT INTO locations(id, world_id, name, description) VALUES (?, ?, ?, ?)",
                (location_id, world_id, name, description),
            )
            connection.execute(
                "INSERT INTO world_expansion_proposals("
                "world_id, proposal_id, operation_id, location_id, anchor_location_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (world_id, proposal_id, operation_id, location_id, anchor_location_id),
            )
            if parent_location_id is not None:
                connection.execute(
                    "INSERT INTO location_containment("
                    "world_id, child_location_id, parent_location_id) "
                    "VALUES (?, ?, ?)",
                    (world_id, location_id, parent_location_id),
                )
            if connect_to_anchor:
                location_a, location_b = sorted((anchor_location_id, location_id))
                connection.execute(
                    "INSERT INTO location_links(world_id, location_a, location_b) VALUES (?, ?, ?)",
                    (world_id, location_a, location_b),
                )
            connection.execute(
                "UPDATE worlds SET revision = ? WHERE id = ? AND revision = ?",
                (next_revision, world_id, expected_revision),
            )
            connection.execute(
                "INSERT INTO events("
                "id, world_id, operation_id, event_type, actor_entity_id, summary, "
                "payload_json, world_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_identifier,
                    world_id,
                    operation_id,
                    _EXPANSION_EVENT,
                    actor_entity_id,
                    f"Expanded location {name}",
                    _json(
                        {
                            "anchor_location_id": anchor_location_id,
                            "connect_to_anchor": connect_to_anchor,
                            "location_id": location_id,
                            "parent_location_id": parent_location_id,
                            "proposal_id": proposal_id,
                        }
                    ),
                    next_revision,
                ),
            )
            connection.commit()
            return result
        except ExpansionError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise ExpansionConflict("expansion proposal violated a database invariant") from error
