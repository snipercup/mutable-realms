from __future__ import annotations

import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_readonly_database


def read_linked_locations(
    database_path: str | Path,
    *,
    world_id: str,
    location_id: str,
    _connection: sqlite3.Connection | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return adjacent locations for one location on the shared snapshot."""
    connection_context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with connection_context as connection:
        linked = [
            dict(row)
            for row in connection.execute(
                """
                SELECT l.id, l.name
                FROM location_links ll
                JOIN locations l
                  ON l.id = CASE WHEN ll.location_a = ? THEN ll.location_b ELSE ll.location_a END
                WHERE ll.world_id = ? AND ? IN (ll.location_a, ll.location_b)
                ORDER BY l.id
                """,
                (location_id, world_id, location_id),
            )
        ]
    return {"linked_locations": linked}
