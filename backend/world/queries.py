from __future__ import annotations

import json
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_readonly_database

WorldRecord = dict[str, Any]


class WorldQueryError(LookupError):
    """Base error for a missing read-model resource."""


class WorldNotFound(WorldQueryError):
    """Raised when a requested world does not exist."""


class PlayerNotFound(WorldQueryError):
    """Raised when a world has no current player."""


class LocationNotFound(WorldQueryError):
    """Raised when a requested location is unavailable in the world."""


class EntityNotFound(WorldQueryError):
    """Raised when a requested entity is unavailable in the world."""


def list_worlds(database_path: str | Path) -> list[WorldRecord]:
    """Return available worlds in stable name/ID order."""
    with connect_readonly_database(database_path) as connection:
        rows = connection.execute(
            "SELECT id, name, revision, description, source_scenario_id "
            "FROM worlds ORDER BY name, id"
        ).fetchall()
    return [dict(row) for row in rows]


def read_world(database_path: str | Path, world_id: str) -> dict[str, Any]:
    """Return one world with its owned story elements."""
    with connect_readonly_database(database_path) as connection:
        world = connection.execute(
            "SELECT id, name, revision, description, source_scenario_id "
            "FROM worlds WHERE id = ?",
            (world_id,),
        ).fetchone()
        if world is None:
            raise WorldNotFound(f"World '{world_id}' does not exist")
        elements = connection.execute(
            "SELECT we.element_type, we.content, ev.occurred_at AS updated_at "
            "FROM world_elements we "
            "JOIN events ev ON ev.id = we.updated_event_id "
            "WHERE we.world_id = ? ORDER BY we.element_type",
            (world_id,),
        ).fetchall()
    return {**dict(world), "elements": [dict(row) for row in elements]}


def get_player(
    database_path: str | Path,
    world_id: str,
    *,
    _connection: sqlite3.Connection | None = None,
) -> WorldRecord:
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with connection_context as connection:
        row = connection.execute(
            """
            SELECT e.id, e.world_id, e.kind, e.name,
                   c.role, c.condition, c.disposition,
                   el.location_id
            FROM entities e
            JOIN characters c ON c.entity_id = e.id
            LEFT JOIN entity_locations el ON el.entity_id = e.id
            WHERE e.world_id = ? AND c.role = 'player'
            ORDER BY e.id
            LIMIT 1
            """,
            (world_id,),
        ).fetchone()
    if row is None:
        raise PlayerNotFound(f"World {world_id!r} has no player")
    return dict(row)


def get_current_location(database_path: str | Path, world_id: str) -> WorldRecord:
    with closing(connect_readonly_database(database_path)) as connection:
        connection.execute("BEGIN")
        player = get_player(database_path, world_id, _connection=connection)
        location_id = player["location_id"]
        if location_id is None:
            raise LocationNotFound(f"Player in world {world_id!r} has no current location")
        return get_location(database_path, world_id, location_id, _connection=connection)


def get_location(
    database_path: str | Path,
    world_id: str,
    location_id: str,
    *,
    _connection: sqlite3.Connection | None = None,
) -> WorldRecord:
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with connection_context as connection:
        if _connection is None:
            connection.execute("BEGIN")
        location = connection.execute(
            """
            SELECT l.id, l.world_id, l.name, l.description, w.revision
            FROM locations l
            JOIN worlds w ON w.id = l.world_id
            WHERE l.world_id = ? AND l.id = ?
            """,
            (world_id, location_id),
        ).fetchone()
        if location is None:
            raise LocationNotFound(f"Location {location_id!r} was not found in world {world_id!r}")

        entities = [
            dict(row)
            for row in connection.execute(
                """
                SELECT e.id, e.kind, e.name,
                       c.role, c.condition, c.disposition
                FROM entity_locations el
                JOIN entities e ON e.id = el.entity_id
                LEFT JOIN characters c ON c.entity_id = e.id
                WHERE el.location_id = ? AND e.world_id = ?
                ORDER BY e.id
                """,
                (location_id, world_id),
            )
        ]
    result = dict(location)
    result["entities"] = entities
    return result


