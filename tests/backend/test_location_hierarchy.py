from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.world.hierarchy import (
    read_location_ancestors,
    read_location_children,
    read_location_descendants,
    set_location_hierarchy,
)
from backend.world.validation import validate_worlds
from backend.world.worlds import WorldAdminConflict


def _world(tmp_path: Path) -> Path:
    path = tmp_path / "world.sqlite3"
    migrate_database(path)
    with connect_database(path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('world-a', 'World A')")
        connection.executemany(
            "INSERT INTO locations(id, world_id, name, description) VALUES (?, 'world-a', ?, '')",
            [
                ("city", "City"),
                ("district", "District"),
                ("street", "Street"),
                ("house", "House"),
            ],
        )
        connection.commit()
    return path


def test_configures_hierarchy_atomically_and_replays_exact_request(tmp_path: Path) -> None:
    path = _world(tmp_path)

    first = set_location_hierarchy(
        path,
        world_id="world-a",
        operation_id="hierarchy-1",
        expected_revision=0,
        location_id="street",
        parent_location_id="district",
        kind="street",
        is_map_scope=True,
        is_default_scope=True,
    )
    replay = set_location_hierarchy(
        path,
        world_id="world-a",
        operation_id="hierarchy-1",
        expected_revision=0,
        location_id="street",
        parent_location_id="district",
        kind="street",
        is_map_scope=True,
        is_default_scope=True,
    )

    assert first == {
        "already_applied": False,
        "world_id": "world-a",
        "world_revision": 1,
        "location_id": "street",
    }
    assert replay == {**first, "already_applied": True}
    with connect_database(path) as connection:
        assert tuple(
            connection.execute(
                "SELECT parent_location_id FROM location_containment "
                "WHERE world_id = 'world-a' AND child_location_id = 'street'"
            ).fetchone()
        ) == ("district",)
        assert tuple(
            connection.execute(
                "SELECT kind, is_map_scope, is_default_scope FROM location_metadata "
                "WHERE world_id = 'world-a' AND location_id = 'street'"
            ).fetchone()
        ) == ("street", 1, 1)
        assert (
            connection.execute("SELECT revision FROM worlds WHERE id = 'world-a'").fetchone()[0]
            == 1
        )


def test_rejects_cross_world_parent_and_containment_cycle_without_mutation(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with connect_database(path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('world-b', 'World B')")
        connection.execute(
            "INSERT INTO locations(id, world_id, name, description) "
            "VALUES ('foreign', 'world-b', 'Foreign', '')"
        )
        connection.commit()

    with pytest.raises(WorldAdminConflict, match="parent location not found"):
        set_location_hierarchy(
            path,
            world_id="world-a",
            operation_id="foreign-parent",
            expected_revision=0,
            location_id="city",
            parent_location_id="foreign",
        )

    set_location_hierarchy(
        path,
        world_id="world-a",
        operation_id="district-parent",
        expected_revision=0,
        location_id="district",
        parent_location_id="city",
    )
    with pytest.raises(WorldAdminConflict, match="cycle"):
        set_location_hierarchy(
            path,
            world_id="world-a",
            operation_id="city-parent",
            expected_revision=1,
            location_id="city",
            parent_location_id="district",
        )

    with connect_database(path) as connection:
        assert (
            connection.execute("SELECT revision FROM worlds WHERE id = 'world-a'").fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT 1 FROM location_containment WHERE child_location_id = 'city'"
            ).fetchone()
            is None
        )


def test_reads_ordered_ancestors_and_direct_children(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with connect_database(path) as connection:
        connection.executemany(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES ('world-a', ?, ?)",
            [("district", "city"), ("street", "district"), ("house", "street")],
        )
        connection.executemany(
            "INSERT INTO location_metadata("
            "world_id, location_id, kind, is_map_scope, is_default_scope) "
            "VALUES ('world-a', ?, ?, ?, ?)",
            [("city", "city", 1, 0), ("district", "district", 1, 0), ("street", "street", 1, 1)],
        )
        connection.commit()

    assert [
        item["id"]
        for item in read_location_ancestors(path, world_id="world-a", location_id="house")
    ] == [
        "city",
        "district",
        "street",
    ]
    children = read_location_children(
        path, world_id="world-a", parent_location_id="street", limit=100
    )
    assert children["total"] == 1
    assert children["has_more"] is False
    assert children["locations"][0]["id"] == "house"


def test_reads_bounded_descendants_and_reports_overflow(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with connect_database(path) as connection:
        connection.executemany(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES ('world-a', ?, ?)",
            [("district", "city"), ("street", "district"), ("house", "street")],
        )
        connection.commit()

    descendants = read_location_descendants(path, world_id="world-a", location_id="city", limit=2)

    assert [item["id"] for item in descendants["locations"]] == ["district", "street"]
    assert descendants["has_more"] is True


async def _request(app: object, method: str, path: str, json: dict[str, object]):
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.request(method, path, json=json)
    return response.status_code, response.json()


def test_http_configures_location_hierarchy(tmp_path: Path) -> None:
    path = _world(tmp_path)
    app = create_app(path)

    status, body = asyncio.run(
        _request(
            app,
            "PUT",
            "/api/worlds/world-a/locations/street/hierarchy",
            {
                "operation_id": "http-hierarchy-1",
                "expected_revision": 0,
                "parent_location_id": "district",
                "kind": "street",
                "is_map_scope": True,
                "is_default_scope": True,
            },
        )
    )

    assert status == 200
    assert body == {
        "already_applied": False,
        "location_id": "street",
        "world_id": "world-a",
        "world_revision": 1,
    }


def test_whole_world_validation_detects_containment_cycle(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with connect_database(path) as connection:
        connection.executemany(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES ('world-a', ?, ?)",
            [("city", "district"), ("district", "city")],
        )
        connection.commit()

    issues = validate_worlds(path)

    assert [
        (issue.code, issue.entity_id)
        for issue in issues
        if issue.code == "location_containment_cycle"
    ] == [
        ("location_containment_cycle", "city"),
        ("location_containment_cycle", "district"),
    ]
