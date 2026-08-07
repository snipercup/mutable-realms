from __future__ import annotations

import json
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database
from backend.world.mutations import event_id

_LOCATION_EVENT_TYPE = "location_updated"
_MAX_DISPLAY_NAME_LENGTH = 100
_MAX_PROPERTY_LENGTH = 50
_MIN_PROPERTY_VALUE = 0
_MAX_PROPERTY_VALUE = 100


class LocationStateError(RuntimeError):
    """Base error for location-state operations."""


class LocationStateNotFound(LocationStateError):
    """A location-state operation resource does not exist."""


class LocationStateConflict(LocationStateError):
    """A location-state operation violates its preconditions."""


def update_location(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    actor_entity_id: str,
    location_id: str,
    display_name: str | None = None,
    property: str | None = None,
    value: int | None = None,
) -> dict[str, Any]:
    """Atomically rename a location and/or set one property value.

    ``display_name`` changes the mutable display name behind the stable ID
    (identity evolution such as The Slums → Riverside Quarter). ``property``
    with ``value`` sets a bounded 0–100 property such as ``cleanliness``.
    """
    if not operation_id.strip():
        raise LocationStateConflict("operation ID must not be blank")
    if display_name is None and property is None:
        raise LocationStateConflict("display_name or property is required")
    if display_name is not None:
        if not display_name.strip():
            raise LocationStateConflict("display name must not be blank")
        if len(display_name) > _MAX_DISPLAY_NAME_LENGTH:
            raise LocationStateConflict(
                f"display name must be at most {_MAX_DISPLAY_NAME_LENGTH} characters"
            )
    if property is not None:
        if not property.strip():
            raise LocationStateConflict("property must not be blank")
        if len(property) > _MAX_PROPERTY_LENGTH:
            raise LocationStateConflict(
                f"property must be at most {_MAX_PROPERTY_LENGTH} characters"
            )
        if value is None:
            raise LocationStateConflict("value is required when a property is set")
        if not _MIN_PROPERTY_VALUE <= value <= _MAX_PROPERTY_VALUE:
            raise LocationStateConflict(
                f"value must be between {_MIN_PROPERTY_VALUE} and {_MAX_PROPERTY_VALUE}"
            )
    if value is not None and property is None:
        raise LocationStateConflict("property is required when a value is set")
    request = {
        "actor_entity_id": actor_entity_id,
        "display_name": display_name,
        "expected_revision": expected_revision,
        "location_id": location_id,
        "property": property,
        "value": value,
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
                    existing["operation_type"] != _LOCATION_EVENT_TYPE
                    or existing["request_json"] != request_json
                ):
                    raise LocationStateConflict(
                        "operation ID was already used for a different request"
                    )
                connection.rollback()
                result = json.loads(existing["result_json"])
                result["already_applied"] = True
                return result

            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise LocationStateNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise LocationStateConflict(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )

            location = connection.execute(
                "SELECT name FROM locations WHERE id = ? AND world_id = ?",
                (location_id, world_id),
            ).fetchone()
            if location is None:
                raise LocationStateNotFound(f"location not found: {location_id}")

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
                    _LOCATION_EVENT_TYPE,
                    request_json,
                    result_json,
                    next_revision,
                ),
            )
            payload = {
                "display_name": display_name,
                "location_id": location_id,
                "property": property,
                "value": value,
            }
            summary_parts = []
            if display_name is not None:
                summary_parts.append(
                    f"location renamed to {display_name.strip()} from {location['name']}"
                )
            if property is not None:
                summary_parts.append(f"{property} set to {value}")
            connection.execute(
                """INSERT INTO events(
                    id, world_id, operation_id, event_type, actor_entity_id,
                    summary, payload_json, world_revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_identifier,
                    world_id,
                    operation_id,
                    _LOCATION_EVENT_TYPE,
                    actor_entity_id,
                    "; ".join(summary_parts),
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    next_revision,
                ),
            )
            if display_name is not None:
                connection.execute(
                    "UPDATE locations SET name = ? WHERE id = ? AND world_id = ?",
                    (display_name.strip(), location_id, world_id),
                )
            if property is not None:
                connection.execute(
                    """INSERT INTO location_properties(
                        world_id, location_id, property, value, updated_event_id
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(world_id, location_id, property) DO UPDATE SET
                        value = excluded.value,
                        updated_event_id = excluded.updated_event_id""",
                    (world_id, location_id, property, value, event_identifier),
                )
            connection.commit()
            return {"already_applied": False, "world_revision": next_revision}
        except Exception:
            connection.rollback()
            raise


def read_location_properties(
    database_path: str | Path,
    *,
    world_id: str,
    location_ids: list[str],
    _connection: sqlite3.Connection | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Read property rows for the given working-set locations."""
    ids = sorted(set(location_ids))
    if not ids:
        return {"properties": []}
    placeholders = ",".join("?" for _ in ids)
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with connection_context as connection:
        properties = [
            dict(row)
            for row in connection.execute(
                f"""SELECT location_id, property, value
            FROM location_properties WHERE world_id = ? AND location_id IN ({placeholders})
            ORDER BY location_id, property""",
                [world_id, *ids],
            )
        ]
    return {"properties": properties}
