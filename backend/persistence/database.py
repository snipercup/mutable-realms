from __future__ import annotations

import sqlite3
from pathlib import Path

BUSY_TIMEOUT_MS = 5_000


def connect_database(database_path: str | Path) -> sqlite3.Connection:
    """Open a configured SQLite connection for authoritative world state."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1_000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
