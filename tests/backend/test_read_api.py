from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.town.seed import TOWN_WORLD_ID, seed_town_world
from backend.scenarios.ward.mutations import treat_and_discharge_patient
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from tests.backend.general_world import GENERAL_WORLD_ID, seed_general_world


def _seeded_app(tmp_path: Path) -> tuple[Any, Path]:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    seed_general_world(database_path)
    return create_app(database_path), database_path


async def _get(app: Any, path: str) -> tuple[int, Any]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path)
    return response.status_code, response.json()


async def _get_text(app: Any, path: str) -> tuple[int, str]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path)
    return response.status_code, response.text


def test_read_api_exposes_world_map_with_links_and_entity_kinds(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_town_world(database_path)
    app = create_app(database_path)

    status, world_map = asyncio.run(_get(app, f"/api/worlds/{TOWN_WORLD_ID}/map"))

    assert status == 200
    assert world_map["world"]["id"] == TOWN_WORLD_ID
    assert world_map["player_location_id"] == "plaza"
    by_id = {loc["id"]: loc for loc in world_map["locations"]}
    assert set(by_id) == {"plaza", "market", "tavern", "docks"}
    assert by_id["plaza"]["linked_location_ids"] == ["market", "tavern"]
    assert by_id["market"]["linked_location_ids"] == ["docks", "plaza"]
    assert by_id["plaza"]["entity_kinds"] == {"character": 1}
    assert by_id["market"]["entity_kinds"] == {"character": 1, "item": 1}


def test_read_api_map_renders_one_scope_and_reports_boundary_exits(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_town_world(database_path)
    with connect_database(database_path) as connection:
        connection.executemany(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES (?, ?, ?)",
            [
                (TOWN_WORLD_ID, "market", "plaza"),
                (TOWN_WORLD_ID, "tavern", "plaza"),
                (TOWN_WORLD_ID, "docks", "market"),
            ],
        )
        connection.execute(
            "INSERT INTO location_metadata("
            "world_id, location_id, kind, is_map_scope, is_default_scope) "
            "VALUES (?, 'plaza', 'street', 1, 1)",
            (TOWN_WORLD_ID,),
        )
        connection.commit()
    app = create_app(database_path)

    status, world_map = asyncio.run(
        _get(app, f"/api/worlds/{TOWN_WORLD_ID}/map?scope_location_id=plaza")
    )

    assert status == 200
    assert world_map["scope_location"]["id"] == "plaza"
    assert world_map["breadcrumbs"] == []
    assert world_map["player_location_id"] == "plaza"
    assert world_map["player_visible_location_id"] == "plaza"
    assert world_map["child_total"] == 2
    assert world_map["has_more"] is False
    assert [location["id"] for location in world_map["locations"]] == ["market", "plaza", "tavern"]
    assert world_map["boundary_links"] == [
        {
            "from_location_id": "market",
            "to_location_id": "docks",
            "to_location_name": "Harbor Docks",
        },
        {
            "from_location_id": "tavern",
            "to_location_id": "docks",
            "to_location_name": "Harbor Docks",
        },
    ]


def test_read_api_map_includes_explicit_promoted_landmark(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_town_world(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES (?, 'market', 'plaza')",
            (TOWN_WORLD_ID,),
        )
        connection.execute(
            "INSERT INTO location_metadata("
            "world_id, location_id, kind, is_map_scope, is_default_scope) "
            "VALUES (?, 'plaza', 'province', 1, 1)",
            (TOWN_WORLD_ID,),
        )
        connection.execute(
            "INSERT INTO location_scope_promotions(world_id, scope_location_id, location_id) "
            "VALUES (?, 'plaza', 'docks')",
            (TOWN_WORLD_ID,),
        )
        connection.commit()
    app = create_app(database_path)

    status, world_map = asyncio.run(
        _get(app, f"/api/worlds/{TOWN_WORLD_ID}/map?scope_location_id=plaza")
    )

    assert status == 200
    assert world_map["child_total"] == 2
    docks = next(location for location in world_map["locations"] if location["id"] == "docks")
    assert docks["is_promoted"] is True
    assert docks["linked_location_ids"] == ["market"]


def test_read_api_map_uses_nearest_default_scope_for_player(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_town_world(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES (?, 'plaza', 'market')",
            (TOWN_WORLD_ID,),
        )
        connection.execute(
            "INSERT INTO location_metadata("
            "world_id, location_id, kind, is_map_scope, is_default_scope) "
            "VALUES (?, 'market', 'street', 1, 1)",
            (TOWN_WORLD_ID,),
        )
        connection.commit()
    app = create_app(database_path)

    status, world_map = asyncio.run(_get(app, f"/api/worlds/{TOWN_WORLD_ID}/map"))

    assert status == 200
    assert world_map["scope_location"]["id"] == "market"
    assert world_map["player_location_id"] == "plaza"
    assert world_map["player_visible_location_id"] == "plaza"


def test_read_api_map_renders_world_without_links(tmp_path: Path) -> None:
    app, _ = _seeded_app(tmp_path)

    status, world_map = asyncio.run(_get(app, f"/api/worlds/{GENERAL_WORLD_ID}/map"))

    assert status == 200
    assert world_map["player_location_id"] == "ocean-farm"
    assert all(loc["linked_location_ids"] == [] for loc in world_map["locations"])


def test_read_api_map_reports_missing_world(tmp_path: Path) -> None:
    app, _ = _seeded_app(tmp_path)

    status, _ = asyncio.run(_get(app, "/api/worlds/no-such-world/map"))

    assert status == 404


def test_read_api_exposes_player_current_location_and_entity(tmp_path: Path) -> None:
    app, _ = _seeded_app(tmp_path)

    player_status, player = asyncio.run(_get(app, f"/api/worlds/{WARD_WORLD_ID}/player"))
    location_status, location = asyncio.run(
        _get(app, f"/api/worlds/{WARD_WORLD_ID}/locations/current")
    )
    entity_status, entity = asyncio.run(
        _get(app, f"/api/worlds/{WARD_WORLD_ID}/entities/patient-1")
    )

    assert player_status == 200
    assert player["id"] == "player"
    assert player["location_id"] == "ward"
    assert location_status == 200
    assert "beds" not in location
    assert len(location["entities"]) == 13
    assert entity_status == 200
    assert entity["condition"] == "untreated"


def test_read_api_lists_and_reads_a_world_without_ward_state(tmp_path: Path) -> None:
    app, _ = _seeded_app(tmp_path)

    worlds_status, worlds = asyncio.run(_get(app, "/api/worlds"))
    location_status, location = asyncio.run(
        _get(app, f"/api/worlds/{GENERAL_WORLD_ID}/locations/current")
    )

    assert worlds_status == 200
    assert [world["id"] for world in worlds] == [GENERAL_WORLD_ID, WARD_WORLD_ID]
    assert location_status == 200
    assert location["id"] == "ocean-farm"
    assert {entity["kind"] for entity in location["entities"]} == {
        "animal",
        "character",
        "item",
    }
    assert "beds" not in location

    ward_status, ward = asyncio.run(
        _get(
            app,
            f"/api/worlds/{GENERAL_WORLD_ID}/capabilities/ward/locations/ocean-farm",
        )
    )
    assert ward_status == 404
    assert ward == {"detail": "ward capability not found"}


def test_read_api_exposes_named_location_and_recent_events(tmp_path: Path) -> None:
    app, database_path = _seeded_app(tmp_path)
    treat_and_discharge_patient(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="operation-1",
        expected_revision=0,
        patient_id="patient-1",
        bed_id="bed-1",
    )

    location_status, location = asyncio.run(
        _get(app, f"/api/worlds/{WARD_WORLD_ID}/locations/ward")
    )
    ward_status, ward = asyncio.run(
        _get(
            app,
            f"/api/worlds/{WARD_WORLD_ID}/capabilities/ward/locations/ward",
        )
    )
    events_status, events = asyncio.run(_get(app, f"/api/worlds/{WARD_WORLD_ID}/events?limit=1"))

    assert location_status == 200
    assert location["revision"] == 1
    assert "beds" not in location
    assert ward_status == 200
    assert ward["occupied_bed_count"] == 5
    assert ward["beds"][0]["occupant"] is None
    assert events_status == 200
    assert len(events) == 1
    assert events[0]["event_type"] == "patient_treated_and_discharged"


def test_read_api_returns_404_for_missing_resources(tmp_path: Path) -> None:
    app, _ = _seeded_app(tmp_path)

    player_status, player = asyncio.run(_get(app, "/api/worlds/missing/player"))
    location_status, location = asyncio.run(
        _get(app, f"/api/worlds/{WARD_WORLD_ID}/locations/missing")
    )
    entity_status, entity = asyncio.run(_get(app, f"/api/worlds/{WARD_WORLD_ID}/entities/missing"))
    events_status, events = asyncio.run(_get(app, "/api/worlds/missing/events"))

    assert player_status == 404
    assert player == {"detail": "player not found"}
    assert location_status == 404
    assert location == {"detail": "location not found"}
    assert entity_status == 404
    assert entity == {"detail": "entity not found"}
    assert events_status == 404
    assert events == {"detail": "world not found"}


def test_events_limit_is_bounded_by_api_validation(tmp_path: Path) -> None:
    app, _ = _seeded_app(tmp_path)

    zero_status, _ = asyncio.run(_get(app, f"/api/worlds/{WARD_WORLD_ID}/events?limit=0"))
    excessive_status, _ = asyncio.run(_get(app, f"/api/worlds/{WARD_WORLD_ID}/events?limit=101"))

    assert zero_status == 422
    assert excessive_status == 422


def test_openapi_documents_read_routes(tmp_path: Path) -> None:
    app, _ = _seeded_app(tmp_path)

    status, schema = asyncio.run(_get(app, "/openapi.json"))

    assert status == 200
    assert "/api/worlds/{world_id}/player" in schema["paths"]
    assert "/api/worlds/{world_id}/locations/current" in schema["paths"]
    assert "/api/worlds/{world_id}/locations/{location_id}" in schema["paths"]
    assert "/api/worlds/{world_id}/entities/{entity_id}" in schema["paths"]
    assert "/api/worlds/{world_id}/events" in schema["paths"]
    assert "/api/worlds" in schema["paths"]
    assert "/api/worlds/{world_id}/capabilities/ward/locations/{location_id}" in schema["paths"]
    player_schema = schema["paths"]["/api/worlds/{world_id}/player"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    location_schema = schema["paths"]["/api/worlds/{world_id}/locations/{location_id}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert player_schema["$ref"].endswith("/PlayerRead")
    assert location_schema["$ref"].endswith("/LocationRead")


def test_application_serves_built_frontend_when_available(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    frontend_path = tmp_path / "frontend"
    frontend_path.mkdir()
    (frontend_path / "index.html").write_text(
        "<!doctype html><title>Authoritative ward</title>", encoding="utf-8"
    )
    app = create_app(database_path, frontend_path=frontend_path)

    status, body = asyncio.run(_get_text(app, "/"))

    assert status == 200
    assert "Authoritative ward" in body
