from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.narrator import build_narration_prompt
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.world.context import build_world_context
from backend.world.expansion import ExpansionNotFound, propose_location_expansion
from backend.world.regions import read_world_regions, resolve_region_chain
from backend.world.routes import RouteConflict, create_route


def _world_with_framework(tmp_path: Path) -> Path:
    """A world with a kingdom (virellea) + city region, and a neighbor kingdom."""
    path = tmp_path / "world.sqlite3"
    migrate_database(path)
    with connect_database(path) as connection:
        connection.execute(
            "INSERT INTO worlds(id, name, revision) VALUES ('world-a', 'World A', 0)"
        )
        connection.executemany(
            "INSERT INTO locations(id, world_id, name) VALUES (?, 'world-a', ?)",
            [
                ("virellea", "Virellea"),
                ("virellea-elaris", "Elaris"),
                ("thurnrok", "Thurnrok"),
                ("thurnrok-capital", "Thurnrok Capital"),
                ("caldrith", "Caldrith"),
                ("caldrith-skyport", "Caldrith Skyport"),
                ("main-street", "Main Street"),
            ],
        )
        connection.execute(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES ('world-a', 'virellea-elaris', 'virellea')"
        )
        connection.execute(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES ('world-a', 'thurnrok-capital', 'thurnrok')"
        )
        connection.execute(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES ('world-a', 'caldrith-skyport', 'caldrith')"
        )
        connection.execute(
            "INSERT INTO location_containment(world_id, child_location_id, parent_location_id) "
            "VALUES ('world-a', 'main-street', 'virellea-elaris')"
        )
        connection.executemany(
            "INSERT INTO world_regions("
            "world_id, region_id, parent_region_id, level, title, description, "
            "attributes_json, location_id) VALUES ('world-a', ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "virellea",
                    None,
                    "kingdom",
                    "Virellea",
                    "Fertile heart.",
                    '{"biomes": ["Grassy Plains"], '
                    '"connected_by_road_to": {"thurnrok": "NW"}}',
                    "virellea",
                ),
                (
                    "virellea-elaris",
                    "virellea",
                    "city",
                    "Elaris",
                    "Capital.",
                    "{}",
                    "virellea-elaris",
                ),
                (
                    "thurnrok",
                    None,
                    "kingdom",
                    "Thurnrok",
                    "Volcanic ridges.",
                    '{"connected_by_road_to": {"virellea": "SE"}}',
                    "thurnrok",
                ),
                (
                    "caldrith",
                    None,
                    "kingdom",
                    "Caldrith",
                    "Floating isles.",
                    "{}",
                    "caldrith",
                ),
            ],
        )
        connection.commit()
    return path


def _player_at(path: Path, location_id: str) -> None:
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
            "INSERT INTO entity_locations(entity_id, location_id) VALUES ('sailor', ?)",
            (location_id,),
        )
        connection.commit()


# --- region chain resolution -------------------------------------------------


