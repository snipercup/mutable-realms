from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.cli import main
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.world.scenarios import (
    ScenarioConflict,
    ScenarioNotFound,
    create_scenario,
    list_scenarios,
    read_scenario,
    remove_scenario,
    remove_scenario_region,
    set_scenario_element,
    set_scenario_region,
    update_scenario,
)


def _database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    return database_path


def _create(
    database_path: Path,
    *,
    scenario_id: str = "aerthalon",
    operation_id: str = "scenario-create-1",
    title: str = "Aerthalon",
    description: str | None = "A vast ancient fantasy world.",
) -> dict[str, Any]:
    return create_scenario(
        database_path,
        scenario_id=scenario_id,
        operation_id=operation_id,
        title=title,
        description=description,
    )


def _element_count(database_path: Path, scenario_id: str) -> int:
    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM scenario_elements WHERE scenario_id = ?",
            (scenario_id,),
        ).fetchone()
    return row["count"]


def _operation_count(database_path: Path, scenario_id: str) -> int:
    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM scenario_operations WHERE scenario_id = ?",
            (scenario_id,),
        ).fetchone()
    return row["count"]


# --- service: create -------------------------------------------------------


def test_create_scenario_persists_title_and_description(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    result = _create(database_path)

    assert result["already_applied"] is False
    assert result["scenario_id"] == "aerthalon"
    scenario = read_scenario(database_path, "aerthalon")
    assert scenario["title"] == "Aerthalon"
    assert scenario["description"] == "A vast ancient fantasy world."
    assert scenario["elements"] == []


def test_create_scenario_replays_exact_request(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    first = _create(database_path)
    second = _create(database_path)

    assert first["already_applied"] is False
    assert second["already_applied"] is True
    assert second["scenario_id"] == "aerthalon"
    assert len(list_scenarios(database_path)) == 1


def test_create_scenario_conflicts_on_duplicate_id(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    with pytest.raises(ScenarioConflict, match="already exists"):
        _create(database_path, operation_id="scenario-create-2")


def test_create_scenario_conflicts_on_operation_reuse(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    with pytest.raises(ScenarioConflict, match="different request"):
        _create(database_path, title="Different title")


def test_create_scenario_rejects_invalid_id_and_blank_title(tmp_path: Path) -> None:
    database_path = _database(tmp_path)

    with pytest.raises(ScenarioConflict, match="kebab-case"):
        _create(database_path, scenario_id="Not Kebab!")
    with pytest.raises(ScenarioConflict, match="title must not be blank"):
        _create(database_path, operation_id="scenario-create-3", title="   ")


# --- service: update -------------------------------------------------------


def test_update_scenario_sets_title_and_description(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    result = update_scenario(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-update-1",
        title="Aerthalon Reborn",
        description=None,
    )

    assert result["already_applied"] is False
    scenario = read_scenario(database_path, "aerthalon")
    assert scenario["title"] == "Aerthalon Reborn"
    assert scenario["description"] == "A vast ancient fantasy world."


def test_update_scenario_requires_a_field(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    with pytest.raises(ScenarioConflict, match="title or description"):
        update_scenario(
            database_path,
            scenario_id="aerthalon",
            operation_id="scenario-update-2",
        )


def test_update_scenario_missing_scenario_raises_not_found(tmp_path: Path) -> None:
    database_path = _database(tmp_path)

    with pytest.raises(ScenarioNotFound):
        update_scenario(
            database_path,
            scenario_id="missing",
            operation_id="scenario-update-3",
            title="New title",
        )


def test_update_scenario_replays_exact_request(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    first = update_scenario(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-update-4",
        title="Renamed",
    )
    second = update_scenario(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-update-4",
        title="Renamed",
    )
    assert first["already_applied"] is False
    assert second["already_applied"] is True
    assert read_scenario(database_path, "aerthalon")["title"] == "Renamed"


# --- service: elements -----------------------------------------------------


def test_set_scenario_element_upserts_all_three_types(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    for index, element_type in enumerate(
        ("ai_instructions", "author_note", "plot_essentials", "opening_scene")
    ):
        set_scenario_element(
            database_path,
            scenario_id="aerthalon",
            operation_id=f"scenario-element-{index + 1}",
            element_type=element_type,
            content=f"Content for {element_type}.",
        )

    scenario = read_scenario(database_path, "aerthalon")
    assert [element["element_type"] for element in scenario["elements"]] == [
        "ai_instructions",
        "author_note",
        "opening_scene",
        "plot_essentials",
    ]
    assert _element_count(database_path, "aerthalon") == 4

    set_scenario_element(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-element-5",
        element_type="author_note",
        content="Updated author note.",
    )
    assert _element_count(database_path, "aerthalon") == 4
    scenario = read_scenario(database_path, "aerthalon")
    author_note = next(
        element for element in scenario["elements"] if element["element_type"] == "author_note"
    )
    assert author_note["content"] == "Updated author note."


def test_set_scenario_element_validates_type_and_content(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    with pytest.raises(ScenarioConflict, match="element type"):
        set_scenario_element(
            database_path,
            scenario_id="aerthalon",
            operation_id="scenario-element-5",
            element_type="character_sheet",
            content="nope",
        )
    with pytest.raises(ScenarioConflict, match="must not be blank"):
        set_scenario_element(
            database_path,
            scenario_id="aerthalon",
            operation_id="scenario-element-6",
            element_type="author_note",
            content="   ",
        )
    with pytest.raises(ScenarioConflict, match="at most 20000"):
        set_scenario_element(
            database_path,
            scenario_id="aerthalon",
            operation_id="scenario-element-7",
            element_type="author_note",
            content="x" * 20_001,
        )


def test_set_scenario_element_missing_scenario_raises_not_found(tmp_path: Path) -> None:
    database_path = _database(tmp_path)

    with pytest.raises(ScenarioNotFound):
        set_scenario_element(
            database_path,
            scenario_id="missing",
            operation_id="scenario-element-8",
            element_type="author_note",
            content="content",
        )


def test_scenario_element_replays_exact_request(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    first = set_scenario_element(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-element-9",
        element_type="opening_scene",
        content="You arrive at the gates.",
    )
    second = set_scenario_element(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-element-9",
        element_type="opening_scene",
        content="You arrive at the gates.",
    )
    assert first["already_applied"] is False
    assert second["already_applied"] is True


# --- service: remove -------------------------------------------------------


def test_remove_scenario_cascades_elements_and_operations(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)
    set_scenario_element(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-element-10",
        element_type="author_note",
        content="Note.",
    )
    assert _operation_count(database_path, "aerthalon") == 2

    result = remove_scenario(
        database_path, scenario_id="aerthalon", operation_id="scenario-remove-1"
    )

    assert result["removed"] is True
    assert list_scenarios(database_path) == []
    assert _element_count(database_path, "aerthalon") == 0
    assert _operation_count(database_path, "aerthalon") == 0
    with pytest.raises(ScenarioNotFound):
        read_scenario(database_path, "aerthalon")


def test_remove_scenario_missing_raises_not_found(tmp_path: Path) -> None:
    database_path = _database(tmp_path)

    with pytest.raises(ScenarioNotFound):
        remove_scenario(
            database_path, scenario_id="missing", operation_id="scenario-remove-2"
        )


# --- CLI -------------------------------------------------------------------


def test_cli_scenario_roundtrip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = _database(tmp_path)
    db_args = ["--db-path", str(database_path)]

    assert main([*db_args, "create-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-1", "--title", "Aerthalon",
                 "--description", "A world."]) == 0
    assert main([*db_args, "set-scenario-element", "--scenario-id", "aerthalon",
                 "--operation-id", "op-2", "--element-type", "opening_scene",
                 "--content", "You arrive at the gates."]) == 0
    assert main([*db_args, "update-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-3", "--title", "Aerthalon Reborn"]) == 0
    assert main([*db_args, "create-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-1", "--title", "Aerthalon",
                 "--description", "A world."]) == 0
    captured = capsys.readouterr()
    assert '"already_applied": true' in captured.out
    assert '"removed"' not in captured.out

    assert main([*db_args, "remove-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-4"]) == 0
    captured = capsys.readouterr()
    assert '"removed": true' in captured.out


def test_cli_scenario_conflict_fails_with_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = _database(tmp_path)
    db_args = ["--db-path", str(database_path)]
    assert main([*db_args, "create-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-1", "--title", "Aerthalon"]) == 0
    capsys.readouterr()

    assert main([*db_args, "create-scenario", "--scenario-id", "aerthalon",
                 "--operation-id", "op-2", "--title", "Aerthalon"]) == 2
    captured = capsys.readouterr()
    assert "scenario already exists" in captured.err


# --- HTTP API --------------------------------------------------------------


async def _request(
    app: Any, method: str, path: str, **kwargs: Any
) -> tuple[int, Any]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.request(method, path, **kwargs)
    return response.status_code, response.json()


def test_scenario_api_full_roundtrip(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    app = create_app(database_path)

    status, body = asyncio.run(
        _request(
            app,
            "POST",
            "/api/scenarios",
            json={
                "scenario_id": "aerthalon",
                "title": "Aerthalon",
                "description": "A vast ancient fantasy world.",
                "operation_id": "api-create-1",
            },
        )
    )
    assert status == 201
    assert body["scenario_id"] == "aerthalon"

    status, _ = asyncio.run(
        _request(
            app,
            "PUT",
            "/api/scenarios/aerthalon/elements/opening_scene",
            json={"content": "You arrive at the gates.", "operation_id": "api-element-1"},
        )
    )
    assert status == 200

    status, body = asyncio.run(_request(app, "GET", "/api/scenarios"))
    assert status == 200
    assert [scenario["id"] for scenario in body] == ["aerthalon"]

    status, body = asyncio.run(_request(app, "GET", "/api/scenarios/aerthalon"))
    assert status == 200
    assert body["title"] == "Aerthalon"
    assert body["elements"][0]["element_type"] == "opening_scene"

    status, _ = asyncio.run(
        _request(
            app,
            "PATCH",
            "/api/scenarios/aerthalon",
            json={"title": "Aerthalon Reborn", "operation_id": "api-update-1"},
        )
    )
    assert status == 200

    status, _ = asyncio.run(
        _request(app, "DELETE", "/api/scenarios/aerthalon?operation_id=api-remove-1")
    )
    assert status == 200

    status, _ = asyncio.run(_request(app, "GET", "/api/scenarios/aerthalon"))
    assert status == 404


def test_scenario_api_conflict_returns_409(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    app = create_app(database_path)
    payload = {
        "scenario_id": "aerthalon",
        "title": "Aerthalon",
        "operation_id": "api-create-2",
    }
    assert asyncio.run(_request(app, "POST", "/api/scenarios", json=payload))[0] == 201

    conflicting = {**payload, "operation_id": "api-create-3"}
    status, body = asyncio.run(_request(app, "POST", "/api/scenarios", json=conflicting))
    assert status == 409
    assert "already exists" in body["detail"]

    # The exact same request is an idempotent replay, not a conflict.
    status, body = asyncio.run(_request(app, "POST", "/api/scenarios", json=payload))
    assert status == 201
    assert body["already_applied"] is True


def test_scenario_api_missing_returns_404(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    app = create_app(database_path)

    status, _ = asyncio.run(_request(app, "GET", "/api/scenarios/missing"))
    assert status == 404
    status, _ = asyncio.run(
        _request(
            app,
            "PATCH",
            "/api/scenarios/missing",
            json={"title": "X", "operation_id": "api-update-2"},
        )
    )
    assert status == 404
    status, _ = asyncio.run(
        _request(app, "DELETE", "/api/scenarios/missing?operation_id=api-remove-2")
    )
    assert status == 404


# --- service: regions ------------------------------------------------------


def _set_region(
    database_path: Path,
    *,
    region_id: str = "virellea",
    level: str = "kingdom",
    title: str = "Virellea",
    description: str = "The fertile heart of Aerthalon.",
    parent_region_id: str | None = None,
    attributes: dict[str, Any] | None = None,
    operation_id: str = "scenario-region-1",
    scenario_id: str = "aerthalon",
) -> dict[str, Any]:
    return set_scenario_region(
        database_path,
        scenario_id=scenario_id,
        operation_id=operation_id,
        region_id=region_id,
        level=level,
        title=title,
        description=description,
        parent_region_id=parent_region_id,
        attributes=attributes,
    )


def test_set_scenario_region_upserts_and_reads_back(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    _set_region(
        database_path,
        attributes={
            "biomes": ["Grassy Plains", "Ancient Forests"],
            "connected_by_road_to": {"thurnrok": "NW", "velquess": "NE"},
        },
    )
    _set_region(
        database_path,
        region_id="virellea-elaris",
        level="city",
        title="Elaris",
        description="Capital of Virellea.",
        parent_region_id="virellea",
        operation_id="scenario-region-2",
    )

    scenario = read_scenario(database_path, "aerthalon")
    assert [region["region_id"] for region in scenario["regions"]] == [
        "virellea",
        "virellea-elaris",
    ]
    virellea = next(r for r in scenario["regions"] if r["region_id"] == "virellea")
    assert virellea["level"] == "kingdom"
    assert virellea["attributes"]["connected_by_road_to"]["thurnrok"] == "NW"
    elaris = next(r for r in scenario["regions"] if r["region_id"] == "virellea-elaris")
    assert elaris["parent_region_id"] == "virellea"

    _set_region(
        database_path,
        description="Updated description.",
        operation_id="scenario-region-3",
    )
    scenario = read_scenario(database_path, "aerthalon")
    virellea = next(r for r in scenario["regions"] if r["region_id"] == "virellea")
    assert virellea["description"] == "Updated description."


def test_set_scenario_region_validates_ids_level_title_description(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    with pytest.raises(ScenarioConflict, match="kebab-case"):
        _set_region(database_path, region_id="Not Kebab!", operation_id="region-bad-1")
    with pytest.raises(ScenarioConflict, match="level must not be blank"):
        _set_region(database_path, level="   ", operation_id="region-bad-2")
    with pytest.raises(ScenarioConflict, match="title must not be blank"):
        _set_region(database_path, title="  ", operation_id="region-bad-3")
    with pytest.raises(ScenarioConflict, match="description must not be blank"):
        _set_region(database_path, description="", operation_id="region-bad-4")


def test_set_scenario_region_requires_parent_and_rejects_cycles(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)
    _set_region(database_path)
    _set_region(
        database_path,
        region_id="virellea-elaris",
        level="city",
        title="Elaris",
        description="Capital.",
        parent_region_id="virellea",
        operation_id="scenario-region-2",
    )

    with pytest.raises(ScenarioConflict, match="parent region not found"):
        _set_region(
            database_path,
            region_id="missing-city",
            level="city",
            title="Missing",
            description="D.",
            parent_region_id="missing-parent",
            operation_id="region-bad-5",
        )
    with pytest.raises(ScenarioConflict, match="cycle"):
        _set_region(
            database_path,
            region_id="virellea",
            parent_region_id="virellea-elaris",
            operation_id="region-bad-6",
        )


def test_set_scenario_region_replays_exactly(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    first = _set_region(database_path, operation_id="region-replay-1")
    second = _set_region(database_path, operation_id="region-replay-1")
    assert first["already_applied"] is False
    assert second["already_applied"] is True
    with pytest.raises(ScenarioConflict, match="already used"):
        _set_region(
            database_path,
            description="Different.",
            operation_id="region-replay-1",
        )


def test_remove_scenario_region_cascades_children(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)
    _set_region(database_path)
    _set_region(
        database_path,
        region_id="virellea-elaris",
        level="city",
        title="Elaris",
        description="Capital.",
        parent_region_id="virellea",
        operation_id="scenario-region-2",
    )

    result = remove_scenario_region(
        database_path,
        scenario_id="aerthalon",
        operation_id="scenario-region-remove-1",
        region_id="virellea",
    )
    assert result["removed"] is True
    scenario = read_scenario(database_path, "aerthalon")
    assert scenario["regions"] == []


def test_remove_scenario_region_missing_raises_not_found(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    _create(database_path)

    with pytest.raises(ScenarioNotFound, match="region not found"):
        remove_scenario_region(
            database_path,
            scenario_id="aerthalon",
            operation_id="scenario-region-remove-2",
            region_id="missing",
        )


def test_region_api_crud_round_trip(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    app = create_app(database_path)
    assert (
        asyncio.run(
            _request(
                app,
                "POST",
                "/api/scenarios",
                json={
                    "scenario_id": "aerthalon",
                    "title": "Aerthalon",
                    "operation_id": "api-region-create-1",
                },
            )
        )[0]
        == 201
    )

    status, _ = asyncio.run(
        _request(
            app,
            "PUT",
            "/api/scenarios/aerthalon/regions/virellea",
            json={
                "level": "kingdom",
                "title": "Virellea",
                "description": "The fertile heart of Aerthalon.",
                "attributes": {"biomes": ["Grassy Plains"]},
                "operation_id": "api-region-1",
            },
        )
    )
    assert status == 200

    status, _ = asyncio.run(
        _request(
            app,
            "PUT",
            "/api/scenarios/aerthalon/regions/virellea-elaris",
            json={
                "level": "city",
                "title": "Elaris",
                "description": "Capital of Virellea.",
                "parent_region_id": "virellea",
                "operation_id": "api-region-2",
            },
        )
    )
    assert status == 200

    status, body = asyncio.run(_request(app, "GET", "/api/scenarios/aerthalon"))
    assert status == 200
    assert [region["region_id"] for region in body["regions"]] == [
        "virellea",
        "virellea-elaris",
    ]

    status, _ = asyncio.run(
        _request(
            app,
            "DELETE",
            "/api/scenarios/aerthalon/regions/virellea?operation_id=api-region-remove-1",
        )
    )
    assert status == 200
    status, body = asyncio.run(_request(app, "GET", "/api/scenarios/aerthalon"))
    assert body["regions"] == []

    # Missing region delete is a 404; unknown parent on set is a 409.
    status, _ = asyncio.run(
        _request(
            app,
            "DELETE",
            "/api/scenarios/aerthalon/regions/missing?operation_id=api-region-remove-2",
        )
    )
    assert status == 404
    status, _ = asyncio.run(
        _request(
            app,
            "PUT",
            "/api/scenarios/aerthalon/regions/x",
            json={
                "level": "city",
                "title": "X",
                "description": "D.",
                "parent_region_id": "missing",
                "operation_id": "api-region-3",
            },
        )
    )
    assert status == 409
