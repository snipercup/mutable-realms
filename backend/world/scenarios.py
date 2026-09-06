"""Scenario authoring services.

Scenarios are reusable authoring templates (title, description, story
elements) from which worlds are instanced later. They are administrative
data, not playable world state: no revision counter and no event stream.
Traceability and exact idempotency come from the ``scenario_operations``
ledger keyed by the caller operation ID.

Removal is destructive by design: deleting a scenario cascades its elements
and operation records, so a removed scenario leaves no trace (the same
accepted trade-off as removing a world).
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database

SCENARIO_ELEMENT_TYPES = ("ai_instructions", "author_note", "plot_essentials", "opening_scene")
_MAX_ELEMENT_LENGTH = 20_000
_MAX_REGION_ID_LENGTH = 100
_MAX_REGION_LEVEL_LENGTH = 50
_MAX_REGION_TITLE_LENGTH = 200
_MAX_REGION_DESCRIPTION_LENGTH = 2000
_MAX_REGION_ATTRIBUTES_LENGTH = 10_000
_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class ScenarioError(RuntimeError):
    """Base error for scenario operations."""


class ScenarioNotFound(ScenarioError):
    """A scenario does not exist."""


class ScenarioConflict(ScenarioError):
    """A scenario operation violates its preconditions."""


def _validate_scenario_id(scenario_id: str) -> None:
    if not _ID_PATTERN.fullmatch(scenario_id):
        raise ScenarioConflict(
            "scenario id must be lowercase kebab-case (letters, digits, hyphens)"
        )


def _validate_operation_id(operation_id: str) -> None:
    if not operation_id.strip():
        raise ScenarioConflict("operation ID must not be blank")


def _validate_element_type(element_type: str) -> None:
    if element_type not in SCENARIO_ELEMENT_TYPES:
        raise ScenarioConflict(
            "element type must be one of: " + ", ".join(SCENARIO_ELEMENT_TYPES)
        )


def _validate_content(content: str) -> str:
    trimmed = content.strip()
    if not trimmed:
        raise ScenarioConflict("element content must not be blank")
    if len(trimmed) > _MAX_ELEMENT_LENGTH:
        raise ScenarioConflict(
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
    scenario_id: str,
    operation_id: str,
    operation_type: str,
    request_json: str,
) -> dict[str, Any] | None:
    """Return the stored result for an exact-request replay, else None.

    Raises ``ScenarioConflict`` when the operation ID was already used for a
    different request.
    """
    existing = connection.execute(
        "SELECT operation_type, request_json, result_json FROM scenario_operations "
        "WHERE scenario_id = ? AND operation_id = ?",
        (scenario_id, operation_id),
    ).fetchone()
    if existing is None:
        return None
    if (
        existing["operation_type"] != operation_type
        or existing["request_json"] != request_json
    ):
        raise ScenarioConflict("operation ID was already used for a different request")
    result = json.loads(existing["result_json"])
    result["already_applied"] = True
    return result


def _record_operation(
    connection: sqlite3.Connection,
    *,
    scenario_id: str,
    operation_id: str,
    operation_type: str,
    request_json: str,
    result: dict[str, Any],
) -> None:
    connection.execute(
        "INSERT INTO scenario_operations "
        "(scenario_id, operation_id, operation_type, request_json, result_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            scenario_id,
            operation_id,
            operation_type,
            request_json,
            json.dumps(result, sort_keys=True),
        ),
    )


def _require_scenario(
    connection: sqlite3.Connection, scenario_id: str
) -> None:
    row = connection.execute(
        "SELECT id FROM scenarios WHERE id = ?", (scenario_id,)
    ).fetchone()
    if row is None:
        raise ScenarioNotFound(f"scenario not found: {scenario_id}")


def create_scenario(
    database_path: str | Path,
    *,
    scenario_id: str,
    operation_id: str,
    title: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Create one scenario atomically with exact operation-ID idempotency."""
    _validate_scenario_id(scenario_id)
    _validate_operation_id(operation_id)
    trimmed_title = title.strip()
    if not trimmed_title:
        raise ScenarioConflict("title must not be blank")
    normalized_description = _normalize_description(description)
    request = {"description": normalized_description, "title": trimmed_title}
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="create_scenario",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            existing = connection.execute(
                "SELECT id FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
            if existing is not None:
                raise ScenarioConflict(f"scenario already exists: {scenario_id}")
            connection.execute(
                "INSERT INTO scenarios (id, title, description) VALUES (?, ?, ?)",
                (scenario_id, trimmed_title, normalized_description),
            )
            result = {
                "already_applied": False,
                "scenario_id": scenario_id,
                "title": trimmed_title,
            }
            _record_operation(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="create_scenario",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except ScenarioError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def update_scenario(
    database_path: str | Path,
    *,
    scenario_id: str,
    operation_id: str,
    title: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Update a scenario's title and/or description atomically."""
    _validate_scenario_id(scenario_id)
    _validate_operation_id(operation_id)
    if title is None and description is None:
        raise ScenarioConflict("update requires title or description")
    trimmed_title = title.strip() if title is not None else None
    if title is not None and not trimmed_title:
        raise ScenarioConflict("title must not be blank")
    normalized_description = _normalize_description(description)
    request = {"description": normalized_description, "title": trimmed_title}
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="update_scenario",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            _require_scenario(connection, scenario_id)
            if trimmed_title is not None:
                connection.execute(
                    "UPDATE scenarios SET title = ? WHERE id = ?",
                    (trimmed_title, scenario_id),
                )
            if normalized_description is not None:
                connection.execute(
                    "UPDATE scenarios SET description = ? WHERE id = ?",
                    (normalized_description, scenario_id),
                )
            result = {"already_applied": False, "scenario_id": scenario_id}
            _record_operation(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="update_scenario",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except ScenarioError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def set_scenario_element(
    database_path: str | Path,
    *,
    scenario_id: str,
    operation_id: str,
    element_type: str,
    content: str,
) -> dict[str, Any]:
    """Upsert one story element (author_note, plot_essentials, opening_scene)."""
    _validate_scenario_id(scenario_id)
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
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="set_scenario_element",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            _require_scenario(connection, scenario_id)
            connection.execute(
                "INSERT INTO scenario_elements (scenario_id, element_type, content) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(scenario_id, element_type) "
                "DO UPDATE SET content = excluded.content, "
                "updated_at = CURRENT_TIMESTAMP",
                (scenario_id, element_type, trimmed_content),
            )
            result = {
                "already_applied": False,
                "scenario_id": scenario_id,
                "element_type": element_type,
            }
            _record_operation(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="set_scenario_element",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except ScenarioError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def _validate_region_id(region_id: str) -> str:
    trimmed = region_id.strip()
    if not _ID_PATTERN.fullmatch(trimmed):
        raise ScenarioConflict(
            "region id must be lowercase kebab-case (letters, digits, hyphens)"
        )
    if len(trimmed) > _MAX_REGION_ID_LENGTH:
        raise ScenarioConflict(
            f"region id must be at most {_MAX_REGION_ID_LENGTH} characters"
        )
    return trimmed


def _validate_region_level(level: str) -> str:
    trimmed = level.strip()
    if not trimmed:
        raise ScenarioConflict("region level must not be blank")
    if len(trimmed) > _MAX_REGION_LEVEL_LENGTH:
        raise ScenarioConflict(
            f"region level must be at most {_MAX_REGION_LEVEL_LENGTH} characters"
        )
    return trimmed


def _validate_region_title(title: str) -> str:
    trimmed = title.strip()
    if not trimmed:
        raise ScenarioConflict("region title must not be blank")
    if len(trimmed) > _MAX_REGION_TITLE_LENGTH:
        raise ScenarioConflict(
            f"region title must be at most {_MAX_REGION_TITLE_LENGTH} characters"
        )
    return trimmed


def _validate_region_description(description: str) -> str:
    trimmed = description.strip()
    if not trimmed:
        raise ScenarioConflict("region description must not be blank")
    if len(trimmed) > _MAX_REGION_DESCRIPTION_LENGTH:
        raise ScenarioConflict(
            f"region description must be at most "
            f"{_MAX_REGION_DESCRIPTION_LENGTH} characters"
        )
    return trimmed


def _validate_region_attributes(attributes: dict[str, Any] | None) -> str:
    if attributes is None:
        return "{}"
    serialized = json.dumps(attributes, sort_keys=True, separators=(",", ":"))
    if len(serialized) > _MAX_REGION_ATTRIBUTES_LENGTH:
        raise ScenarioConflict(
            f"region attributes must be at most "
            f"{_MAX_REGION_ATTRIBUTES_LENGTH} characters"
        )
    return serialized


def _require_parent_is_acyclic(
    connection: sqlite3.Connection,
    scenario_id: str,
    region_id: str,
    parent_region_id: str | None,
) -> None:
    """Ensure the proposed parent does not create a cycle in the hierarchy."""
    current = parent_region_id
    depth = 0
    while current is not None:
        if current == region_id:
            raise ScenarioConflict(
                "region parent must not create a cycle in the hierarchy"
            )
        depth += 1
        if depth > 1000:
            raise ScenarioConflict("region hierarchy is too deep")
        row = connection.execute(
            "SELECT parent_region_id FROM scenario_regions "
            "WHERE scenario_id = ? AND region_id = ?",
            (scenario_id, current),
        ).fetchone()
        if row is None:
            raise ScenarioConflict(f"parent region not found: {current}")
        current = row["parent_region_id"]


def set_scenario_region(
    database_path: str | Path,
    *,
    scenario_id: str,
    operation_id: str,
    region_id: str,
    level: str,
    title: str,
    description: str,
    parent_region_id: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upsert one region in a scenario's framework hierarchy.

    A region is knowledge (a kingdom, province, or city-to-be), not a playable
    location. It carries a level name chosen by the scenario author (free-form,
    e.g. ``kingdom`` / ``province`` / ``city`` or ``planet`` / ``school
    grounds``), a title, a lore description, and arbitrary structured
    attributes (biomes, species, declared connections).
    """
    _validate_scenario_id(scenario_id)
    _validate_operation_id(operation_id)
    region_id = _validate_region_id(region_id)
    level = _validate_region_level(level)
    title = _validate_region_title(title)
    description = _validate_region_description(description)
    parent_region_id = (
        _validate_region_id(parent_region_id)
        if parent_region_id is not None
        else None
    )
    attributes_json = _validate_region_attributes(attributes)
    request = {
        "attributes": attributes,
        "description": description,
        "level": level,
        "parent_region_id": parent_region_id,
        "region_id": region_id,
        "title": title,
    }
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="set_scenario_region",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            _require_scenario(connection, scenario_id)
            if parent_region_id is not None:
                parent = connection.execute(
                    "SELECT region_id FROM scenario_regions "
                    "WHERE scenario_id = ? AND region_id = ?",
                    (scenario_id, parent_region_id),
                ).fetchone()
                if parent is None:
                    raise ScenarioConflict(
                        f"parent region not found: {parent_region_id}"
                    )
                _require_parent_is_acyclic(
                    connection, scenario_id, region_id, parent_region_id
                )
            connection.execute(
                "INSERT INTO scenario_regions ("
                "scenario_id, region_id, parent_region_id, level, title, "
                "description, attributes_json) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(scenario_id, region_id) DO UPDATE SET "
                "parent_region_id = excluded.parent_region_id, "
                "level = excluded.level, title = excluded.title, "
                "description = excluded.description, "
                "attributes_json = excluded.attributes_json, "
                "updated_at = CURRENT_TIMESTAMP",
                (
                    scenario_id,
                    region_id,
                    parent_region_id,
                    level,
                    title,
                    description,
                    attributes_json,
                ),
            )
            result = {
                "already_applied": False,
                "scenario_id": scenario_id,
                "region_id": region_id,
            }
            _record_operation(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="set_scenario_region",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except ScenarioError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def remove_scenario_region(
    database_path: str | Path,
    *,
    scenario_id: str,
    operation_id: str,
    region_id: str,
) -> dict[str, Any]:
    """Remove one region and all of its descendant regions atomically.

    Like scenario removal, this is destructive by design: deleting a kingdom
    cascades to its provinces and cities. The scenario itself is untouched.
    """
    _validate_scenario_id(scenario_id)
    _validate_operation_id(operation_id)
    region_id = _validate_region_id(region_id)
    request = {"region_id": region_id}
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="remove_scenario_region",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            _require_scenario(connection, scenario_id)
            existing = connection.execute(
                "SELECT region_id FROM scenario_regions "
                "WHERE scenario_id = ? AND region_id = ?",
                (scenario_id, region_id),
            ).fetchone()
            if existing is None:
                raise ScenarioNotFound(f"region not found: {region_id}")
            connection.execute(
                "DELETE FROM scenario_regions "
                "WHERE scenario_id = ? AND region_id = ?",
                (scenario_id, region_id),
            )
            result = {
                "already_applied": False,
                "scenario_id": scenario_id,
                "region_id": region_id,
                "removed": True,
            }
            _record_operation(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="remove_scenario_region",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except ScenarioError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def remove_scenario(
    database_path: str | Path,
    *,
    scenario_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Remove a scenario and its elements atomically (destructive)."""
    _validate_scenario_id(scenario_id)
    _validate_operation_id(operation_id)

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _require_scenario(connection, scenario_id)
            connection.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
            connection.commit()
            return {"already_applied": False, "scenario_id": scenario_id, "removed": True}
        except ScenarioError:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def read_scenario(database_path: str | Path, scenario_id: str) -> dict[str, Any]:
    """Read one scenario with its elements from one read-only snapshot."""
    with closing(connect_readonly_database(database_path)) as connection:
        row = connection.execute(
            "SELECT id, title, description, created_at FROM scenarios WHERE id = ?",
            (scenario_id,),
        ).fetchone()
        if row is None:
            raise ScenarioNotFound(f"scenario not found: {scenario_id}")
        elements = connection.execute(
            "SELECT element_type, content, updated_at FROM scenario_elements "
            "WHERE scenario_id = ? ORDER BY element_type",
            (scenario_id,),
        ).fetchall()
        regions = connection.execute(
            "SELECT region_id, parent_region_id, level, title, description, "
            "attributes_json, updated_at FROM scenario_regions "
            "WHERE scenario_id = ? ORDER BY region_id",
            (scenario_id,),
        ).fetchall()
        return {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "created_at": row["created_at"],
            "elements": [
                {
                    "element_type": element["element_type"],
                    "content": element["content"],
                    "updated_at": element["updated_at"],
                }
                for element in elements
            ],
            "regions": [
                {
                    "region_id": region["region_id"],
                    "parent_region_id": region["parent_region_id"],
                    "level": region["level"],
                    "title": region["title"],
                    "description": region["description"],
                    "attributes": json.loads(region["attributes_json"]),
                    "updated_at": region["updated_at"],
                }
                for region in regions
            ],
        }


def list_scenarios(database_path: str | Path) -> list[dict[str, Any]]:
    """List scenarios (without elements) newest-independent, ordered by id."""
    with closing(connect_readonly_database(database_path)) as connection:
        rows = connection.execute(
            "SELECT id, title, description, created_at FROM scenarios ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]
