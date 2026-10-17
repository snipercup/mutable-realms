"""Scenario-authored lore and revision-checked world-owned lore copies."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database
from backend.world.mutations import event_id
from backend.world.scenarios import (
    ScenarioConflict,
    ScenarioNotFound,
    _record_operation,
    _replay_or_conflict,
    _require_scenario,
    _validate_operation_id,
    _validate_scenario_id,
)
from backend.world.worlds import (
    WorldAdminConflict,
    WorldAdminNotFound,
    _check_revision,
    _commit_world_mutation,
    _require_world,
    _validate_world_id,
)
from backend.world.worlds import (
    _replay_or_conflict as _world_replay_or_conflict,
)
from backend.world.worlds import (
    _validate_operation_id as _validate_world_operation_id,
)

_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MAX_ID_LENGTH = 100
_MAX_CATEGORY_LENGTH = 80
_MAX_TITLE_LENGTH = 200
_MAX_CONTENT_LENGTH = 20_000
_MAX_KEYWORDS_JSON_LENGTH = 10_000
_MAX_RELEVANT_ENTRIES = 8
_MAX_RELEVANT_CHARS = 8_000
_WORLD_LORE_UPDATED_EVENT = "world_lore_updated"
_WORLD_LORE_REMOVED_EVENT = "world_lore_removed"


def _validate_lore_id(lore_id: str, error: type[Exception]) -> str:
    value = lore_id.strip()
    if not _ID_PATTERN.fullmatch(value) or len(value) > _MAX_ID_LENGTH:
        raise error("lore id must be lowercase kebab-case (letters, digits, hyphens)")
    return value


def _validate_text(value: str, field: str, maximum: int, error: type[Exception]) -> str:
    value = value.strip()
    if not value:
        raise error(f"lore {field} must not be blank")
    if len(value) > maximum:
        raise error(f"lore {field} must be at most {maximum} characters")
    return value


def _normalize_keywords(
    keywords: list[str] | None, error: type[Exception]
) -> tuple[list[str], str]:
    if keywords is None:
        keywords = []
    if not isinstance(keywords, list) or any(not isinstance(item, str) for item in keywords):
        raise error("lore keywords must be an array of strings")
    normalized = list(dict.fromkeys(item.strip() for item in keywords if item.strip()))
    if len(normalized) > 40 or any(len(item) > 120 for item in normalized):
        raise error("lore keywords must contain at most 40 entries of 120 characters")
    encoded = json.dumps(normalized, separators=(",", ":"))
    if len(encoded) > _MAX_KEYWORDS_JSON_LENGTH:
        raise error("lore keywords are too long")
    return normalized, encoded


def _lore_row(row: sqlite3.Row, *, include_content: bool = True) -> dict[str, Any]:
    value = {
        "lore_id": row["lore_id"],
        "category": row["category"],
        "title": row["title"],
        "keywords": json.loads(row["keywords_json"]),
    }
    if include_content:
        value["content"] = row["content"]
    return value


def read_scenario_lore(database_path: str | Path, *, scenario_id: str) -> list[dict[str, Any]]:
    with connect_readonly_database(database_path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
        if exists is None:
            raise ScenarioNotFound(f"scenario not found: {scenario_id}")
        rows = connection.execute(
            "SELECT lore_id, category, title, content, keywords_json "
            "FROM scenario_lore WHERE scenario_id = ? "
            "ORDER BY category, title, lore_id",
            (scenario_id,),
        ).fetchall()
    return [_lore_row(row) for row in rows]


def set_scenario_lore(
    database_path: str | Path,
    *,
    scenario_id: str,
    operation_id: str,
    lore_id: str,
    category: str,
    title: str,
    content: str,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    _validate_scenario_id(scenario_id)
    _validate_operation_id(operation_id)
    lore_id = _validate_lore_id(lore_id, ScenarioConflict)
    category = _validate_text(category, "category", _MAX_CATEGORY_LENGTH, ScenarioConflict)
    title = _validate_text(title, "title", _MAX_TITLE_LENGTH, ScenarioConflict)
    content = _validate_text(content, "content", _MAX_CONTENT_LENGTH, ScenarioConflict)
    keywords, keywords_json = _normalize_keywords(keywords, ScenarioConflict)
    request = {
        "category": category,
        "content": content,
        "keywords": keywords,
        "lore_id": lore_id,
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
                operation_type="set_scenario_lore",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            _require_scenario(connection, scenario_id)
            connection.execute(
                "INSERT INTO scenario_lore("
                "scenario_id,lore_id,category,title,content,keywords_json) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(scenario_id,lore_id) DO UPDATE SET "
                "category=excluded.category,title=excluded.title,content=excluded.content,"
                "keywords_json=excluded.keywords_json,updated_at=CURRENT_TIMESTAMP",
                (scenario_id, lore_id, category, title, content, keywords_json),
            )
            result = {"already_applied": False, "scenario_id": scenario_id, "lore_id": lore_id}
            _record_operation(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="set_scenario_lore",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except ScenarioConflict:
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def remove_scenario_lore(
    database_path: str | Path, *, scenario_id: str, operation_id: str, lore_id: str
) -> dict[str, Any]:
    _validate_scenario_id(scenario_id)
    _validate_operation_id(operation_id)
    lore_id = _validate_lore_id(lore_id, ScenarioConflict)
    request_json = json.dumps({"lore_id": lore_id}, sort_keys=True, separators=(",", ":"))
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="remove_scenario_lore",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            _require_scenario(connection, scenario_id)
            if (
                connection.execute(
                    "DELETE FROM scenario_lore WHERE scenario_id=? AND lore_id=?",
                    (scenario_id, lore_id),
                ).rowcount
                != 1
            ):
                raise ScenarioNotFound(f"lore entry not found: {lore_id}")
            result = {"already_applied": False, "scenario_id": scenario_id, "lore_id": lore_id}
            _record_operation(
                connection,
                scenario_id=scenario_id,
                operation_id=operation_id,
                operation_type="remove_scenario_lore",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except (ScenarioConflict, ScenarioNotFound):
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def read_world_lore(database_path: str | Path, *, world_id: str, lore_id: str) -> dict[str, Any]:
    with connect_readonly_database(database_path) as connection:
        row = connection.execute(
            "SELECT lore_id, category, title, content, keywords_json "
            "FROM world_lore WHERE world_id = ? AND lore_id = ?",
            (world_id, lore_id),
        ).fetchone()
    if row is None:
        raise WorldAdminNotFound(f"lore entry not found: {lore_id}")
    return _lore_row(row)


def list_world_lore(database_path: str | Path, *, world_id: str) -> list[dict[str, Any]]:
    with connect_readonly_database(database_path) as connection:
        rows = connection.execute(
            "SELECT lore_id, category, title, content, keywords_json "
            "FROM world_lore WHERE world_id = ? "
            "ORDER BY category, title, lore_id",
            (world_id,),
        ).fetchall()
    return [_lore_row(row) for row in rows]


def search_world_lore(
    database_path: str | Path, *, world_id: str, query: str, limit: int = 10
) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        raise WorldAdminConflict("lore query must not be blank")
    if not 1 <= limit <= 20:
        raise WorldAdminConflict("lore limit must be between 1 and 20")
    needle = f"%{query}%"
    with connect_readonly_database(database_path) as connection:
        rows = connection.execute(
            "SELECT lore_id, category, title, content, keywords_json FROM world_lore "
            "WHERE world_id = ? AND ("
            "lore_id LIKE ? COLLATE NOCASE OR category LIKE ? COLLATE NOCASE OR "
            "title LIKE ? COLLATE NOCASE OR keywords_json LIKE ? COLLATE NOCASE OR "
            "content LIKE ? COLLATE NOCASE) ORDER BY title, lore_id LIMIT ?",
            (world_id, needle, needle, needle, needle, needle, limit),
        ).fetchall()
    return [_lore_row(row, include_content=False) for row in rows]


def _mutate_world_lore(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    lore_id: str,
    values: dict[str, Any] | None,
) -> dict[str, Any]:
    _validate_world_id(world_id)
    _validate_world_operation_id(operation_id)
    lore_id = _validate_lore_id(lore_id, WorldAdminConflict)
    operation_type = _WORLD_LORE_UPDATED_EVENT if values is not None else _WORLD_LORE_REMOVED_EVENT
    request = {"lore_id": lore_id, **(values or {})}
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _world_replay_or_conflict(
                connection,
                world_id=world_id,
                operation_id=operation_id,
                operation_type=operation_type,
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
                operation_type=operation_type,
                request_json=request_json,
                event_identifier=event_identifier,
                summary=(
                    f"lore entry {lore_id} updated"
                    if values is not None
                    else f"lore entry {lore_id} removed"
                ),
                payload={
                    "lore_id": lore_id,
                    **(
                        {"category": values["category"], "title": values["title"]} if values else {}
                    ),
                },
                expected_revision=expected_revision,
                result_fields={"lore_id": lore_id},
            )
            if values is None:
                if (
                    connection.execute(
                        "DELETE FROM world_lore WHERE world_id=? AND lore_id=?", (world_id, lore_id)
                    ).rowcount
                    != 1
                ):
                    raise WorldAdminNotFound(f"lore entry not found: {lore_id}")
            else:
                connection.execute(
                    "INSERT INTO world_lore("
                    "world_id,lore_id,category,title,content,keywords_json,updated_event_id) "
                    "VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(world_id,lore_id) DO UPDATE SET "
                    "category=excluded.category,title=excluded.title,content=excluded.content,"
                    "keywords_json=excluded.keywords_json,"
                    "updated_event_id=excluded.updated_event_id",
                    (
                        world_id,
                        lore_id,
                        values["category"],
                        values["title"],
                        values["content"],
                        values["keywords_json"],
                        event_identifier,
                    ),
                )
            connection.commit()
            return result
        except (WorldAdminConflict, WorldAdminNotFound):
            connection.rollback()
            raise
        except sqlite3.Error:
            connection.rollback()
            raise


def set_world_lore(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    lore_id: str,
    category: str,
    title: str,
    content: str,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "category": _validate_text(category, "category", _MAX_CATEGORY_LENGTH, WorldAdminConflict),
        "title": _validate_text(title, "title", _MAX_TITLE_LENGTH, WorldAdminConflict),
        "content": _validate_text(content, "content", _MAX_CONTENT_LENGTH, WorldAdminConflict),
    }
    normalized, values["keywords_json"] = _normalize_keywords(keywords, WorldAdminConflict)
    values["keywords"] = normalized
    return _mutate_world_lore(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        lore_id=lore_id,
        values=values,
    )


def remove_world_lore(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    lore_id: str,
) -> dict[str, Any]:
    return _mutate_world_lore(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        lore_id=lore_id,
        values=None,
    )


def select_relevant_lore(
    entries: list[dict[str, Any]], *, terms: list[str]
) -> list[dict[str, Any]]:
    """Select a bounded working set from scenario-independent world lore."""
    haystack = " ".join(term for term in terms if term).casefold()
    result: list[dict[str, Any]] = []
    used = 0
    for item in sorted(entries, key=lambda entry: (entry["title"], entry["lore_id"])):
        matches = [item["title"], *item["keywords"]]
        if not any(value.casefold() in haystack for value in matches if value):
            continue
        size = len(item["title"]) + len(item["category"]) + len(item["content"])
        if len(result) >= _MAX_RELEVANT_ENTRIES or used + size > _MAX_RELEVANT_CHARS:
            continue
        result.append(item)
        used += size
    return result


def relevant_world_lore(
    connection: sqlite3.Connection, *, world_id: str, terms: list[str]
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT lore_id, category, title, content, keywords_json "
        "FROM world_lore WHERE world_id = ? ORDER BY title, lore_id",
        (world_id,),
    ).fetchall()
    return select_relevant_lore([_lore_row(row) for row in rows], terms=terms)
