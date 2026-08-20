from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence.database import connect_database
from backend.persistence.migrations import MigrationError, migrate_database
from backend.scenarios.ward.seed import seed_ward_world


def test_migrate_creates_versioned_schema_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"

    first = migrate_database(database_path)
    second = migrate_database(database_path)

    assert first == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    assert second == []

    with connect_database(database_path) as connection:
        applied = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert [tuple(row) for row in applied] == [
        (1, "initial_world_schema"),
        (2, "generalize_entities"),
        (3, "social_state"),
        (4, "resources"),
        (5, "location_properties"),
        (6, "location_links"),
        (7, "scenarios"),
        (8, "world_metadata"),
        (9, "world_elements"),
        (10, "player_characters"),
        (11, "location_hierarchy"),
        (12, "location_scope_promotions"),
        (13, "world_routes"),
        (14, "world_expansion"),
        (15, "location_geography"),
        (16, "location_map_forms"),
        (17, "narration_history"),
        (18, "location_memories"),
        (19, "scenario_regions"),
        (20, "world_regions"),
    ]
    assert {
        "worlds",
        "locations",
        "entities",
        "entity_locations",
        "characters",
        "beds",
        "operations",
        "events",
        "location_containment",
        "location_metadata",
        "location_scope_promotions",
        "world_routes",
        "world_expansion_limits",
        "world_expansion_proposals",
        "narration_history",
        "location_memories",
        "scenario_regions",
        "world_regions",
        "schema_migrations",
    } <= tables


def test_generalization_migration_preserves_existing_ward_data(tmp_path: Path) -> None:
    migrations_path = Path(__file__).parents[2] / "backend" / "migrations"
    database_path = tmp_path / "world.sqlite3"
    migration_one_path = tmp_path / "migration-one"
    migration_one_path.mkdir()
    (migration_one_path / "0001_initial_world_schema.sql").write_text(
        (migrations_path / "0001_initial_world_schema.sql").read_text()
    )
    migrate_database(database_path, migrations_path=migration_one_path)
    seed_ward_world(database_path)

    assert migrate_database(database_path) == [
        2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    ]

    with connect_database(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM beds").fetchone()[0] == 6
        assert connection.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 7
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_generalized_schema_accepts_scenario_defined_entity_kinds_and_roles(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)

    with connect_database(database_path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('world', 'World')")
        connection.execute(
            "INSERT INTO entities(id, world_id, kind, name) "
            "VALUES ('quest', 'world', 'quest', 'Find the moon')"
        )
        connection.execute(
            "INSERT INTO entities(id, world_id, kind, name) "
            "VALUES ('farmer', 'world', 'character', 'Farmer')"
        )
        connection.execute(
            "INSERT INTO characters(entity_id, role, disposition) "
            "VALUES ('farmer', 'chicken_farmer', 'underwater')"
        )
        connection.commit()

    with connect_database(database_path) as connection:
        assert (
            connection.execute("SELECT kind FROM entities WHERE id = 'quest'").fetchone()[0]
            == "quest"
        )
        assert tuple(
            connection.execute(
                "SELECT role, disposition FROM characters WHERE entity_id = 'farmer'"
            ).fetchone()
        ) == ("chicken_farmer", "underwater")


def test_database_connections_enforce_foreign_keys_and_busy_timeout(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"

    with connect_database(database_path) as connection:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert foreign_keys == 1
    assert busy_timeout == 5_000


def test_changed_applied_migration_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrations_path = tmp_path / "migrations"
    migrations_path.mkdir()
    migration = migrations_path / "0001_example.sql"
    migration.write_text("CREATE TABLE example (id INTEGER PRIMARY KEY);\n")
    migrate_database(database_path, migrations_path=migrations_path)
    migration.write_text("CREATE TABLE changed (id INTEGER PRIMARY KEY);\n")

    with pytest.raises(MigrationError, match="checksum"):
        migrate_database(database_path, migrations_path=migrations_path)


def test_failed_migration_rolls_back_schema_and_version_record(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrations_path = tmp_path / "migrations"
    migrations_path.mkdir()
    (migrations_path / "0001_broken.sql").write_text(
        "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY);\n"
        "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY);\n"
    )

    with pytest.raises(sqlite3.OperationalError):
        migrate_database(database_path, migrations_path=migrations_path)

    with connect_database(database_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'should_rollback'"
        ).fetchone()
        versions = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]

    assert table is None
    assert versions == 0


def test_applied_migration_history_must_be_a_contiguous_prefix(tmp_path: Path) -> None:
    migrations_path = tmp_path / "migrations"
    migrations_path.mkdir()
    (migrations_path / "0001_first.sql").write_text("CREATE TABLE first(id INTEGER);\n")
    (migrations_path / "0002_second.sql").write_text("CREATE TABLE second(id INTEGER);\n")
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path, migrations_path=migrations_path)

    with connect_database(database_path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 1")
        connection.commit()

    with pytest.raises(MigrationError, match="contiguous prefix"):
        migrate_database(database_path, migrations_path=migrations_path)
