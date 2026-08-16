from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.app.narrator import NarratorError
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.town.seed import TOWN_WORLD_ID, seed_town_world
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.agent_tools import move_world_entity, read_world_status

WARD_SOCIAL_DECISION = {
    "kind": "perform_one_supported_operation",
    "message": "Player reassures Patient 2 and promises to look out for her.",
    "operation": {
        "operation_type": "world_record_social_interaction",
        "subject_entity_id": "player",
        "object_entity_id": "patient-2",
        "relationship_category": "grateful",
        "relationship_delta": 10,
        "memory": "Player promised to look out for Patient 2.",
    },
}

TOWN_MOVE_DECISION = {
    "kind": "perform_one_supported_operation",
    "message": "The sailor walks to the market.",
    "operation": {
        "operation_type": "world_move_entity",
        "entity_id": "sailor",
        "destination_location_id": "market",
    },
}

NARRATE_DECISION = {"kind": "narrate_without_mutation", "message": "The sailor waits."}


def _ward_app(tmp_path: Path) -> tuple[Any, Path]:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_ward_world(database_path)
    return create_app(database_path), database_path


def _town_app(
    tmp_path: Path, narrator: Any = None
) -> tuple[Any, Path]:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_town_world(database_path)
    return create_app(database_path, narrator=narrator), database_path


async def _post(app: Any, path: str, body: dict[str, Any]) -> tuple[int, Any]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(path, json=body)
    return response.status_code, response.json()


def _relationship(database_path: Path, subject: str, object_: str) -> tuple[str, int] | None:
    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT category, score FROM relationships " \
            "WHERE world_id = ? AND subject_entity_id = ? AND object_entity_id = ?",
            (WARD_WORLD_ID, subject, object_),
        ).fetchone()
    return None if row is None else (row[0], row[1])


def _entity_location(database_path: Path, world_id: str, entity_id: str) -> str | None:
    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT el.location_id FROM entity_locations el "
            "JOIN entities e ON e.id = el.entity_id "
            "WHERE e.world_id = ? AND e.id = ?",
            (world_id, entity_id),
        ).fetchone()
    return None if row is None else row[0]


def test_turn_endpoint_applies_deterministic_decision(tmp_path: Path) -> None:
    app, database_path = _ward_app(tmp_path)

    status, body = asyncio.run(
        _post(
            app,
            f"/api/worlds/{WARD_WORLD_ID}/turns",
            {
                "player_id": "player",
                "player_action": "I reassure Patient 2.",
                "decision_json": json.dumps(WARD_SOCIAL_DECISION),
            },
        )
    )

    assert status == 200
    assert body["outcome"] == "success"
    assert body["revision_before"] == 0
    assert body["revision_after"] == 1
    assert body["attempts"] == 1
    assert body["mutation"]["already_applied"] is False
    assert _relationship(database_path, "player", "patient-2") == ("grateful", 10)


def test_turn_endpoint_narrate_decision_does_not_mutate(tmp_path: Path) -> None:
    app, database_path = _town_app(tmp_path)

    status, body = asyncio.run(
        _post(
            app,
            f"/api/worlds/{TOWN_WORLD_ID}/turns",
            {
                "player_id": "sailor",
                "player_action": "The sailor waits.",
                "decision_json": json.dumps(NARRATE_DECISION),
            },
        )
    )

    assert status == 200
    assert body["outcome"] == "no_mutation"
    assert body["revision_before"] == 0
    assert body["revision_after"] == 0
    assert body["mutation"] is None


def test_turn_endpoint_rejects_invalid_decision_json(tmp_path: Path) -> None:
    app, _ = _ward_app(tmp_path)

    status, body = asyncio.run(
        _post(
            app,
            f"/api/worlds/{WARD_WORLD_ID}/turns",
            {
                "player_id": "player",
                "player_action": "anything",
                "decision_json": "{not valid json",
            },
        )
    )

    assert status == 422
    assert "invalid decision_json" in body["detail"]


def test_turn_endpoint_missing_world_returns_404(tmp_path: Path) -> None:
    app, _ = _ward_app(tmp_path)

    status, body = asyncio.run(
        _post(
            app,
            "/api/worlds/missing-world/turns",
            {
                "player_id": "player",
                "player_action": "anything",
                "decision_json": json.dumps(NARRATE_DECISION),
            },
        )
    )

    assert status == 404
    assert body["detail"] == "world not found"


