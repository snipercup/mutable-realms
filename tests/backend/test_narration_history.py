from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.seed import seed_ward_world
from backend.world.narration_history import append_narration, read_narration_history
from backend.world.queries import WorldNotFound


def _ward_db(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    return database_path


def test_append_and_read_returns_entries_oldest_to_newest(tmp_path: Path) -> None:
    database_path = _ward_db(tmp_path)
    append_narration(
        database_path, world_id="ward-world", revision=1, role="agent", content="Welcome."
    )
    append_narration(
        database_path,
        world_id="ward-world",
        revision=1,
        role="player",
        content="I wait quietly.",
    )
    append_narration(
        database_path,
        world_id="ward-world",
        revision=2,
        role="agent",
        content="Nothing stirs.",
    )

    entries = read_narration_history(database_path, world_id="ward-world", limit=20)
    assert [entry["content"] for entry in entries] == [
        "Welcome.",
        "I wait quietly.",
        "Nothing stirs.",
    ]
    assert [entry["role"] for entry in entries] == ["agent", "player", "agent"]
    assert [entry["revision"] for entry in entries] == [1, 1, 2]


def test_read_limit_returns_most_recent_entries(tmp_path: Path) -> None:
    database_path = _ward_db(tmp_path)
    for index in range(5):
        append_narration(
            database_path,
            world_id="ward-world",
            revision=1,
            role="agent",
            content=f"Entry {index}.",
        )

    entries = read_narration_history(database_path, world_id="ward-world", limit=2)
    assert [entry["content"] for entry in entries] == ["Entry 3.", "Entry 4."]


def test_read_raises_for_missing_world(tmp_path: Path) -> None:
    database_path = _ward_db(tmp_path)
    try:
        read_narration_history(database_path, world_id="missing-world")
    except WorldNotFound:
        pass
    else:
        raise AssertionError("expected WorldNotFound")


def test_append_validates_role_and_content(tmp_path: Path) -> None:
    database_path = _ward_db(tmp_path)
    try:
        append_narration(
            database_path, world_id="ward-world", revision=1, role="system", content="x"
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for invalid role")
    try:
        append_narration(
            database_path, world_id="ward-world", revision=1, role="agent", content="  "
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for blank content")


def test_world_deletion_cascades_narration_history(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO worlds (id, name, revision) VALUES ('solo-world', 'Solo', 0)"
        )
    append_narration(
        database_path, world_id="solo-world", revision=1, role="agent", content="Welcome."
    )
    with connect_database(database_path) as connection:
        connection.execute("DELETE FROM worlds WHERE id = 'solo-world'")
    with connect_database(database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM narration_history WHERE world_id = 'solo-world'"
        ).fetchone()[0]
    assert count == 0


async def _get(app: Any, path: str) -> tuple[int, Any]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(path)
    return response.status_code, response.json()


def test_narration_route_returns_history_for_world(tmp_path: Path) -> None:
    database_path = _ward_db(tmp_path)
    app = create_app(database_path)
    append_narration(
        database_path, world_id="ward-world", revision=1, role="agent", content="Welcome."
    )

    status, body = asyncio.run(_get(app, "/api/worlds/ward-world/narration?limit=20"))
    assert status == 200
    assert body["world_id"] == "ward-world"
    assert body["entries"][0]["role"] == "agent"
    assert body["entries"][0]["content"] == "Welcome."


def test_narration_route_returns_404_for_missing_world(tmp_path: Path) -> None:
    database_path = _ward_db(tmp_path)
    app = create_app(database_path)

    status, body = asyncio.run(_get(app, "/api/worlds/missing/narration"))
    assert status == 404
    assert body == {"detail": "world not found"}


def test_narrated_turn_records_player_and_agent_entries(tmp_path: Path) -> None:
    database_path = _ward_db(tmp_path)

    def narrator(
        world_id: str,
        player_id: str,
        player_action: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        return "The ward is still."

    app = create_app(database_path, narrator=narrator)

    status, _ = asyncio.run(
        _post(
            app,
            "/api/worlds/ward-world/turns",
            {"player_id": "player", "player_action": "I inspect the ward."},
        )
    )
    assert status == 200

    entries = read_narration_history(database_path, world_id="ward-world", limit=20)
    assert [entry["role"] for entry in entries] == ["player", "agent"]
    assert entries[0]["content"] == "I inspect the ward."
    assert entries[1]["content"] == "The ward is still."


def test_narrated_turn_passes_recent_narration_into_context(tmp_path: Path) -> None:
    database_path = _ward_db(tmp_path)
    received_contexts: list[dict[str, Any]] = []

    def narrator(
        world_id: str,
        player_id: str,
        player_action: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        received_contexts.append(dict(context) if context else {})
        return "The ward is still."

    app = create_app(database_path, narrator=narrator)

    asyncio.run(
        _post(
            app,
            "/api/worlds/ward-world/turns",
            {"player_id": "player", "player_action": "I inspect the ward."},
        )
    )
    assert received_contexts[0]["recent_narration"] == []
    assert "player" in received_contexts[0]

    asyncio.run(
        _post(
            app,
            "/api/worlds/ward-world/turns",
            {"player_id": "player", "player_action": "I open the door."},
        )
    )
    # The second turn sees both the player's first action and the agent reply.
    assert [entry["content"] for entry in received_contexts[1]["recent_narration"]] == [
        "I inspect the ward.",
        "The ward is still.",
    ]


async def _post(app: Any, path: str, body: dict[str, Any]) -> tuple[int, Any]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(path, json=body)
    return response.status_code, response.json()
