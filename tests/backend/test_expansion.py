from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.world.expansion import (
    ExpansionConflict,
    ExpansionNotFound,
    propose_location_expansion,
)


def _world(tmp_path: Path) -> Path:
    path = tmp_path / "world.sqlite3"
    migrate_database(path)
    with connect_database(path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('world-a', 'World A')")
        connection.executemany(
            "INSERT INTO locations(id, world_id, name) VALUES (?, 'world-a', ?)",
            [("harbor", "Harbor"), ("city", "City")],
        )
        connection.commit()
    return path


def _world_with_actor_at_harbor(tmp_path: Path) -> Path:
    path = _world(tmp_path)
    with connect_database(path) as connection:
        connection.execute(
            "INSERT INTO entities(id, world_id, kind, name) "
            "VALUES ('sailor', 'world-a', 'character', 'Sailor')"
        )
        connection.execute(
            "INSERT INTO characters(entity_id, role, disposition) "
            "VALUES ('sailor', 'player', 'active')"
        )
        connection.execute(
            "INSERT INTO entity_locations(entity_id, location_id) VALUES ('sailor', 'harbor')"
        )
        connection.commit()
    return path


async def _request(app: Any, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/worlds/world-a/locations/expand", json=payload)
    return response.status_code, response.json()


def test_http_expansion_contract_is_revision_aware(tmp_path: Path) -> None:
    path = _world(tmp_path)
    status, body = asyncio.run(
        _request(
            create_app(path),
            {
                "proposal_id": "http-proposal-1",
                "location_id": "market",
                "anchor_location_id": "harbor",
                "name": "Market",
                "operation_id": "http-expand-1",
                "expected_revision": 0,
            },
        )
    )
    assert status == 200
    assert body["world_revision"] == 1


def test_http_expansion_accepts_orientation_metadata(tmp_path: Path) -> None:
    path = _world(tmp_path)
    status, body = asyncio.run(
        _request(
            create_app(path),
            {
                "proposal_id": "http-proposal-orient",
                "location_id": "orchard",
                "anchor_location_id": "harbor",
                "name": "Orchard Ford",
                "connect_to_anchor": True,
                "direction": "east",
                "range_band": "mid",
                "map_form": "forest",
                "operation_id": "http-expand-orient",
                "expected_revision": 0,
            },
        )
    )
    assert status == 200
    assert body["world_revision"] == 1
    with connect_database(path) as connection:
        row = connection.execute(
            "SELECT direction, range_band, map_form "
            "FROM location_metadata WHERE location_id = 'orchard'"
        ).fetchone()
    assert tuple(row) == ("east", "mid", "forest")


def test_expansion_creates_one_location_with_containment_and_link(tmp_path: Path) -> None:
    path = _world(tmp_path)

    result = propose_location_expansion(
        path,
        world_id="world-a",
        operation_id="expand-1",
        expected_revision=0,
        proposal_id="proposal-1",
        location_id="market",
        anchor_location_id="harbor",
        name="Market",
        description="A busy market square.",
        parent_location_id="city",
        connect_to_anchor=True,
    )

    assert result == {
        "already_applied": False,
        "location_id": "market",
        "proposal_id": "proposal-1",
        "world_id": "world-a",
        "world_revision": 1,
    }
    with connect_database(path) as connection:
        assert connection.execute(
            "SELECT name, description FROM locations WHERE id = 'market'"
        ).fetchone()[:]
        assert (
            connection.execute(
                "SELECT parent_location_id FROM location_containment "
                "WHERE child_location_id = 'market'"
            ).fetchone()[0]
            == "city"
        )
        assert connection.execute(
            "SELECT location_a, location_b FROM location_links "
            "WHERE location_a = 'harbor' OR location_b = 'harbor'"
        ).fetchone()[:] == ("harbor", "market")
        assert connection.execute(
            "SELECT proposal_id, location_id FROM world_expansion_proposals"
        ).fetchone()[:] == ("proposal-1", "market")


def test_expansion_replays_by_operation_and_rejects_duplicate_proposal(tmp_path: Path) -> None:
    path = _world(tmp_path)
    kwargs = {
        "world_id": "world-a",
        "operation_id": "expand-1",
        "expected_revision": 0,
        "proposal_id": "proposal-1",
        "location_id": "market",
        "anchor_location_id": "harbor",
        "name": "Market",
    }
    first = propose_location_expansion(path, **kwargs)
    replay = propose_location_expansion(path, **kwargs)
    assert first["world_revision"] == replay["world_revision"] == 1
    assert replay["already_applied"] is True

    with pytest.raises(ExpansionConflict, match="proposal ID"):
        propose_location_expansion(
            path,
            **{**kwargs, "operation_id": "expand-2", "expected_revision": 1},
        )


def test_expansion_rejects_foreign_actor(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with pytest.raises(ExpansionNotFound, match="actor"):
        propose_location_expansion(
            path,
            world_id="world-a",
            operation_id="actor-expand-1",
            expected_revision=0,
            proposal_id="actor-proposal-1",
            location_id="market",
            anchor_location_id="harbor",
            name="Market",
            actor_entity_id="missing",
        )


def test_expansion_rejects_duplicate_name_and_exhausts_budget(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with pytest.raises(ExpansionConflict, match="already exists"):
        propose_location_expansion(
            path,
            world_id="world-a",
            operation_id="expand-1",
            expected_revision=0,
            proposal_id="proposal-1",
            location_id="harbor-copy",
            anchor_location_id="harbor",
            name=" harbor ",
        )

    with connect_database(path) as connection:
        connection.execute(
            "INSERT INTO world_expansion_limits(world_id, max_locations) VALUES ('world-a', 0)"
        )
        connection.commit()
    with pytest.raises(ExpansionConflict, match="budget"):
        propose_location_expansion(
            path,
            world_id="world-a",
            operation_id="expand-2",
            expected_revision=0,
            proposal_id="proposal-2",
            location_id="market",
            anchor_location_id="harbor",
            name="Market",
        )


def test_expansion_persists_orientation_metadata(tmp_path: Path) -> None:
    path = _world(tmp_path)

    result = propose_location_expansion(
        path,
        world_id="world-a",
        operation_id="expand-orient-1",
        expected_revision=0,
        proposal_id="orient-proposal-1",
        location_id="orchard",
        anchor_location_id="harbor",
        name="Orchard Ford",
        connect_to_anchor=True,
        direction="east",
        range_band="mid",
        map_form="forest",
    )

    assert result["world_revision"] == 1
    with connect_database(path) as connection:
        row = connection.execute(
            "SELECT geography_role, direction, range_band, map_form "
            "FROM location_metadata WHERE location_id = 'orchard'"
        ).fetchone()
    assert tuple(row) == ("local", "east", "mid", "forest")


def test_expansion_rejects_invalid_orientation_metadata(tmp_path: Path) -> None:
    path = _world(tmp_path)
    base = {
        "world_id": "world-a",
        "operation_id": "expand-bad-1",
        "expected_revision": 0,
        "proposal_id": "bad-proposal-1",
        "location_id": "market",
        "anchor_location_id": "harbor",
        "name": "Market",
    }
    with pytest.raises(ExpansionConflict, match="direction"):
        propose_location_expansion(path, **{**base, "direction": "up"})
    with pytest.raises(ExpansionConflict, match="range band"):
        propose_location_expansion(path, **{**base, "range_band": "far"})
    with pytest.raises(ExpansionConflict, match="map form"):
        propose_location_expansion(path, **{**base, "map_form": "castle"})


def test_expansion_moves_actor_into_new_location_atomically(tmp_path: Path) -> None:
    path = _world_with_actor_at_harbor(tmp_path)

    result = propose_location_expansion(
        path,
        world_id="world-a",
        operation_id="expand-move-1",
        expected_revision=0,
        proposal_id="move-proposal-1",
        location_id="orchard",
        anchor_location_id="harbor",
        name="Orchard Ford",
        connect_to_anchor=True,
        actor_entity_id="sailor",
        direction="east",
        move_actor_to_location=True,
    )

    assert result["world_revision"] == 1
    with connect_database(path) as connection:
        location_id = connection.execute(
            "SELECT location_id FROM entity_locations WHERE entity_id = 'sailor'"
        ).fetchone()[0]
        assert location_id == "orchard"


def test_expansion_move_requires_connect_and_anchor_presence(tmp_path: Path) -> None:
    path = _world_with_actor_at_harbor(tmp_path)
    base = {
        "world_id": "world-a",
        "operation_id": "expand-move-2",
        "expected_revision": 0,
        "proposal_id": "move-proposal-2",
        "location_id": "orchard",
        "anchor_location_id": "harbor",
        "name": "Orchard Ford",
        "actor_entity_id": "sailor",
        "move_actor_to_location": True,
    }
    with pytest.raises(ExpansionConflict, match="connect_to_anchor"):
        propose_location_expansion(path, **base)
    with pytest.raises(ExpansionConflict, match="actor_entity_id"):
        propose_location_expansion(
            path, **{**base, "connect_to_anchor": True, "actor_entity_id": None}
        )
    with pytest.raises(ExpansionConflict, match="not at the anchor"):
        with connect_database(path) as connection:
            connection.execute(
                "UPDATE entity_locations SET location_id = 'city' WHERE entity_id = 'sailor'"
            )
            connection.commit()
        propose_location_expansion(path, **{**base, "connect_to_anchor": True})
