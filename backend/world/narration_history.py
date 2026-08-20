"""Append-only player-facing narration history.

Narration history is a transcript of what the narrator told the player: it is
presentation/history state, NOT authoritative world state. It never bumps a
world revision, never writes an event, and never participates in operation
idempotency or ``expected_revision`` checks. Rows cascade away when their
world is deleted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database
from backend.world.queries import WorldNotFound

_MAX_NARRATION_LENGTH = 20000


def append_narration(
    database_path: str | Path,
    *,
    world_id: str,
    revision: int,
    role: str,
    content: str,
) -> None:
    """Append one narration entry for a world.

    ``role`` must be ``"player"`` (the free-form action) or ``"agent"`` (the
    narrator's response). This is a transcript write, not a world mutation.
    """
    if role not in ("player", "agent"):
        raise ValueError("narration role must be 'player' or 'agent'")
    if not content.strip():
        raise ValueError("narration content must not be blank")
    if len(content) > _MAX_NARRATION_LENGTH:
        raise ValueError("narration content is too long")
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO narration_history (world_id, revision, role, content) "
            "VALUES (?, ?, ?, ?)",
            (world_id, revision, role, content),
        )


def read_narration_history(
    database_path: str | Path,
    *,
    world_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the most recent narration entries, oldest to newest.

    Raises :class:`WorldNotFound` when the world does not exist.
    """
    if not 1 <= limit <= 100:
        raise ValueError("narration history limit must be between 1 and 100")
    with connect_readonly_database(database_path) as connection:
        world = connection.execute(
            "SELECT 1 FROM worlds WHERE id = ?", (world_id,)
        ).fetchone()
        if world is None:
            raise WorldNotFound(f"World {world_id!r} was not found")
        rows = connection.execute(
            """
            SELECT id, world_id, revision, role, content, occurred_at
            FROM narration_history
            WHERE world_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (world_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "world_id": row["world_id"],
            "revision": row["revision"],
            "role": row["role"],
            "content": row["content"],
            "occurred_at": row["occurred_at"],
        }
        for row in reversed(rows)
    ]
