from __future__ import annotations

from pathlib import Path

from backend.persistence.database import connect_database

GENERAL_WORLD_ID = "open-world"


def seed_general_world(database_path: Path) -> None:
    """Create a small world with no ward, patient, or bed state."""
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO worlds(id, name) VALUES (?, ?)",
            (GENERAL_WORLD_ID, "Open World"),
        )
        connection.executemany(
            "INSERT INTO locations(id, world_id, name, description) VALUES (?, ?, ?, ?)",
            [
                ("ocean-farm", GENERAL_WORLD_ID, "Ocean Farm", "A farm on the ocean floor."),
                ("kelp-market", GENERAL_WORLD_ID, "Kelp Market", "A nearby market."),
            ],
        )
        connection.executemany(
            "INSERT INTO entities(id, world_id, kind, name) VALUES (?, ?, ?, ?)",
            [
                ("farmer", GENERAL_WORLD_ID, "character", "The Farmer"),
                ("hen", GENERAL_WORLD_ID, "animal", "Henrietta"),
                ("basket", GENERAL_WORLD_ID, "item", "Egg Basket"),
            ],
        )
        connection.execute(
            "INSERT INTO characters(entity_id, role, disposition) VALUES (?, ?, ?)",
            ("farmer", "player", "active"),
        )
        connection.executemany(
            "INSERT INTO entity_locations(entity_id, location_id) VALUES (?, ?)",
            [
                ("farmer", "ocean-farm"),
                ("hen", "ocean-farm"),
                ("basket", "ocean-farm"),
            ],
        )
        connection.commit()
