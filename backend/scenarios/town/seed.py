from __future__ import annotations

from pathlib import Path

from backend.persistence.database import connect_database

TOWN_WORLD_ID = "town-world"

_LOCATIONS = [
    ("plaza", "Harbor Plaza", "The town center, paved with salt-worn stone."),
    ("market", "Fish Market", "Stalls of nets, crates, and the morning catch."),
    ("tavern", "The Drowned Gull", "A low-beamed tavern by the harbor."),
    ("docks", "Harbor Docks", "Rope-slick planks over dark water."),
]

_LINKS = [
    ("market", "plaza"),
    ("plaza", "tavern"),
    ("docks", "market"),
    ("docks", "tavern"),
]

_ENTITIES = [
    ("sailor", "character", "Sailor"),
    ("town-barkeep", "character", "Barkeep"),
    ("town-merchant", "character", "Market Merchant"),
    ("town-provisions", "item", "Travel Provisions"),
]

_CHARACTERS = [
    ("sailor", "player", "active"),
    ("town-barkeep", "npc", "active"),
    ("town-merchant", "npc", "active"),
]

_PLACEMENTS = [
    ("sailor", "plaza"),
    ("town-barkeep", "tavern"),
    ("town-merchant", "market"),
    ("town-provisions", "market"),
]


def seed_town_world(database_path: str | Path) -> bool:
    """Create a deterministic small connected world for travel; no-op when present."""
    with connect_database(database_path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM worlds WHERE id = ?", (TOWN_WORLD_ID,)
        ).fetchone()
        if exists is not None:
            return False
        connection.execute(
            "INSERT INTO worlds(id, name) VALUES (?, ?)", (TOWN_WORLD_ID, "Harbor Town")
        )
        connection.executemany(
            "INSERT INTO locations(id, world_id, name, description) VALUES (?, ?, ?, ?)",
            [
                (loc_id, TOWN_WORLD_ID, name, description)
                for loc_id, name, description in _LOCATIONS
            ],
        )
        connection.executemany(
            "INSERT INTO location_links(world_id, location_a, location_b) VALUES (?, ?, ?)",
            [(TOWN_WORLD_ID, a, b) for a, b in _LINKS],
        )
        connection.executemany(
            "INSERT INTO entities(id, world_id, kind, name) VALUES (?, ?, ?, ?)",
            [(entity_id, TOWN_WORLD_ID, kind, name) for entity_id, kind, name in _ENTITIES],
        )
        connection.executemany(
            "INSERT INTO characters(entity_id, role, disposition) VALUES (?, ?, ?)",
            _CHARACTERS,
        )
        connection.executemany(
            "INSERT INTO entity_locations(entity_id, location_id) VALUES (?, ?)",
            _PLACEMENTS,
        )
        connection.commit()
    return True
