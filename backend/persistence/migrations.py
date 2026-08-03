from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MIGRATIONS_PATH = Path(__file__).parents[1] / "migrations"
_MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z][a-z0-9_]*)\.sql$")


class MigrationError(RuntimeError):
    """Raised when migration history or files are invalid."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    sql: str


def _load_migrations(migrations_path: Path) -> list[Migration]:
    if not migrations_path.is_dir():
        raise MigrationError(f"Migration directory does not exist: {migrations_path}")

    migrations: list[Migration] = []
    for path in sorted(migrations_path.glob("*.sql")):
        match = _MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"Invalid migration filename: {path.name}")
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                checksum=hashlib.sha256(sql.encode()).hexdigest(),
                sql=sql,
            )
        )

    expected = list(range(1, len(migrations) + 1))
    versions = [migration.version for migration in migrations]
    if versions != expected:
        raise MigrationError(f"Migration versions must be contiguous from 0001; found {versions}")
    return migrations


def _statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise MigrationError("Migration contains an incomplete SQL statement")
    return statements


def _verify_history(
    connection: sqlite3.Connection,
    migrations: list[Migration],
    *,
    require_all: bool,
) -> dict[int, sqlite3.Row]:
    applied = {
        row["version"]: row
        for row in connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        )
    }
    known_versions = {migration.version for migration in migrations}
    unknown_versions = set(applied) - known_versions
    if unknown_versions:
        raise MigrationError(
            f"Database contains unsupported migration versions: {sorted(unknown_versions)}"
        )
    applied_versions = sorted(applied)
    expected_prefix = list(range(1, max(applied_versions, default=0) + 1))
    if applied_versions != expected_prefix:
        raise MigrationError(
            f"Applied migration history must be a contiguous prefix; found {applied_versions}"
        )

    for migration in migrations:
        existing = applied.get(migration.version)
        if existing is None:
            if require_all:
                raise MigrationError(f"Database is missing migration {migration.version:04d}")
            continue
        if existing["name"] != migration.name:
            raise MigrationError(f"Applied migration {migration.version:04d} name does not match")
        if existing["checksum"] != migration.checksum:
            raise MigrationError(
                f"Applied migration {migration.version:04d} checksum does not match"
            )
    return applied


def verify_database_schema(
    database_path: str | Path,
    *,
    migrations_path: str | Path = DEFAULT_MIGRATIONS_PATH,
) -> None:
    """Verify that a database has exactly the supported migration history."""
    from backend.persistence.database import connect_database

    migrations = _load_migrations(Path(migrations_path))
    with connect_database(database_path) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if table is None:
            raise MigrationError("Database has not been migrated")
        _verify_history(connection, migrations, require_all=True)


def migrate_database(
    database_path: str | Path,
    *,
    migrations_path: str | Path = DEFAULT_MIGRATIONS_PATH,
) -> list[int]:
    """Apply pending migrations atomically and return their version numbers."""
    from backend.persistence.database import connect_database

    migrations = _load_migrations(Path(migrations_path))
    applied_now: list[int] = []

    with connect_database(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) STRICT
            """
        )
        connection.commit()
        applied = _verify_history(connection, migrations, require_all=False)

        for migration in migrations:
            existing = applied.get(migration.version)
            if existing is not None:
                continue

            try:
                connection.execute("BEGIN IMMEDIATE")
                for statement in _statements(migration.sql):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
                    (migration.version, migration.name, migration.checksum),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            applied_now.append(migration.version)

    return applied_now
