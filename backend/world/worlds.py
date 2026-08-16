"""World administration services.

``create_world_from_scenario`` instances a fresh world from a reusable
scenario: the scenario's title, description, and story elements are copied
into the new world, which records its source scenario for traceability. Copy
semantics are the contract — the scenario is never modified, and the world
owns its copies so the two diverge independently afterward.

``update_world``, ``set_world_element``, and ``remove_world`` manage a world
after creation. They are revision-checked, idempotent, and (like every world
mutation) record an operation and an event; ``remove_world`` is destructive
by design — the world's history is removed with it (the same accepted
trade-off as removing a scenario).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database
from backend.world.mutations import event_id
from backend.world.scenarios import SCENARIO_ELEMENT_TYPES, ScenarioNotFound

_WORLD_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_WORLD_CREATED_EVENT = "world_created"
_WORLD_UPDATED_EVENT = "world_updated"
_WORLD_ELEMENT_UPDATED_EVENT = "world_element_updated"
_PLAYER_PROVISIONED_EVENT = "player_provisioned"
_MAX_ELEMENT_LENGTH = 20_000


class WorldAdminError(RuntimeError):
    """Base error for world administration operations."""


class WorldAdminConflict(WorldAdminError):
    """A world administration operation violates its preconditions."""


class WorldAdminNotFound(WorldAdminError):
    """A world administration operation references a missing world."""


def _validate_world_id(world_id: str) -> None:
    if not _WORLD_ID_PATTERN.fullmatch(world_id):
        raise WorldAdminConflict("world id must be lowercase kebab-case (letters, digits, hyphens)")


def _validate_operation_id(operation_id: str) -> None:
    if not operation_id.strip():
        raise WorldAdminConflict("operation ID must not be blank")


def _validate_element_type(element_type: str) -> None:
    if element_type not in SCENARIO_ELEMENT_TYPES:
        raise WorldAdminConflict(
            "element type must be one of: " + ", ".join(SCENARIO_ELEMENT_TYPES)
        )


def _validate_content(content: str) -> str:
    trimmed = content.strip()
    if not trimmed:
        raise WorldAdminConflict("element content must not be blank")
    if len(trimmed) > _MAX_ELEMENT_LENGTH:
        raise WorldAdminConflict(
            f"element content must be at most {_MAX_ELEMENT_LENGTH} characters"
        )
    return trimmed


def _normalize_description(description: str | None) -> str | None:
    if description is None:
        return None
    return description.strip() or None


def _replay_or_conflict(
    connection: sqlite3.Connection,
    *,
    world_id: str,
    operation_id: str,
    operation_type: str,
    request_json: str,
) -> dict[str, Any] | None:
    """Return the stored result for an exact-request replay, else None.

    Raises ``WorldAdminConflict`` when the operation ID was already used for a
    different request.
    """
    existing = connection.execute(
        "SELECT operation_type, request_json, result_json FROM operations "
        "WHERE world_id = ? AND operation_id = ?",
        (world_id, operation_id),
    ).fetchone()
    if existing is None:
        return None
    if existing["operation_type"] != operation_type or existing["request_json"] != request_json:
        raise WorldAdminConflict("operation ID was already used for a different request")
    result = json.loads(existing["result_json"])
    result["already_applied"] = True
    return result


def _require_world(connection: sqlite3.Connection, world_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT id, name, revision FROM worlds WHERE id = ?", (world_id,)
    ).fetchone()
    if row is None:
        raise WorldAdminNotFound(f"world not found: {world_id}")
    return dict(row)


def _check_revision(world: dict[str, Any], expected_revision: int) -> None:
    if world["revision"] != expected_revision:
        raise WorldAdminConflict(
            f"expected world revision {expected_revision}, found {world['revision']}"
        )


def _commit_world_mutation(
    connection: sqlite3.Connection,
    *,
    world_id: str,
    operation_id: str,
    operation_type: str,
    request_json: str,
    event_identifier: str,
    summary: str,
    payload: dict[str, Any],
    expected_revision: int,
) -> dict[str, Any]:
    """Record the operation + event, bump the revision, and return the result."""
    next_revision = expected_revision + 1
    result = {"already_applied": False, "world_id": world_id, "world_revision": next_revision}
    result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
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
            operation_type,
            request_json,
            result_json,
            next_revision,
        ),
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
            operation_type,
            None,
            summary,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            next_revision,
        ),
    )
    return result


def create_world_from_scenario(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    scenario_id: str,
) -> dict[str, Any]:
    """Instance a new world from a scenario atomically.

    Copies the scenario's title, description, and story elements into the new
    world (revision 0 → 1 with a ``world_created`` event) and records the
    source scenario. The scenario itself is never modified. Replaying the
    same caller operation ID returns the stored result without a second world.
    """
    _validate_world_id(world_id)
    _validate_operation_id(operation_id)
    if not scenario_id.strip():
        raise WorldAdminConflict("scenario id must not be blank")
    request = {"scenario_id": scenario_id}
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
                    existing["operation_type"] != _WORLD_CREATED_EVENT
                    or existing["request_json"] != request_json
                ):
                    raise WorldAdminConflict(
                        "operation ID was already used for a different request"
                    )
                connection.rollback()
                result = json.loads(existing["result_json"])
                result["already_applied"] = True
                return result

            duplicate = connection.execute(
                "SELECT id FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if duplicate is not None:
                raise WorldAdminConflict(f"world already exists: {world_id}")

            scenario = connection.execute(
                "SELECT id, title, description FROM scenarios WHERE id = ?",
                (scenario_id,),
            ).fetchone()
            if scenario is None:
                raise ScenarioNotFound(f"scenario not found: {scenario_id}")
            elements = connection.execute(
                "SELECT element_type, content FROM scenario_elements "
                "WHERE scenario_id = ? ORDER BY element_type",
                (scenario_id,),
            ).fetchall()

            connection.execute(
                "INSERT INTO worlds (id, name, description, source_scenario_id, revision) "
                "VALUES (?, ?, ?, ?, 0)",
                (world_id, scenario["title"], scenario["description"], scenario_id),
            )
            connection.execute("UPDATE worlds SET revision = 1 WHERE id = ?", (world_id,))
            result = {
                "already_applied": False,
                "world_id": world_id,
                "world_revision": 1,
                "source_scenario_id": scenario_id,
                "copied_elements": [element["element_type"] for element in elements],
            }
            result_json = json.dumps(result, sort_keys=True, separators=(",", ":"))
            connection.execute(
                "INSERT INTO operations("
                "world_id, operation_id, operation_type, request_json, result_json, "
                "completed_revision) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    world_id,
                    operation_id,
                    _WORLD_CREATED_EVENT,
                    request_json,
                    result_json,
                    1,
                ),
            )
            event_identifier = event_id(world_id, operation_id)
            payload = {
                "scenario_id": scenario_id,
                "source_scenario_id": scenario_id,
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
                    _WORLD_CREATED_EVENT,
                    None,
                    f"world instanced from scenario {scenario_id}",
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    1,
                ),
            )
            for element in elements:
                connection.execute(
                    "INSERT INTO world_elements "
                    "(world_id, element_type, content, updated_event_id) "
                    "VALUES (?, ?, ?, ?)",
                    (world_id, element["element_type"], element["content"], event_identifier),
                )
            connection.commit()
            return result
        except (WorldAdminError, ScenarioNotFound):
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def update_world(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    title: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Update a world's title and/or description atomically."""
    _validate_world_id(world_id)
    _validate_operation_id(operation_id)
    if title is None and description is None:
        raise WorldAdminConflict("update requires title or description")
    trimmed_title = title.strip() if title is not None else None
    if title is not None and not trimmed_title:
        raise WorldAdminConflict("title must not be blank")
    normalized_description = _normalize_description(description)
    request = {"description": normalized_description, "title": trimmed_title}
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type=_WORLD_UPDATED_EVENT,
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            world = _require_world(connection, world_id)
            _check_revision(world, expected_revision)
            if trimmed_title is not None:
                connection.execute(
                    "UPDATE worlds SET name = ? WHERE id = ?",
                    (trimmed_title, world_id),
                )
            if normalized_description is not None:
                connection.execute(
                    "UPDATE worlds SET description = ? WHERE id = ?",
                    (normalized_description, world_id),
                )
            payload = {"description": normalized_description, "title": trimmed_title}
            result = _commit_world_mutation(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type=_WORLD_UPDATED_EVENT,
                request_json=request_json,
                event_identifier=event_id(world_id, operation_id),
                summary=f"world {world_id} updated",
                payload=payload,
                expected_revision=expected_revision,
            )
            connection.commit()
            return result
        except WorldAdminError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def set_world_element(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    element_type: str,
    content: str,
) -> dict[str, Any]:
    """Upsert one world-owned story element atomically."""
    _validate_world_id(world_id)
    _validate_operation_id(operation_id)
    _validate_element_type(element_type)
    trimmed_content = _validate_content(content)
    request = {"content": trimmed_content, "element_type": element_type}
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type=_WORLD_ELEMENT_UPDATED_EVENT,
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            world = _require_world(connection, world_id)
            _check_revision(world, expected_revision)
            event_identifier = event_id(world_id, operation_id)
            result = _commit_world_mutation(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type=_WORLD_ELEMENT_UPDATED_EVENT,
                request_json=request_json,
                event_identifier=event_identifier,
                summary=f"world element {element_type} updated in {world_id}",
                payload={"element_type": element_type},
                expected_revision=expected_revision,
            )
            connection.execute(
                "INSERT INTO world_elements "
                "(world_id, element_type, content, updated_event_id) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(world_id, element_type) DO UPDATE SET "
                "content = excluded.content, "
                "updated_event_id = excluded.updated_event_id",
                (world_id, element_type, trimmed_content, event_identifier),
            )
            connection.commit()
            result["element_type"] = element_type
            return result
        except WorldAdminError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def remove_world(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Remove a world and all of its state atomically (destructive).

    Every child table cascades, so the world's history is removed with it —
    there is no post-removal trace (the same accepted trade-off as removing a
    scenario). Scenarios that instanced the world are untouched.
    """
    _validate_world_id(world_id)
    _validate_operation_id(operation_id)

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            world = _require_world(connection, world_id)
            _check_revision(world, expected_revision)
            connection.execute("DELETE FROM worlds WHERE id = ?", (world_id,))
            connection.commit()
            return {
                "already_applied": False,
                "world_id": world_id,
                "world_revision": expected_revision,
                "removed": True,
            }
        except WorldAdminError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def world_provision_player(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    player_name: str,
    location_name: str,
) -> dict[str, Any]:
    """Provision a world for play: create a player and a starting location.

    A world instanced from a scenario has no entities or locations, so it is
    not playable until provisioned. This operation creates a starting location
    (``{world_id}-start``) and a player character (``{world_id}-player`` with
    role ``player``) placed there, atomically with a ``player_provisioned``
    event. The player name is per-world: the same name (for example ``fate``)
    can be used in any number of worlds, each with its own entity.
    """
    _validate_world_id(world_id)
    _validate_operation_id(operation_id)
    trimmed_player = player_name.strip()
    trimmed_location = location_name.strip()
    if not trimmed_player:
        raise WorldAdminConflict("player name must not be blank")
    if not trimmed_location:
        raise WorldAdminConflict("location name must not be blank")
    request = {"location_name": trimmed_location, "player_name": trimmed_player}
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type=_PLAYER_PROVISIONED_EVENT,
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            world = _require_world(connection, world_id)
            _check_revision(world, expected_revision)
            existing = connection.execute(
                "SELECT e.id FROM entities e "
                "JOIN characters c ON c.entity_id = e.id "
                "WHERE e.world_id = ? AND c.role = 'player' LIMIT 1",
                (world_id,),
            ).fetchone()
            if existing is not None:
                raise WorldAdminConflict(f"world already has a player: {existing['id']}")
            player_entity_id = f"{world_id}-player"
            location_id = f"{world_id}-start"
            connection.execute(
                "INSERT INTO locations (id, world_id, name, description) VALUES (?, ?, ?, '')",
                (location_id, world_id, trimmed_location),
            )
            connection.execute(
                "INSERT INTO entities (id, world_id, kind, name) VALUES (?, ?, 'character', ?)",
                (player_entity_id, world_id, trimmed_player),
            )
            connection.execute(
                "INSERT INTO characters (entity_id, role, condition, disposition) "
                "VALUES (?, 'player', NULL, 'active')",
                (player_entity_id,),
            )
            connection.execute(
                "INSERT INTO entity_locations (entity_id, location_id) VALUES (?, ?)",
                (player_entity_id, location_id),
            )
            result = _commit_world_mutation(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type=_PLAYER_PROVISIONED_EVENT,
                request_json=request_json,
                event_identifier=event_id(world_id, operation_id),
                summary=f"player {trimmed_player} provisioned at {trimmed_location}",
                payload={"location_id": location_id, "player_id": player_entity_id},
                expected_revision=expected_revision,
            )
            connection.commit()
            result["location_id"] = location_id
            result["player_id"] = player_entity_id
            return result
        except WorldAdminError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def instance_player_character(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    character_id: str,
    location_name: str,
    location_description: str | None = None,
) -> dict[str, Any]:
    """Copy a reusable character definition into a world as its sole player."""
    _validate_world_id(world_id)
    _validate_operation_id(operation_id)
    if not character_id.strip():
        raise WorldAdminConflict("character id must not be blank")
    trimmed_location = location_name.strip()
    trimmed_description = location_description.strip() if location_description else None
    if not trimmed_location:
        raise WorldAdminConflict("location name must not be blank")
    request_json = json.dumps(
        {
            "character_id": character_id,
            "location_name": trimmed_location,
            "location_description": trimmed_description,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type="player_character_instanced",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            world = _require_world(connection, world_id)
            _check_revision(world, expected_revision)
            definition = connection.execute(
                "SELECT id, name, basic_info FROM player_character_definitions WHERE id = ?",
                (character_id,),
            ).fetchone()
            if definition is None:
                raise WorldAdminConflict(f"player character not found: {character_id}")
            existing_player = connection.execute(
                "SELECT e.id FROM entities e JOIN characters c ON c.entity_id = e.id "
                "WHERE e.world_id = ? AND c.role = 'player' LIMIT 1",
                (world_id,),
            ).fetchone()
            if existing_player is not None:
                raise WorldAdminConflict(f"world already has a player: {world_id}")
            location_id = f"{world_id}-start"
            entity_id = f"{world_id}-player"
            if (
                connection.execute(
                    "SELECT 1 FROM locations WHERE id = ?", (location_id,)
                ).fetchone()
                is not None
            ):
                raise WorldAdminConflict(f"starting location already exists: {location_id}")
            if (
                connection.execute("SELECT 1 FROM entities WHERE id = ?", (entity_id,)).fetchone()
                is not None
            ):
                raise WorldAdminConflict(f"player entity already exists: {entity_id}")
            connection.execute(
                "INSERT INTO locations(id, world_id, name, description) VALUES (?, ?, ?, ?)",
                (
                    location_id,
                    world_id,
                    trimmed_location,
                    trimmed_description or f"Starting location for {definition['name']}",
                ),
            )
            connection.execute(
                "INSERT INTO entities(id, world_id, kind, name) VALUES (?, ?, 'character', ?)",
                (entity_id, world_id, definition["name"]),
            )
            connection.execute(
                "INSERT INTO characters(entity_id, role, condition, disposition) "
                "VALUES (?, 'player', ?, 'active')",
                (entity_id, definition["basic_info"]),
            )
            connection.execute(
                "INSERT INTO entity_locations(entity_id, location_id) VALUES (?, ?)",
                (entity_id, location_id),
            )
            connection.execute(
                "INSERT INTO player_character_instances("
                "world_id, character_definition_id, entity_id, name, basic_info) "
                "VALUES (?, ?, ?, ?, ?)",
                (world_id, character_id, entity_id, definition["name"], definition["basic_info"]),
            )
            result = _commit_world_mutation(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type="player_character_instanced",
                request_json=request_json,
                event_identifier=event_id(world_id, operation_id),
                summary=f"player character {character_id} instanced in {world_id}",
                payload={
                    "character_id": character_id,
                    "entity_id": entity_id,
                    "location_id": location_id,
                },
                expected_revision=expected_revision,
            )
            connection.commit()
            result.update(
                {"character_id": character_id, "entity_id": entity_id, "location_id": location_id}
            )
            return result
        except WorldAdminError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise
