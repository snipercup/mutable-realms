from __future__ import annotations

from pathlib import Path

from backend.persistence.database import connect_database

WARD_WORLD_ID = "ward-world"
WARD_LOCATION_ID = "ward"
PLAYER_ID = "player"


def seed_ward_world(database_path: str | Path) -> bool:
    """Create the deterministic ward example, returning false when it exists."""
    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM worlds WHERE id = ?", (WARD_WORLD_ID,)
            ).fetchone()
            if exists is not None:
                connection.rollback()
                return False

            connection.execute(
                "INSERT INTO worlds(id, name) VALUES (?, ?)",
                (WARD_WORLD_ID, "Recovery Ward"),
            )
            connection.execute(
                "INSERT INTO locations(id, world_id, name, description) VALUES (?, ?, ?, ?)",
                (
                    WARD_LOCATION_ID,
                    WARD_WORLD_ID,
                    "Recovery Ward",
                    "A small six-bed ward used to verify persistent causality.",
                ),
            )

            entities = [(PLAYER_ID, WARD_WORLD_ID, "character", "Player")]
            entities.extend(
                (f"patient-{number}", WARD_WORLD_ID, "character", f"Patient {number}")
                for number in range(1, 7)
            )
            entities.extend(
                (f"bed-{number}", WARD_WORLD_ID, "bed", f"Bed {number}")
                for number in range(1, 7)
            )
            connection.executemany(
                "INSERT INTO entities(id, world_id, kind, name) VALUES (?, ?, ?, ?)",
                entities,
            )

            placements = [(entity_id, WARD_LOCATION_ID) for entity_id, *_ in entities]
            connection.executemany(
                "INSERT INTO entity_locations(entity_id, location_id) VALUES (?, ?)",
                placements,
            )
            connection.execute(
                "INSERT INTO characters(entity_id, role, condition, disposition) "
                "VALUES (?, 'player', NULL, 'active')",
                (PLAYER_ID,),
            )
            connection.executemany(
                "INSERT INTO characters(entity_id, role, condition, disposition) "
                "VALUES (?, 'patient', 'untreated', 'admitted')",
                [(f"patient-{number}",) for number in range(1, 7)],
            )
            connection.executemany(
                "INSERT INTO beds(entity_id, location_id, occupant_entity_id) VALUES (?, ?, ?)",
                [
                    (f"bed-{number}", WARD_LOCATION_ID, f"patient-{number}")
                    for number in range(1, 7)
                ],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return True
