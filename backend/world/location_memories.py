"""Location-scoped narrative memories.

Location memories are condensed, narrator-maintained narrative facts about a
place ("Fate fixed a cart at the farmstead") and are distinct from the
quantified ``location_properties`` ledger (exact counts, ward patients,
visits). They are:

- keyed by a normalized ``memory_key`` so recording the same key again
  increments ``occurrence_count`` instead of duplicating the row;
- revision-checked, exactly idempotent, and linked to an event through the
  standard operation ledger;
- bounded in *stored* size per location (a large budget) and in *rendered*
  size (a token budget applied when reading for context, newest first).

Memories are authoritative narrative state, not presentation: they persist
and are read back into the narrator's context. Only the player's current
location's memories are exposed by ``build_world_context``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database
from backend.world.mutations import event_id

_MEMORY_EVENT = "location_memory_recorded"
_CONSOLIDATE_EVENT = "location_memories_consolidated"
_MAX_KEY_LENGTH = 100
_MAX_CONTENT_LENGTH = 300
_MAX_MEMORIES_PER_LOCATION = 200
_RENDER_MAX_TOKENS = 1000
_CHARS_PER_TOKEN = 4
_WHITESPACE = re.compile(r"\s+")


class MemoryError(RuntimeError):
    """Base error for location memory operations."""


class MemoryNotFound(MemoryError):
    """A referenced memory resource does not exist."""


class MemoryConflict(MemoryError):
    """A memory operation violates an authoritative invariant."""


def _clean(value: str, label: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise MemoryConflict(f"{label} must not be blank")
    if len(cleaned) > maximum:
        raise MemoryConflict(f"{label} must be at most {maximum} characters")
    return cleaned


def normalize_memory_key(key: str) -> str:
    """Normalize a memory key so casing/whitespace variants merge."""
    return _WHITESPACE.sub(" ", key.strip().lower())


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _existing_operation(
    connection: sqlite3.Connection,
    world_id: str,
    operation_id: str,
    operation_type: str,
    request_json: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT operation_type, request_json, result_json FROM operations "
        "WHERE world_id = ? AND operation_id = ?",
        (world_id, operation_id),
    ).fetchone()
    if row is None:
        return None
    if row["operation_type"] != operation_type or row["request_json"] != request_json:
        raise MemoryConflict("operation ID was already used for a different request")
    result = json.loads(row["result_json"])
    result["already_applied"] = True
    return result


def record_location_memory(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    location_id: str,
    memory_key: str,
    content: str,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Atomically record one location memory (or bump its occurrence count).

    The same normalized ``memory_key`` on the same location increments
    ``occurrence_count`` and refreshes the content instead of inserting a
    duplicate row. One revision, one event, exact idempotency.
    """
    world_id = _clean(world_id, "world ID", 100)
    operation_id = _clean(operation_id, "operation ID", 100)
    location_id = _clean(location_id, "location ID", 100)
    key = normalize_memory_key(_clean(memory_key, "memory key", _MAX_KEY_LENGTH))
    content = content.strip()
    if not content:
        raise MemoryConflict("memory content must not be blank")
    if len(content) > _MAX_CONTENT_LENGTH:
        raise MemoryConflict(
            f"memory content must be at most {_MAX_CONTENT_LENGTH} characters"
        )
    request = {
        "actor_entity_id": actor_entity_id,
        "content": content,
        "expected_revision": expected_revision,
        "location_id": location_id,
        "memory_key": memory_key,
    }
    request_json = _json(request)

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _existing_operation(
                connection, world_id, operation_id, _MEMORY_EVENT, request_json
            )
            if replay is not None:
                connection.rollback()
                return replay
            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise MemoryNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise MemoryConflict(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )
            location = connection.execute(
                "SELECT name FROM locations WHERE world_id = ? AND id = ?",
                (world_id, location_id),
            ).fetchone()
            if location is None:
                raise MemoryNotFound(f"location not found: {location_id}")
            if actor_entity_id is not None:
                if (
                    connection.execute(
                        "SELECT 1 FROM entities WHERE world_id = ? AND id = ?",
                        (world_id, actor_entity_id),
                    ).fetchone()
                    is None
                ):
                    raise MemoryNotFound(f"actor not found: {actor_entity_id}")
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM location_memories "
                "WHERE world_id = ? AND location_id = ?",
                (world_id, location_id),
            ).fetchone()["count"]
            if count >= _MAX_MEMORIES_PER_LOCATION:
                raise MemoryConflict(
                    "location memory budget is exhausted; consolidate older "
                    "memories before recording more"
                )

            next_revision = expected_revision + 1
            result = {
                "already_applied": False,
                "location_id": location_id,
                "memory_key": key,
                "occurrence_count": None,
                "world_id": world_id,
                "world_revision": next_revision,
            }
            identifier = event_id(world_id, operation_id)
            connection.execute(
                "INSERT INTO operations("
                "world_id, operation_id, operation_type, request_json, result_json, "
                "completed_revision) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    world_id,
                    operation_id,
                    _MEMORY_EVENT,
                    request_json,
                    _json({k: v for k, v in result.items() if k != "already_applied"}),
                    next_revision,
                ),
            )
            connection.execute(
                "INSERT INTO events("
                "id, world_id, operation_id, event_type, actor_entity_id, summary, "
                "payload_json, world_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    world_id,
                    operation_id,
                    _MEMORY_EVENT,
                    actor_entity_id,
                    f"Memory recorded at {location['name']}",
                    _json(
                        {
                            "content": content,
                            "location_id": location_id,
                            "memory_key": key,
                        }
                    ),
                    next_revision,
                ),
            )
            existing = connection.execute(
                "SELECT occurrence_count FROM location_memories "
                "WHERE world_id = ? AND location_id = ? AND memory_key = ?",
                (world_id, location_id, key),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO location_memories("
                    "world_id, location_id, memory_key, content, occurrence_count, "
                    "updated_event_id) VALUES (?, ?, ?, ?, 1, ?)",
                    (world_id, location_id, key, content, identifier),
                )
                result["occurrence_count"] = 1
            else:
                connection.execute(
                    "UPDATE location_memories SET content = ?, "
                    "occurrence_count = occurrence_count + 1, updated_event_id = ? "
                    "WHERE world_id = ? AND location_id = ? AND memory_key = ?",
                    (content, identifier, world_id, location_id, key),
                )
                result["occurrence_count"] = existing["occurrence_count"] + 1
            connection.execute(
                "UPDATE worlds SET revision = ? WHERE id = ? AND revision = ?",
                (next_revision, world_id, expected_revision),
            )
            connection.commit()
            return result
        except MemoryError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise MemoryConflict(
                "memory record violated a database invariant"
            ) from error


def consolidate_location_memories(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    location_id: str,
    memory_keys: list[str],
    content: str,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Merge several location memories into one condensed row.

    The listed normalized keys are replaced by a single row whose content is
    ``content`` and whose occurrence count is the sum of the merged rows. This
    is the deterministic "narrator summarizes" step when a location's rendered
    memory budget is exceeded.
    """
    world_id = _clean(world_id, "world ID", 100)
    operation_id = _clean(operation_id, "operation ID", 100)
    location_id = _clean(location_id, "location ID", 100)
    if not memory_keys:
        raise MemoryConflict("memory_keys must not be empty")
    keys = [normalize_memory_key(key) for key in memory_keys]
    if len(set(keys)) != len(keys):
        raise MemoryConflict("memory_keys must be distinct")
    content = content.strip()
    if not content:
        raise MemoryConflict("memory content must not be blank")
    if len(content) > _MAX_CONTENT_LENGTH:
        raise MemoryConflict(
            f"memory content must be at most {_MAX_CONTENT_LENGTH} characters"
        )
    new_key = normalize_memory_key(content)
    request = {
        "actor_entity_id": actor_entity_id,
        "content": content,
        "expected_revision": expected_revision,
        "location_id": location_id,
        "memory_keys": sorted(keys),
    }
    request_json = _json(request)

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = _existing_operation(
                connection, world_id, operation_id, _CONSOLIDATE_EVENT, request_json
            )
            if replay is not None:
                connection.rollback()
                return replay
            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise MemoryNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise MemoryConflict(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )
            location = connection.execute(
                "SELECT name FROM locations WHERE world_id = ? AND id = ?",
                (world_id, location_id),
            ).fetchone()
            if location is None:
                raise MemoryNotFound(f"location not found: {location_id}")
            if actor_entity_id is not None:
                if (
                    connection.execute(
                        "SELECT 1 FROM entities WHERE world_id = ? AND id = ?",
                        (world_id, actor_entity_id),
                    ).fetchone()
                    is None
                ):
                    raise MemoryNotFound(f"actor not found: {actor_entity_id}")
            placeholders = ",".join("?" for _ in keys)
            rows = connection.execute(
                f"SELECT memory_key, occurrence_count FROM location_memories "
                f"WHERE world_id = ? AND location_id = ? AND memory_key IN ({placeholders})",
                (world_id, location_id, *keys),
            ).fetchall()
            if len(rows) != len(keys):
                found = {row["memory_key"] for row in rows}
                missing = [key for key in keys if key not in found]
                raise MemoryNotFound(f"memories not found: {', '.join(missing)}")
            merged_count = sum(row["occurrence_count"] for row in rows)

            next_revision = expected_revision + 1
            result = {
                "already_applied": False,
                "location_id": location_id,
                "memory_key": new_key,
                "merged_count": merged_count,
                "world_id": world_id,
                "world_revision": next_revision,
            }
            identifier = event_id(world_id, operation_id)
            connection.execute(
                "INSERT INTO operations("
                "world_id, operation_id, operation_type, request_json, result_json, "
                "completed_revision) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    world_id,
                    operation_id,
                    _CONSOLIDATE_EVENT,
                    request_json,
                    _json({k: v for k, v in result.items() if k != "already_applied"}),
                    next_revision,
                ),
            )
            connection.execute(
                "INSERT INTO events("
                "id, world_id, operation_id, event_type, actor_entity_id, summary, "
                "payload_json, world_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    world_id,
                    operation_id,
                    _CONSOLIDATE_EVENT,
                    actor_entity_id,
                    f"Memories consolidated at {location['name']}",
                    _json(
                        {
                            "content": content,
                            "location_id": location_id,
                            "memory_keys": sorted(keys),
                            "merged_count": merged_count,
                        }
                    ),
                    next_revision,
                ),
            )
            # Delete the merged keys, then insert the condensed row. The new
            # key is derived from the content, so if the condensed text already
            # exists under another key it is merged rather than duplicated.
            placeholders_delete = ",".join("?" for _ in keys)
            connection.execute(
                "DELETE FROM location_memories WHERE world_id = ? AND location_id = ? "
                "AND memory_key IN (" + placeholders_delete + ")",
                (world_id, location_id, *keys),
            )
            if new_key in keys:
                connection.execute(
                    "INSERT INTO location_memories("
                    "world_id, location_id, memory_key, content, occurrence_count, "
                    "updated_event_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (world_id, location_id, new_key, content, merged_count, identifier),
                )
            else:
                connection.execute(
                    "INSERT INTO location_memories("
                    "world_id, location_id, memory_key, content, occurrence_count, "
                    "updated_event_id) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(world_id, location_id, memory_key) DO UPDATE SET "
                    "content = excluded.content, "
                    "occurrence_count = location_memories.occurrence_count "
                    "+ excluded.occurrence_count, "
                    "updated_event_id = excluded.updated_event_id",
                    (world_id, location_id, new_key, content, merged_count, identifier),
                )
            connection.execute(
                "UPDATE worlds SET revision = ? WHERE id = ? AND revision = ?",
                (next_revision, world_id, expected_revision),
            )
            connection.commit()
            return result
        except MemoryError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise MemoryConflict(
                "memory consolidation violated a database invariant"
            ) from error


def read_location_memories(
    database_path: str | Path,
    *,
    world_id: str,
    location_ids: list[str],
    _connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Read location memories newest-first, bounded to the render budget.

    Returns only memories that fit within ``_RENDER_MAX_TOKENS`` (coarse
    4 chars/token), newest first; older memories are dropped at this boundary.
    """
    if not location_ids:
        return []
    placeholders = ",".join("?" for _ in location_ids)
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    budget = _RENDER_MAX_TOKENS * _CHARS_PER_TOKEN
    with connection_context as connection:
        rows = connection.execute(
            f"""
            SELECT lm.location_id, lm.memory_key, lm.content,
                   lm.occurrence_count, lm.updated_event_id,
                   (SELECT world_revision FROM events
                    WHERE id = lm.updated_event_id) AS world_revision
            FROM location_memories lm
            WHERE lm.world_id = ? AND lm.location_id IN ({placeholders})
            ORDER BY world_revision DESC, lm.memory_key
            """,
            [world_id, *location_ids],
        ).fetchall()
    memories: list[dict[str, Any]] = []
    used = 0
    for row in rows:
        if row["occurrence_count"] > 1:
            line = f"{row['content']} (x{row['occurrence_count']})"
        else:
            line = row["content"]
        if memories and used + len(line) + 1 > budget:
            break
        used += len(line) + 1
        memories.append(
            {
                "location_id": row["location_id"],
                "memory_key": row["memory_key"],
                "content": row["content"],
                "occurrence_count": row["occurrence_count"],
                "world_revision": row["world_revision"],
            }
        )
    return memories
