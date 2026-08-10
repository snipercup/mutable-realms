"""World administration services.

``create_world_from_scenario`` instances a fresh world from a reusable
scenario: the scenario's title, description, and story elements are copied
into the new world, which records its source scenario for traceability. Copy
semantics are the contract — the scenario is never modified, and the world
owns its copies so the two diverge independently afterward.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database
from backend.world.mutations import event_id
from backend.world.scenarios import ScenarioNotFound

_WORLD_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_WORLD_CREATED_EVENT = "world_created"


class WorldAdminError(RuntimeError):
    """Base error for world administration operations."""


class WorldAdminConflict(WorldAdminError):
    """A world administration operation violates its preconditions."""


def _validate_world_id(world_id: str) -> None:
    if not _WORLD_ID_PATTERN.fullmatch(world_id):
        raise WorldAdminConflict(
            "world id must be lowercase kebab-case (letters, digits, hyphens)"
        )


def _validate_operation_id(operation_id: str) -> None:
    if not operation_id.strip():
        raise WorldAdminConflict("operation ID must not be blank")


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
            connection.execute(
                "UPDATE worlds SET revision = 1 WHERE id = ?", (world_id,)
            )
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
