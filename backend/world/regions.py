"""Play-side world region framework reads.

World regions are the per-world copy of a scenario's region hierarchy
(kingdoms -> provinces -> cities, or whatever levels the scenario uses).
Regions are knowledge, not playable nodes; ``location_id`` binds a region to
the location the narrator materialized for it. These reads expose the region
chain for a location and the full framework for route validation.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_readonly_database


def _region_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "region_id": row["region_id"],
        "parent_region_id": row["parent_region_id"],
        "level": row["level"],
        "title": row["title"],
        "description": row["description"],
        "attributes": json.loads(row["attributes_json"]),
        "location_id": row["location_id"],
    }


def read_world_regions(
    database_path: str | Path,
    *,
    world_id: str,
    _connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return the world's full region framework, ordered by region_id."""
    context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with context as connection:
        rows = connection.execute(
            "SELECT region_id, parent_region_id, level, title, description, "
            "attributes_json, location_id FROM world_regions "
            "WHERE world_id = ? ORDER BY region_id",
            (world_id,),
        ).fetchall()
    return [_region_row_to_dict(row) for row in rows]


def resolve_region_chain(
    database_path: str | Path,
    *,
    world_id: str,
    location_id: str,
    _connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Resolve the region chain containing ``location_id``.

    Walks containment ancestors from the location upward until it finds a
    location bound to a region (``world_regions.location_id``), then returns
    that region and all of its ancestors (city -> province -> kingdom). Returns
    ``[]`` when the location is not inside any bound region.
    """
    context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with context as connection:
        chain: list[dict[str, Any]] = []
        current_id = location_id
        depth = 0
        while current_id is not None and depth <= 1000:
            bound = connection.execute(
                "SELECT region_id, parent_region_id, level, title, description, "
                "attributes_json, location_id FROM world_regions "
                "WHERE world_id = ? AND location_id = ?",
                (world_id, current_id),
            ).fetchone()
            if bound is not None:
                # Walk the region's own parent chain (region -> region).
                region = dict(bound)
                chain.append(_region_row_to_dict(bound))
                parent_id = region["parent_region_id"]
                region_depth = 0
                while parent_id is not None and region_depth <= 1000:
                    parent = connection.execute(
                        "SELECT region_id, parent_region_id, level, title, "
                        "description, attributes_json, location_id "
                        "FROM world_regions "
                        "WHERE world_id = ? AND region_id = ?",
                        (world_id, parent_id),
                    ).fetchone()
                    if parent is None:
                        break
                    chain.append(_region_row_to_dict(parent))
                    parent_id = parent["parent_region_id"]
                    region_depth += 1
                break
            row = connection.execute(
                "SELECT parent_location_id FROM location_containment "
                "WHERE world_id = ? AND child_location_id = ?",
                (world_id, current_id),
            ).fetchone()
            if row is None:
                break
            current_id = row["parent_location_id"]
            depth += 1
    return chain