def test_turn_endpoint_player_mismatch_returns_409(tmp_path: Path) -> None:
    app, _ = _ward_app(tmp_path)

    status, body = asyncio.run(
        _post(
            app,
            f"/api/worlds/{WARD_WORLD_ID}/turns",
            {
                "player_id": "sailor",
                "player_action": "anything",
                "decision_json": json.dumps(WARD_SOCIAL_DECISION),
            },
        )
    )

    assert status == 409
    assert "bound player" in body["detail"]


def test_turn_endpoint_empty_action_rejected(tmp_path: Path) -> None:
    app, _ = _ward_app(tmp_path)

    status, _ = asyncio.run(
        _post(
            app,
            f"/api/worlds/{WARD_WORLD_ID}/turns",
            {"player_id": "player", "player_action": "   "},
        )
    )

    assert status == 422


def _mutating_narrator(database_path: Path) -> Any:
    calls = {"count": 0}

    def narrator(
        world_id: str,
        player_id: str,
        player_action: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        calls["count"] += 1
        revision = read_world_status(database_path, world_id=world_id)["world"]["revision"]
        move_world_entity(
            database_path,
            world_id=world_id,
            operation_id=f"relay-move-{calls['count']}",
            expected_revision=revision,
            entity_id="sailor",
            destination_location_id="market",
            actor_entity_id=player_id,
        )
        return f"The sailor walks to the market. ({player_action})"

    return narrator


def test_turn_relay_reports_committed_revision(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    seed_town_world(database_path)
    app = create_app(database_path, narrator=_mutating_narrator(database_path))

    status, body = asyncio.run(
        _post(
            app,
            f"/api/worlds/{TOWN_WORLD_ID}/turns",
            {"player_id": "sailor", "player_action": "I walk to the market."},
        )
    )

    assert status == 200
    assert body["outcome"] == "narrated_turn"
    assert "market" in body["narration"]
    assert body["revision_before"] == 0
    assert body["revision_after"] == 1
    assert _entity_location(database_path, TOWN_WORLD_ID, "sailor") == "market"


def test_turn_relay_without_mutation_returns_narration_only(tmp_path: Path) -> None:
    received_contexts: list[dict[str, Any] | None] = []

    def narrator(
        world_id: str,
        player_id: str,
        player_action: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        received_contexts.append(context)
        return f"The sailor stays put. ({player_action})"

    app, database_path = _town_app(tmp_path, narrator=narrator)

    status, body = asyncio.run(
        _post(
            app,
            f"/api/worlds/{TOWN_WORLD_ID}/turns",
            {"player_id": "sailor", "player_action": "I wait."},
        )
    )

    assert status == 200
    assert body["outcome"] == "narrated_turn"
    assert body["narration"] == "The sailor stays put. (I wait.)"
    assert body["revision_before"] == 0
    assert body["revision_after"] == 0
    assert _entity_location(database_path, TOWN_WORLD_ID, "sailor") == "plaza"
    # The relay embeds the selected world's authoritative context for the agent.
    assert received_contexts[0] is not None
    assert received_contexts[0]["world"]["id"] == TOWN_WORLD_ID
    assert received_contexts[0]["player"]["id"] == "sailor"


def test_turn_relay_narrator_failure_returns_502(tmp_path: Path) -> None:
    def narrator(
        world_id: str,
        player_id: str,
        player_action: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        raise NarratorError("narration agent failed: boom")

    app, _ = _town_app(tmp_path, narrator=narrator)

    status, body = asyncio.run(
        _post(
            app,
            f"/api/worlds/{TOWN_WORLD_ID}/turns",
            {"player_id": "sailor", "player_action": "I wait."},
        )
    )

    assert status == 502
    assert "boom" in body["detail"]


def test_turn_relay_missing_world_returns_404(tmp_path: Path) -> None:
    def narrator(
        world_id: str,
        player_id: str,
        player_action: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        return "should not be reached"

    app, _ = _town_app(tmp_path, narrator=narrator)

    status, body = asyncio.run(
        _post(
            app,
            "/api/worlds/missing-world/turns",
            {"player_id": "sailor", "player_action": "I wait."},
        )
    )

    assert status == 404
    assert body["detail"] == "world not found"