def test_resolve_region_chain_walks_containment_to_bound_region(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    chain = resolve_region_chain(path, world_id="world-a", location_id="main-street")
    assert [region["region_id"] for region in chain] == [
        "virellea-elaris",
        "virellea",
    ]


def test_resolve_region_chain_returns_empty_outside_framework(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    chain = resolve_region_chain(path, world_id="world-a", location_id="thurnrok-capital")
    assert [region["region_id"] for region in chain] == ["thurnrok"]


def test_resolve_region_chain_missing_location_is_empty(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    assert resolve_region_chain(path, world_id="world-a", location_id="missing") == []


# --- context + prompt --------------------------------------------------------


def test_context_exposes_region_framework_for_current_location(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    _player_at(path, "main-street")

    context = build_world_context(path, world_id="world-a").model_dump()
    assert [region["region_id"] for region in context["region_framework"]] == [
        "virellea-elaris",
        "virellea",
    ]
    virellea = context["region_framework"][1]
    assert virellea["attributes"]["connected_by_road_to"] == {"thurnrok": "NW"}


def test_prompt_renders_region_framework(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    _player_at(path, "main-street")
    context = build_world_context(path, world_id="world-a").model_dump()

    prompt = build_narration_prompt("world-a", "sailor", "I look around.", context)

    assert "Region framework (authoritative world knowledge):" in prompt
    assert "Virellea" in prompt and "(kingdom)" in prompt
    assert "Connected by road to: thurnrok (NW)" in prompt


# --- expansion binding -------------------------------------------------------


def test_expansion_binds_location_to_region(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    result = propose_location_expansion(
        path,
        world_id="world-a",
        operation_id="expand-1",
        expected_revision=0,
        proposal_id="prop-1",
        location_id="virellea-greenwatch",
        anchor_location_id="virellea-elaris",
        name="Greenwatch",
        connect_to_anchor=True,
        region_id="virellea",
    )
    assert result["already_applied"] is False
    regions = read_world_regions(path, world_id="world-a")
    virellea = next(r for r in regions if r["region_id"] == "virellea")
    assert virellea["location_id"] == "virellea-greenwatch"


def test_expansion_rejects_unknown_region(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    with pytest.raises(ExpansionNotFound, match="region not found"):
        propose_location_expansion(
            path,
            world_id="world-a",
            operation_id="expand-2",
            expected_revision=0,
            proposal_id="prop-2",
            location_id="somewhere",
            anchor_location_id="virellea-elaris",
            name="Somewhere",
            region_id="missing-region",
        )


# --- framework-validated routes ---------------------------------------------


def test_route_between_declared_neighbor_regions_is_accepted(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    result = create_route(
        path,
        world_id="world-a",
        route_id="road-virellea-thurnrok",
        operation_id="route-1",
        expected_revision=0,
        origin_location_id="virellea-elaris",
        destination_location_id="thurnrok-capital",
        name="The North Road",
    )
    assert result["already_applied"] is False


def test_route_within_same_region_is_accepted(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    result = create_route(
        path,
        world_id="world-a",
        route_id="road-elaris-street",
        operation_id="route-2",
        expected_revision=0,
        origin_location_id="main-street",
        destination_location_id="virellea-elaris",
        name="Main Street Gate",
    )
    assert result["already_applied"] is False


def test_route_between_non_adjacent_regions_is_rejected(tmp_path: Path) -> None:
    path = _world_with_framework(tmp_path)
    with pytest.raises(RouteConflict, match="not declared adjacent"):
        create_route(
            path,
            world_id="world-a",
            route_id="road-impossible",
            operation_id="route-3",
            expected_revision=0,
            origin_location_id="virellea-elaris",
            destination_location_id="caldrith-skyport",
            name="Impossible Road",
        )


def test_route_without_framework_still_works(tmp_path: Path) -> None:
    path = tmp_path / "world.sqlite3"
    migrate_database(path)
    with connect_database(path) as connection:
        connection.execute(
            "INSERT INTO worlds(id, name, revision) VALUES ('plain', 'Plain', 0)"
        )
        connection.executemany(
            "INSERT INTO locations(id, world_id, name) VALUES (?, 'plain', ?)",
            [("harbor", "Harbor"), ("city", "City")],
        )
        connection.commit()
    result = create_route(
        path,
        world_id="plain",
        route_id="road",
        operation_id="route-4",
        expected_revision=0,
        origin_location_id="harbor",
        destination_location_id="city",
        name="Plain Road",
    )
    assert result["already_applied"] is False


# --- backfill migration ------------------------------------------------------


def test_backfill_copies_scenario_regions_into_pre_existing_world(tmp_path: Path) -> None:
    """Simulate a world created before migration 0020: it has a source scenario
    with regions but no world_regions rows. Running the 0021 backfill SQL must
    copy the scenario regions into it."""
    from backend.persistence.migrations import DEFAULT_MIGRATIONS_PATH

    path = tmp_path / "world.sqlite3"
    migrate_database(path)
    with connect_database(path) as connection:
        connection.execute(
            "INSERT INTO scenarios(id, title) VALUES ('aerthalon', 'Aerthalon')"
        )
        connection.execute(
            "INSERT INTO worlds(id, name, revision, source_scenario_id) "
            "VALUES ('old-world', 'Old World', 5, 'aerthalon')"
        )
        connection.executemany(
            "INSERT INTO scenario_regions("
            "scenario_id, region_id, parent_region_id, level, title, description, "
            "attributes_json) VALUES ('aerthalon', ?, ?, ?, ?, ?, ?)",
            [
                ("virellea", None, "kingdom", "Virellea", "Fertile.", "{}"),
                ("virellea-elaris", "virellea", "city", "Elaris", "Capital.", "{}"),
            ],
        )
        connection.commit()

    backfill_sql = (DEFAULT_MIGRATIONS_PATH / "0021_backfill_world_regions.sql").read_text()
    with connect_database(path) as connection:
        connection.execute("BEGIN")
        connection.executescript(backfill_sql)
        connection.commit()

    regions = read_world_regions(path, world_id="old-world")
    assert [region["region_id"] for region in regions] == [
        "virellea",
        "virellea-elaris",
    ]
    assert regions[1]["parent_region_id"] == "virellea"
    # Idempotent: a second run must not duplicate rows.
    with connect_database(path) as connection:
        connection.execute("BEGIN")
        connection.executescript(backfill_sql)
        connection.commit()
    assert len(read_world_regions(path, world_id="old-world")) == 2
