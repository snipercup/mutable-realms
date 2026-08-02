from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database
from backend.world.queries import LocationNotFound

WardRecord = dict[str, Any]


class WardCapabilityNotFound(LookupError):
    """Raised when a location has no ward capability state."""


def get_ward_location_state(
    database_path: str | Path, world_id: str, location_id: str
) -> WardRecord:
    """Read optional bed occupancy for a ward-enabled location."""
    with connect_database(database_path) as connection:
        connection.execute("BEGIN")
        location = connection.execute(
            """
            SELECT w.revision
            FROM locations l
            JOIN worlds w ON w.id = l.world_id
            WHERE l.id = ? AND l.world_id = ?
            """,
            (location_id, world_id),
        ).fetchone()
        if location is None:
            raise LocationNotFound(
                f"Location {location_id!r} was not found in world {world_id!r}"
            )
        beds = [
            {
                "id": row["id"],
                "name": row["name"],
                "occupant": (
                    {
                        "id": row["occupant_id"],
                        "name": row["occupant_name"],
                        "role": row["occupant_role"],
                        "condition": row["occupant_condition"],
                        "disposition": row["occupant_disposition"],
                    }
                    if row["occupant_id"] is not None
                    else None
                ),
            }
            for row in connection.execute(
                """
                SELECT bed_entity.id, bed_entity.name,
                       occupant.id AS occupant_id,
                       occupant.name AS occupant_name,
                       character.role AS occupant_role,
                       character.condition AS occupant_condition,
                       character.disposition AS occupant_disposition
                FROM beds b
                JOIN entities bed_entity ON bed_entity.id = b.entity_id
                LEFT JOIN entities occupant ON occupant.id = b.occupant_entity_id
                LEFT JOIN characters character ON character.entity_id = occupant.id
                WHERE b.location_id = ? AND bed_entity.world_id = ?
                ORDER BY bed_entity.id
                """,
                (location_id, world_id),
            )
        ]
        if not beds:
            raise WardCapabilityNotFound(
                f"Location {location_id!r} has no ward capability state"
            )
    return {
        "world_id": world_id,
        "location_id": location_id,
        "revision": location["revision"],
        "beds": beds,
        "bed_count": len(beds),
        "occupied_bed_count": sum(bed["occupant"] is not None for bed in beds),
    }


def get_ward_bed(
    database_path: str | Path, world_id: str, bed_id: str
) -> WardRecord | None:
    """Read ward-specific occupancy for one bed entity."""
    with connect_database(database_path) as connection:
        row = connection.execute(
            """
            SELECT e.id, e.world_id, e.name, b.location_id, b.occupant_entity_id
            FROM beds b
            JOIN entities e ON e.id = b.entity_id
            WHERE e.world_id = ? AND e.id = ?
            """,
            (world_id, bed_id),
        ).fetchone()
    return dict(row) if row is not None else None
