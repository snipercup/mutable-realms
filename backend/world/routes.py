from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database
from backend.world.mutations import event_id
from backend.world.regions import resolve_region_chain

_ROUTE_SET_EVENT = "world_route_set"
_ROUTE_TRAVEL_EVENT = "entity_route_traveled"


class RouteError(RuntimeError):
    """Base route error."""


class RouteNotFound(RouteError):
    """A route, world, entity, or endpoint was not found."""


class RouteConflict(RouteError):
    """A route precondition was rejected."""


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _operation_result(
    connection: sqlite3.Connection,
    world_id: str,
    operation_id: str,
    operation_type: str,
    request_json: str,
) -> dict[str, Any] | None:
    existing = connection.execute(
        "SELECT operation_type, request_json, result_json FROM operations "
        "WHERE world_id = ? AND operation_id = ?",
        (world_id, operation_id),
    ).fetchone()
    if existing is None:
        return None
    if existing["operation_type"] != operation_type or existing["request_json"] != request_json:
        raise RouteConflict("operation ID was already used for a different request")
    result = json.loads(existing["result_json"])
    result["already_applied"] = True
    return result


def _require_revision(connection: sqlite3.Connection, world_id: str, expected_revision: int) -> int:
    world = connection.execute("SELECT revision FROM worlds WHERE id = ?", (world_id,)).fetchone()
    if world is None:
        raise RouteNotFound(f"world not found: {world_id}")
    if world["revision"] != expected_revision:
        raise RouteConflict(
            f"expected world revision {expected_revision}, found {world['revision']}"
        )
    return expected_revision + 1


def _validate_route_against_framework(
    database_path: str | Path,
    connection: sqlite3.Connection,
    world_id: str,
    origin_location_id: str,
    destination_location_id: str,
) -> None:
    """Reject routes whose endpoints violate the world's region framework.

    When the world has no region framework rows the check is skipped (the
    framework is optional). When it does, both endpoints must resolve to a
    bound region chain, and the chains must either share a region (same
    kingdom/province/city) or be declared adjacent via
    ``connected_by_road_to`` in either direction.
    """
    has_regions = connection.execute(
        "SELECT 1 FROM world_regions WHERE world_id = ? LIMIT 1", (world_id,)
    ).fetchone()
    if has_regions is None:
        return
    origin_chain = resolve_region_chain(
        database_path,
        world_id=world_id,
        location_id=origin_location_id,
        _connection=connection,
    )
    destination_chain = resolve_region_chain(
        database_path,
        world_id=world_id,
        location_id=destination_location_id,
        _connection=connection,
    )
    if not origin_chain or not destination_chain:
        raise RouteConflict(
            "route endpoints must be inside a region framework node; "
            "materialize and bind the locations to regions first"
        )
    origin_ids = {region["region_id"] for region in origin_chain}
    destination_ids = {region["region_id"] for region in destination_chain}
    if origin_ids & destination_ids:
        return
    for origin in origin_chain:
        declared = origin["attributes"].get("connected_by_road_to", {})
        if destination_ids & set(declared):
            return
    for destination in destination_chain:
        declared = destination["attributes"].get("connected_by_road_to", {})
        if origin_ids & set(declared):
            return
    raise RouteConflict(
        "route endpoints belong to regions that are not declared adjacent "
        "in the world's region framework"
    )


def create_route(
    database_path: str | Path,
    *,
    world_id: str,
    route_id: str,
    operation_id: str,
    expected_revision: int,
    origin_location_id: str,
    destination_location_id: str,
    name: str,
    description: str | None = None,
    route_kind: str = "route",
    is_active: bool = True,
) -> dict[str, Any]:
    """Create or replace one explicit directed route definition."""
    if not operation_id.strip() or not route_id.strip():
        raise RouteConflict("operation and route IDs must not be blank")
    if not name.strip() or not route_kind.strip():
        raise RouteConflict("route name and kind must not be blank")
    if origin_location_id == destination_location_id:
        raise RouteConflict("route endpoints must be different")
    request = {
        "description": description,
        "destination_location_id": destination_location_id,
        "expected_revision": expected_revision,
        "is_active": is_active,
        "name": name,
        "origin_location_id": origin_location_id,
        "route_id": route_id,
        "route_kind": route_kind,
    }
    request_json = _json(request)
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _operation_result(
                connection, world_id, operation_id, _ROUTE_SET_EVENT, request_json
            )
            if replay is not None:
                connection.rollback()
                return replay
            next_revision = _require_revision(connection, world_id, expected_revision)
            for location_id in (origin_location_id, destination_location_id):
                if (
                    connection.execute(
                        "SELECT 1 FROM locations WHERE world_id = ? AND id = ?",
                        (world_id, location_id),
                    ).fetchone()
                    is None
                ):
                    raise RouteNotFound(f"location not found: {location_id}")
            _validate_route_against_framework(
                database_path,
                connection,
                world_id,
                origin_location_id,
                destination_location_id,
            )
            connection.execute(
                """INSERT INTO world_routes(
                    world_id, route_id, origin_location_id, destination_location_id,
                    name, description, route_kind, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(world_id, route_id) DO UPDATE SET
                    origin_location_id = excluded.origin_location_id,
                    destination_location_id = excluded.destination_location_id,
                    name = excluded.name,
                    description = excluded.description,
                    route_kind = excluded.route_kind,
                    is_active = excluded.is_active""",
                (
                    world_id,
                    route_id,
                    origin_location_id,
                    destination_location_id,
                    name,
                    description,
                    route_kind,
                    int(is_active),
                ),
            )
            result = {
                "already_applied": False,
                "route_id": route_id,
                "world_id": world_id,
                "world_revision": next_revision,
            }
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
                    _ROUTE_SET_EVENT,
                    request_json,
                    _json(result),
                    next_revision,
                ),
            )
            connection.execute(
                "INSERT INTO events("
                "id, world_id, operation_id, event_type, actor_entity_id, summary, "
                "payload_json, world_revision) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
                (
                    event_id(world_id, operation_id),
                    world_id,
                    operation_id,
                    _ROUTE_SET_EVENT,
                    f"Configured route {route_id}",
                    request_json,
                    next_revision,
                ),
            )
            connection.commit()
            return result
        except (RouteConflict, RouteNotFound):
            connection.rollback()
            raise
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise RouteConflict(str(error)) from error


