from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.narrator import build_narration_prompt
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.world.context import build_world_context
from backend.world.location_memories import (
    MemoryConflict,
    MemoryNotFound,
    consolidate_location_memories,
    normalize_memory_key,
    read_location_memories,
    record_location_memory,
)


def _world(tmp_path: Path) -> Path:
    path = tmp_path / "world.sqlite3"
    migrate_database(path)
    with connect_database(path) as connection:
        connection.execute("INSERT INTO worlds(id, name) VALUES ('world-a', 'World A')")
        connection.executemany(
            "INSERT INTO locations(id, world_id, name) VALUES (?, 'world-a', ?)",
            [("farmstead", "Farmstead"), ("plaza", "Plaza")],
        )
        connection.commit()
    return path


def test_normalize_memory_key_collapses_casing_and_whitespace() -> None:
    assert normalize_memory_key("  Fate  Harvested  Mushrooms ") == "fate harvested mushrooms"
    assert normalize_memory_key("FATE HARVESTED MUSHROOMS") == "fate harvested mushrooms"


def test_record_memory_creates_row_and_bumps_revision(tmp_path: Path) -> None:
    path = _world(tmp_path)
    result = record_location_memory(
        path,
        world_id="world-a",
        operation_id="mem-1",
        expected_revision=0,
        location_id="farmstead",
        memory_key="Fate fixed the cart",
        content="Fate fixed the cart at the farmstead.",
    )
    assert result == {
        "already_applied": False,
        "location_id": "farmstead",
        "memory_key": "fate fixed the cart",
        "occurrence_count": 1,
        "world_id": "world-a",
        "world_revision": 1,
    }
    with connect_database(path) as connection:
        row = connection.execute(
            "SELECT memory_key, content, occurrence_count FROM location_memories"
        ).fetchone()
    assert tuple(row) == ("fate fixed the cart", "Fate fixed the cart at the farmstead.", 1)


def test_record_same_key_increments_occurrence_count(tmp_path: Path) -> None:
    path = _world(tmp_path)
    kwargs = {
        "world_id": "world-a",
        "operation_id": "mem-1",
        "expected_revision": 0,
        "location_id": "farmstead",
        "memory_key": "fate harvested mushrooms",
        "content": "Fate harvested mushrooms.",
    }
    first = record_location_memory(path, **kwargs)
    second = record_location_memory(
        path,
        **{
            **kwargs,
            "operation_id": "mem-2",
            "expected_revision": 1,
            "content": "Fate harvested mushrooms again.",
        },
    )
    assert first["occurrence_count"] == 1
    assert second["occurrence_count"] == 2
    with connect_database(path) as connection:
        rows = connection.execute("SELECT memory_key FROM location_memories").fetchall()
        assert len(rows) == 1
        row = connection.execute(
            "SELECT content, occurrence_count FROM location_memories"
        ).fetchone()
    assert tuple(row) == ("Fate harvested mushrooms again.", 2)


def test_record_memory_replays_exactly_and_rejects_stale_revision(tmp_path: Path) -> None:
    path = _world(tmp_path)
    kwargs = {
        "world_id": "world-a",
        "operation_id": "mem-1",
        "expected_revision": 0,
        "location_id": "farmstead",
        "memory_key": "fate fixed the cart",
        "content": "Fate fixed the cart.",
    }
    first = record_location_memory(path, **kwargs)
    replay = record_location_memory(path, **kwargs)
    assert replay["already_applied"] is True
    assert replay["world_revision"] == first["world_revision"] == 1
    with pytest.raises(MemoryConflict, match="revision"):
        record_location_memory(path, **{**kwargs, "operation_id": "mem-2"})
    with pytest.raises(MemoryConflict, match="already used"):
        record_location_memory(
            path, **{**kwargs, "expected_revision": 1, "content": "different text"}
        )


