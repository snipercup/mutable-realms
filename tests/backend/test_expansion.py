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
