"""Compatibility imports for the original ward proof fixture.

New code should import from ``backend.scenarios.ward.seed``.
"""

from backend.scenarios.ward.seed import (
    PLAYER_ID,
    WARD_LOCATION_ID,
    WARD_WORLD_ID,
    seed_ward_world,
)

__all__ = ["PLAYER_ID", "WARD_LOCATION_ID", "WARD_WORLD_ID", "seed_ward_world"]