def travel_entity_route(
    database_path: str | Path,
    *,
    world_id: str,
    route_id: str,
    operation_id: str,
    expected_revision: int,
    entity_id: str,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Move a character along one active route from its exact origin."""
    if not operation_id.strip() or not route_id.strip():
        raise RouteConflict("operation and route IDs must not be blank")
    request = {
        "actor_entity_id": actor_entity_id,
        "entity_id": entity_id,
        "expected_revision": expected_revision,
        "route_id": route_id,
    }
    request_json = _json(request)
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _operation_result(
                connection, world_id, operation_id, _ROUTE_TRAVEL_EVENT, request_json
            )
            if replay is not None:
                connection.rollback()
                return replay
            next_revision = _require_revision(connection, world_id, expected_revision)
            route = connection.execute(
                "SELECT origin_location_id, destination_location_id, name, is_active "
                "FROM world_routes WHERE world_id = ? AND route_id = ?",
                (world_id, route_id),
            ).fetchone()
            if route is None:
                raise RouteNotFound(f"route not found: {route_id}")
            if not route["is_active"]:
                raise RouteConflict(f"route is inactive: {route_id}")
            entity = connection.execute(
                "SELECT e.kind, c.entity_id AS character_id, c.disposition, el.location_id "
                "FROM entities e LEFT JOIN characters c ON c.entity_id = e.id "
                "LEFT JOIN entity_locations el ON el.entity_id = e.id "
                "WHERE e.world_id = ? AND e.id = ?",
                (world_id, entity_id),
            ).fetchone()
            if entity is None:
                raise RouteNotFound(f"entity not found: {entity_id}")
            if entity["kind"] != "character" or entity["character_id"] is None:
                raise RouteConflict(f"entity is not a movable character: {entity_id}")
            if entity["disposition"] == "discharged":
                raise RouteConflict(f"discharged character is not movable: {entity_id}")
            if entity["location_id"] != route["origin_location_id"]:
                raise RouteConflict(
                    "entity is not at route origin: "
                    f"expected {route['origin_location_id']}, "
                    f"found {entity['location_id']}"
                )
            if (
                actor_entity_id is not None
                and connection.execute(
                    "SELECT 1 FROM entities WHERE world_id = ? AND id = ?",
                    (world_id, actor_entity_id),
                ).fetchone()
                is None
            ):
                raise RouteNotFound(f"actor not found: {actor_entity_id}")
            occupied = connection.execute(
                "SELECT 1 FROM beds WHERE occupant_entity_id = ?", (entity_id,)
            ).fetchone()
            if occupied is not None:
                raise RouteConflict(f"entity occupies bed and cannot move: {entity_id}")
            connection.execute(
                "UPDATE entity_locations SET location_id = ? WHERE entity_id = ?",
                (route["destination_location_id"], entity_id),
            )
            result = {
                "already_applied": False,
                "entity_id": entity_id,
                "location_id": route["destination_location_id"],
                "route_id": route_id,
                "world_id": world_id,
                "world_revision": next_revision,
            }
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
                    _ROUTE_TRAVEL_EVENT,
                    request_json,
                    _json(result),
                    next_revision,
                ),
            )
            payload = _json(
                {
                    "entity_id": entity_id,
                    "route_id": route_id,
                    "source_location_id": route["origin_location_id"],
                    "destination_location_id": route["destination_location_id"],
                }
            )
            connection.execute(
                "INSERT INTO events("
                "id, world_id, operation_id, event_type, actor_entity_id, summary, "
                "payload_json, world_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id(world_id, operation_id),
                    world_id,
                    operation_id,
                    _ROUTE_TRAVEL_EVENT,
                    actor_entity_id,
                    f"{entity_id} traveled via {route_id}",
                    payload,
                    next_revision,
                ),
            )
            connection.commit()
            return result
        except (RouteConflict, RouteNotFound):
            connection.rollback()
            raise
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise RouteConflict(str(error)) from error
