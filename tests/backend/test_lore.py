from pathlib import Path

import pytest

from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.world.context import build_world_context
from backend.world.lore import (
    read_world_lore,
    remove_world_lore,
    search_world_lore,
    set_scenario_lore,
    set_world_lore,
)
from backend.world.scenarios import create_scenario
from backend.world.worlds import (
    WorldAdminConflict,
    create_world_from_scenario,
    world_provision_player,
)


def _world(tmp_path: Path) -> Path:
    path = tmp_path / "world.sqlite3"
    migrate_database(path)
    create_scenario(path, scenario_id="night-city", operation_id="scenario-1", title="Night City")
    set_scenario_lore(
        path,
        scenario_id="night-city",
        operation_id="lore-1",
        lore_id="tyger-claws",
        category="faction",
        title="Tyger Claws",
        content="A major Night City gang with strong influence in Japantown and Westbrook.",
        keywords=["Westbrook", "Japantown"],
    )
    create_world_from_scenario(
        path, world_id="night-city-play", operation_id="world-1", scenario_id="night-city"
    )
    world_provision_player(
        path,
        world_id="night-city-play",
        operation_id="player-1",
        expected_revision=1,
        player_name="Fate",
        location_name="Westbrook",
    )
    return path


def test_world_lore_is_copied_searchable_and_relevant_in_context(tmp_path: Path) -> None:
    path = _world(tmp_path)
    assert search_world_lore(path, world_id="night-city-play", query="Westbrook") == [
        {
            "lore_id": "tyger-claws",
            "category": "faction",
            "title": "Tyger Claws",
            "keywords": ["Westbrook", "Japantown"],
        }
    ]
    assert read_world_lore(path, world_id="night-city-play", lore_id="tyger-claws")[
        "content"
    ].startswith("A major")
    context = build_world_context(path, world_id="night-city-play")
    assert [entry["lore_id"] for entry in context.relevant_lore] == ["tyger-claws"]


def test_world_lore_mutations_are_revision_checked_and_do_not_change_scenario(
    tmp_path: Path,
) -> None:
    path = _world(tmp_path)
    result = set_world_lore(
        path,
        world_id="night-city-play",
        operation_id="world-lore-1",
        expected_revision=2,
        lore_id="tyger-claws",
        category="faction",
        title="Tyger Claws",
        content="Changed only in this world.",
        keywords=["Westbrook"],
    )
    assert result["world_revision"] == 3
    assert (
        read_world_lore(path, world_id="night-city-play", lore_id="tyger-claws")["content"]
        == "Changed only in this world."
    )
    with connect_database(path) as connection:
        assert (
            connection.execute(
                "SELECT content FROM scenario_lore "
                "WHERE scenario_id='night-city' AND lore_id='tyger-claws'"
            )
            .fetchone()[0]
            .startswith("A major")
        )
    with pytest.raises(WorldAdminConflict, match="expected world revision"):
        remove_world_lore(
            path,
            world_id="night-city-play",
            operation_id="world-lore-2",
            expected_revision=2,
            lore_id="tyger-claws",
        )
    assert (
        remove_world_lore(
            path,
            world_id="night-city-play",
            operation_id="world-lore-2",
            expected_revision=3,
            lore_id="tyger-claws",
        )["world_revision"]
        == 4
    )
