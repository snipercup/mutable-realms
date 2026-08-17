from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.world.routes import (
    RouteConflict,
    RouteNotFound,
    create_route,
    travel_entity_route,
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
        connection.execute(
            "INSERT INTO entities(id, world_id, kind, name) "
            "VALUES ('player', 'world-a', 'character', 'Player')"
        )
        connection.execute("INSERT INTO characters(entity_id, role) VALUES ('player', 'traveler')")
        connection.execute(
            "INSERT INTO entity_locations(entity_id, location_id) VALUES ('player', 'harbor')"
        )
        connection.commit()
    return path


async def _request(
    app: Any, method: str, path: str, json: dict[str, object]
) -> tuple[int, dict[str, object]]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.request(method, path, json=json)
    return response.status_code, response.json()


def test_http_route_definition_and_travel_are_explicit(tmp_path: Path) -> None:
    path = _world(tmp_path)
    app = create_app(path)
    status, route_body = asyncio.run(
        _request(
            app,
            "PUT",
            "/api/worlds/world-a/routes/harbor-road",
            {
                "route_id": "harbor-road",
                "origin_location_id": "harbor",
                "destination_location_id": "city",
                "name": "Old Road",
                "route_kind": "road",
                "operation_id": "http-route-1",
                "expected_revision": 0,
            },
        )
    )
    assert status == 200
    assert route_body["world_revision"] == 1
    status, travel_body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds/world-a/route-travel",
            {
                "route_id": "harbor-road",
                "entity_id": "player",
                "actor_entity_id": "player",
                "operation_id": "http-travel-1",
                "expected_revision": 1,
            },
        )
    )
    assert status == 200
    assert travel_body["location_id"] == "city"
    status, replay_body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/worlds/world-a/route-travel",
            {
                "route_id": "harbor-road",
                "entity_id": "player",
                "actor_entity_id": "player",
                "operation_id": "http-travel-1",
                "expected_revision": 1,
            },
        )
    )
    assert status == 200
    assert replay_body["already_applied"] is True
    assert replay_body["world_revision"] == 2


def test_route_travel_moves_exact_endpoint_without_local_link(tmp_path: Path) -> None:
    path = _world(tmp_path)
    created = create_route(
        path,
        world_id="world-a",
        route_id="harbor-road",
        operation_id="route-create-1",
        expected_revision=0,
        origin_location_id="harbor",
        destination_location_id="city",
        name="Old Road",
        route_kind="road",
    )

    result = travel_entity_route(
        path,
        world_id="world-a",
        route_id="harbor-road",
        operation_id="route-travel-1",
        expected_revision=created["world_revision"],
        entity_id="player",
        actor_entity_id="player",
    )

    assert result["location_id"] == "city"
    assert result["route_id"] == "harbor-road"
    with connect_database(path) as connection:
        assert (
            connection.execute("SELECT 1 FROM location_links WHERE world_id = 'world-a'").fetchone()
            is None
        )
        assert (
            connection.execute(
                "SELECT location_id FROM entity_locations WHERE entity_id = 'player'"
            ).fetchone()[0]
            == "city"
        )


def test_route_travel_requires_exact_origin_and_active_route(tmp_path: Path) -> None:
    path = _world(tmp_path)
    create_route(
        path,
        world_id="world-a",
        route_id="inactive-road",
        operation_id="inactive-create-1",
        expected_revision=0,
        origin_location_id="harbor",
        destination_location_id="city",
        name="Closed Road",
        is_active=False,
    )
    with pytest.raises(RouteConflict, match="inactive"):
        travel_entity_route(
            path,
            world_id="world-a",
            route_id="inactive-road",
            operation_id="inactive-travel-1",
            expected_revision=1,
            entity_id="player",
            actor_entity_id="player",
        )

    create_route(
        path,
        world_id="world-a",
        route_id="city-road",
        operation_id="route-create-2",
        expected_revision=1,
        origin_location_id="city",
        destination_location_id="harbor",
        name="Reverse Road",
    )
    with pytest.raises(RouteConflict, match="route origin"):
        travel_entity_route(
            path,
            world_id="world-a",
            route_id="city-road",
            operation_id="wrong-origin-1",
            expected_revision=2,
            entity_id="player",
            actor_entity_id="player",
        )


def test_route_travel_rejects_discharged_character(tmp_path: Path) -> None:
    path = _world(tmp_path)
    create_route(
        path,
        world_id="world-a",
        route_id="harbor-road",
        operation_id="route-create-1",
        expected_revision=0,
        origin_location_id="harbor",
        destination_location_id="city",
        name="Old Road",
    )
    with connect_database(path) as connection:
        connection.execute(
            "UPDATE characters SET disposition = 'discharged' WHERE entity_id = 'player'"
        )
        connection.commit()
    with pytest.raises(RouteConflict, match="discharged character"):
        travel_entity_route(
            path,
            world_id="world-a",
            route_id="harbor-road",
            operation_id="discharged-travel-1",
            expected_revision=1,
            entity_id="player",
            actor_entity_id="player",
        )


def test_route_create_rejects_foreign_or_missing_endpoint(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with pytest.raises(RouteNotFound, match="location"):
        create_route(
            path,
            world_id="world-a",
            route_id="bad-route",
            operation_id="route-create-1",
            expected_revision=0,
            origin_location_id="harbor",
            destination_location_id="missing",
            name="Bad Route",
        )