def test_record_memory_rejects_missing_location_and_foreign_actor(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with pytest.raises(MemoryNotFound, match="location"):
        record_location_memory(
            path,
            world_id="world-a",
            operation_id="mem-1",
            expected_revision=0,
            location_id="missing",
            memory_key="k",
            content="c",
        )
    with pytest.raises(MemoryNotFound, match="actor"):
        record_location_memory(
            path,
            world_id="world-a",
            operation_id="mem-2",
            expected_revision=0,
            location_id="farmstead",
            memory_key="k",
            content="c",
            actor_entity_id="nobody",
        )


def test_consolidate_merges_keys_with_summed_counts(tmp_path: Path) -> None:
    path = _world(tmp_path)
    record_location_memory(
        path,
        world_id="world-a",
        operation_id="mem-1",
        expected_revision=0,
        location_id="farmstead",
        memory_key="fate picked apples",
        content="Fate picked apples.",
    )
    record_location_memory(
        path,
        world_id="world-a",
        operation_id="mem-2",
        expected_revision=1,
        location_id="farmstead",
        memory_key="fate picked pears",
        content="Fate picked pears.",
    )
    record_location_memory(
        path,
        world_id="world-a",
        operation_id="mem-3",
        expected_revision=2,
        location_id="farmstead",
        memory_key="fate picked apples",
        content="Fate picked apples.",
    )

    result = consolidate_location_memories(
        path,
        world_id="world-a",
        operation_id="consol-1",
        expected_revision=3,
        location_id="farmstead",
        memory_keys=["fate picked apples", "fate picked pears"],
        content="Fate gathered fruit at the farmstead.",
    )

    assert result["memory_key"] == "fate gathered fruit at the farmstead."
    assert result["merged_count"] == 3
    with connect_database(path) as connection:
        rows = connection.execute(
            "SELECT memory_key, occurrence_count FROM location_memories"
        ).fetchall()
    assert [tuple(row) for row in rows] == [("fate gathered fruit at the farmstead.", 3)]


def test_consolidate_requires_existing_keys(tmp_path: Path) -> None:
    path = _world(tmp_path)
    with pytest.raises(MemoryNotFound, match="not found"):
        consolidate_location_memories(
            path,
            world_id="world-a",
            operation_id="consol-1",
            expected_revision=0,
            location_id="farmstead",
            memory_keys=["missing memory"],
            content="Merged.",
        )


def test_read_memories_is_bounded_to_render_budget(tmp_path: Path) -> None:
    path = _world(tmp_path)
    revision = 0
    # 14 memories × 300 chars = 4200 chars > the 4000-char render budget.
    for index in range(14):
        record_location_memory(
            path,
            world_id="world-a",
            operation_id=f"mem-{index + 1}",
            expected_revision=revision,
            location_id="farmstead",
            memory_key=f"fact {index}",
            content=f"fact {index}: " + "x" * 290,
        )
        revision += 1

    memories = read_location_memories(
        path, world_id="world-a", location_ids=["farmstead"]
    )
    assert len(memories) <= 13
    assert sum(len(m["content"]) + 1 for m in memories) <= 4000


def test_context_includes_only_current_location_memories(tmp_path: Path) -> None:
    path = _world(tmp_path)
    record_location_memory(
        path,
        world_id="world-a",
        operation_id="mem-1",
        expected_revision=0,
        location_id="farmstead",
        memory_key="fate fixed the cart",
        content="Fate fixed the cart at the farmstead.",
    )
    record_location_memory(
        path,
        world_id="world-a",
        operation_id="mem-2",
        expected_revision=1,
        location_id="plaza",
        memory_key="fate argued with a duck",
        content="Fate argued with a duck in the plaza.",
    )
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
            "INSERT INTO entity_locations(entity_id, location_id) "
            "VALUES ('sailor', 'farmstead')"
        )
        connection.commit()

    context = build_world_context(path, world_id="world-a")
    assert context.current_location.id == "farmstead"
    assert [m["content"] for m in context.current_location.memories] == [
        "Fate fixed the cart at the farmstead."
    ]


def test_prompt_renders_location_memories_with_counts(tmp_path: Path) -> None:
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
            "INSERT INTO entity_locations(entity_id, location_id) "
            "VALUES ('sailor', 'farmstead')"
        )
        connection.commit()
    record_location_memory(
        path,
        world_id="world-a",
        operation_id="mem-1",
        expected_revision=0,
        location_id="farmstead",
        memory_key="fate harvested mushrooms",
        content="Fate harvested mushrooms.",
    )
    record_location_memory(
        path,
        world_id="world-a",
        operation_id="mem-2",
        expected_revision=1,
        location_id="farmstead",
        memory_key="fate harvested mushrooms",
        content="Fate harvested mushrooms.",
    )
    context = build_world_context(path, world_id="world-a").model_dump()

    prompt = build_narration_prompt(
        "world-a", "sailor", "I look around.", context
    )

    assert "Location memories" in prompt
    assert "Fate harvested mushrooms. (x2)" in prompt
