"""Reusable player-character definitions.

Definitions are administrative templates. World-specific instances are copied
by ``worlds.instance_player_character`` and never read back from this table
during play, so later definition edits cannot alter an instance.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database

_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MAX_INFO_LENGTH = 20_000


class CharacterError(RuntimeError):
    """Base error for character-definition operations."""


class CharacterNotFound(CharacterError):
    """A character definition does not exist."""


class CharacterConflict(CharacterError):
    """A character-definition operation violates its preconditions."""


def _validate_id(value: str, label: str) -> None:
    if not _ID_PATTERN.fullmatch(value):
        raise CharacterConflict(f"{label} must be lowercase kebab-case (letters, digits, hyphens)")


def _validate_operation_id(operation_id: str) -> None:
    if not operation_id.strip():
        raise CharacterConflict("operation ID must not be blank")


def _normalize_text(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if len(trimmed) > _MAX_INFO_LENGTH:
        raise CharacterConflict(f"{label} must be at most {_MAX_INFO_LENGTH} characters")
    return trimmed or None


def _validate_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed:
        raise CharacterConflict("name must not be blank")
    return trimmed


def _replay_or_conflict(
    connection: sqlite3.Connection,
    *,
    character_id: str,
    operation_id: str,
    operation_type: str,
    request_json: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT operation_type, request_json, result_json "
        "FROM player_character_operations WHERE character_id = ? AND operation_id = ?",
        (character_id, operation_id),
    ).fetchone()
    if row is None:
        return None
    if row["operation_type"] != operation_type or row["request_json"] != request_json:
        raise CharacterConflict("operation ID was already used for a different request")
    result = json.loads(row["result_json"])
    result["already_applied"] = True
    return result


def _record_operation(
    connection: sqlite3.Connection,
    *,
    character_id: str,
    operation_id: str,
    operation_type: str,
    request_json: str,
    result: dict[str, Any],
) -> None:
    connection.execute(
        "INSERT INTO player_character_operations "
        "(character_id, operation_id, operation_type, request_json, result_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            character_id,
            operation_id,
            operation_type,
            request_json,
            json.dumps(result, sort_keys=True),
        ),
    )


def _require_character(connection: sqlite3.Connection, character_id: str) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM player_character_definitions WHERE id = ?", (character_id,)
        ).fetchone()
        is None
    ):
        raise CharacterNotFound(f"player character not found: {character_id}")


def create_player_character(
    database_path: str | Path,
    *,
    character_id: str,
    operation_id: str,
    name: str,
    basic_info: str | None = None,
) -> dict[str, Any]:
    _validate_id(character_id, "character id")
    _validate_operation_id(operation_id)
    trimmed_name = _validate_name(name)
    normalized_info = _normalize_text(basic_info, "basic info")
    request_json = json.dumps(
        {"basic_info": normalized_info, "name": trimmed_name}, sort_keys=True, separators=(",", ":")
    )
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                character_id=character_id,
                operation_id=operation_id,
                operation_type="create_player_character",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            if (
                connection.execute(
                    "SELECT 1 FROM player_character_definitions WHERE id = ?", (character_id,)
                ).fetchone()
                is not None
            ):
                raise CharacterConflict(f"player character already exists: {character_id}")
            connection.execute(
                "INSERT INTO player_character_definitions(id, name, basic_info) VALUES (?, ?, ?)",
                (character_id, trimmed_name, normalized_info),
            )
            result = {"already_applied": False, "character_id": character_id}
            _record_operation(
                connection,
                character_id=character_id,
                operation_id=operation_id,
                operation_type="create_player_character",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except CharacterError:
            connection.rollback()
            raise


def update_player_character(
    database_path: str | Path,
    *,
    character_id: str,
    operation_id: str,
    name: str | None = None,
    basic_info: str | None = None,
) -> dict[str, Any]:
    _validate_id(character_id, "character id")
    _validate_operation_id(operation_id)
    if name is None and basic_info is None:
        raise CharacterConflict("update requires name or basic info")
    trimmed_name = _validate_name(name) if name is not None else None
    normalized_info = _normalize_text(basic_info, "basic info")
    request_json = json.dumps(
        {"basic_info": normalized_info, "name": trimmed_name}, sort_keys=True, separators=(",", ":")
    )
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _replay_or_conflict(
                connection,
                character_id=character_id,
                operation_id=operation_id,
                operation_type="update_player_character",
                request_json=request_json,
            )
            if replay is not None:
                connection.rollback()
                return replay
            _require_character(connection, character_id)
            if trimmed_name is not None:
                connection.execute(
                    "UPDATE player_character_definitions SET name = ? WHERE id = ?",
                    (trimmed_name, character_id),
                )
            if basic_info is not None:
                connection.execute(
                    "UPDATE player_character_definitions SET basic_info = ? WHERE id = ?",
                    (normalized_info, character_id),
                )
            result = {"already_applied": False, "character_id": character_id}
            _record_operation(
                connection,
                character_id=character_id,
                operation_id=operation_id,
                operation_type="update_player_character",
                request_json=request_json,
                result=result,
            )
            connection.commit()
            return result
        except CharacterError:
            connection.rollback()
            raise


def remove_player_character(
    database_path: str | Path, *, character_id: str, operation_id: str
) -> dict[str, Any]:
    _validate_id(character_id, "character id")
    _validate_operation_id(operation_id)
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _require_character(connection, character_id)
            connection.execute(
                "DELETE FROM player_character_definitions WHERE id = ?", (character_id,)
            )
            connection.commit()
            return {"already_applied": False, "character_id": character_id, "removed": True}
        except CharacterError:
            connection.rollback()
            raise


def read_player_character(database_path: str | Path, character_id: str) -> dict[str, Any]:
    with closing(connect_readonly_database(database_path)) as connection:
        row = connection.execute(
            "SELECT id, name, basic_info, created_at "
            "FROM player_character_definitions WHERE id = ?",
            (character_id,),
        ).fetchone()
    if row is None:
        raise CharacterNotFound(f"player character not found: {character_id}")
    return dict(row)


def list_player_characters(database_path: str | Path) -> list[dict[str, Any]]:
    with closing(connect_readonly_database(database_path)) as connection:
        rows = connection.execute(
            "SELECT id, name, basic_info, created_at FROM player_character_definitions ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]