def get_entity(
    database_path: str | Path,
    world_id: str,
    entity_id: str,
    *,
    _connection: sqlite3.Connection | None = None,
) -> WorldRecord:
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with connection_context as connection:
        row = connection.execute(
            """
            SELECT e.id, e.world_id, e.kind, e.name,
                   el.location_id,
                   c.role, c.condition, c.disposition
            FROM entities e
            LEFT JOIN entity_locations el ON el.entity_id = e.id
            LEFT JOIN characters c ON c.entity_id = e.id
            WHERE e.world_id = ? AND e.id = ?
            """,
            (world_id, entity_id),
        ).fetchone()
    if row is None:
        raise EntityNotFound(f"Entity {entity_id!r} was not found in world {world_id!r}")
    return dict(row)


def list_recent_events(
    database_path: str | Path,
    world_id: str,
    *,
    limit: int = 20,
    _connection: sqlite3.Connection | None = None,
) -> list[WorldRecord]:
    if not 1 <= limit <= 100:
        raise ValueError("recent event limit must be between 1 and 100")
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with connection_context as connection:
        world = connection.execute("SELECT 1 FROM worlds WHERE id = ?", (world_id,)).fetchone()
        if world is None:
            raise WorldNotFound(f"World {world_id!r} was not found")
        rows = connection.execute(
            """
            SELECT id, world_id, operation_id, event_type, actor_entity_id,
                   summary, payload_json, world_revision, occurred_at
            FROM events
            WHERE world_id = ?
            ORDER BY world_revision DESC
            LIMIT ?
            """,
            (world_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "world_id": row["world_id"],
            "operation_id": row["operation_id"],
            "event_type": row["event_type"],
            "actor_entity_id": row["actor_entity_id"],
            "summary": row["summary"],
            "payload": json.loads(row["payload_json"]),
            "world_revision": row["world_revision"],
            "occurred_at": row["occurred_at"],
        }
        for row in rows
    ]


def get_world_map(database_path: str | Path, *, world_id: str) -> dict[str, Any]:
    """Return the derived map read model for one world on one snapshot."""
    with connect_readonly_database(database_path) as connection:
        world = connection.execute(
            "SELECT id, name, revision, description, source_scenario_id "
            "FROM worlds WHERE id = ?",
            (world_id,),
        ).fetchone()
        if world is None:
            raise WorldNotFound(f"World {world_id!r} was not found")
        location_rows = connection.execute(
            "SELECT id, name, description FROM locations WHERE world_id = ? ORDER BY name, id",
            (world_id,),
        ).fetchall()
        link_rows = connection.execute(
            "SELECT location_a, location_b FROM location_links "
            "WHERE world_id = ? ORDER BY location_a, location_b",
            (world_id,),
        ).fetchall()
        count_rows = connection.execute(
            """
            SELECT el.location_id, e.kind, COUNT(*) AS count
            FROM entity_locations el
            JOIN entities e ON e.id = el.entity_id
            WHERE e.world_id = ? AND el.location_id IS NOT NULL
            GROUP BY el.location_id, e.kind
            ORDER BY el.location_id, e.kind
            """,
            (world_id,),
        ).fetchall()
        player = connection.execute(
            """
            SELECT c.entity_id, el.location_id
            FROM characters c
            JOIN entities e ON e.id = c.entity_id
            LEFT JOIN entity_locations el ON el.entity_id = c.entity_id
            WHERE e.world_id = ? AND c.role = 'player'
            ORDER BY c.entity_id
            LIMIT 1
            """,
            (world_id,),
        ).fetchone()

    linked_by_location: dict[str, list[str]] = {}
    for row in link_rows:
        first, second = row["location_a"], row["location_b"]
        linked_by_location.setdefault(first, []).append(second)
        linked_by_location.setdefault(second, []).append(first)

    counts_by_location: dict[str, dict[str, int]] = {}
    for row in count_rows:
        counts_by_location.setdefault(row["location_id"], {})[row["kind"]] = row["count"]

    return {
        "world": dict(world),
        "player_location_id": player["location_id"] if player is not None else None,
        "locations": [
            {
                "id": location["id"],
                "name": location["name"],
                "description": location["description"],
                "entity_kinds": counts_by_location.get(location["id"], {}),
                "linked_location_ids": sorted(linked_by_location.get(location["id"], [])),
            }
            for location in location_rows
        ],
    }
