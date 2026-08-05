from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.resources import (
    ResourceConflict,
    ResourceNotFound,
    read_resources,
    transfer_resource,
)
from backend.world.turns import (
    DecisionKind,
    OperationDecision,
    TurnDecision,
    TurnOutcome,
    run_turn,
)
from backend.world.validation import validate_worlds
from tests.backend.general_world import seed_general_world


def _ward_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    assert seed_ward_world(database_path)
    return database_path


def _grant_arguments(database_path: Path, operation_id: str = "resource-grant-1") -> dict[str, Any]:
    return {
        "database_path": database_path,
        "world_id": WARD_WORLD_ID,
        "operation_id": operation_id,
        "expected_revision": 0,
        "actor_entity_id": "player",
        "recipient_entity_id": "player",
        "resource_type": "coin",
        "quantity": 25,
    }


def test_resource_grant_persists_ledger_event_and_readback(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    result = transfer_resource(**_grant_arguments(database_path))

    assert result == {"already_applied": False, "world_revision": 1}
    resources = read_resources(
        database_path,
        world_id=WARD_WORLD_ID,
        owner_entity_ids=["player", "patient-1"],
    )
    assert resources == {
        "resources": [
            {"owner_entity_id": "player", "resource_type": "coin", "quantity": 25}
        ]
    }
    with connect_database(database_path) as connection:
        event = connection.execute(
            "SELECT event_type, world_revision, actor_entity_id FROM events"
        ).fetchone()
        operation = connection.execute(
            "SELECT operation_type, completed_revision FROM operations"
        ).fetchone()
    assert tuple(event) == ("resource_transferred", 1, "player")
    assert tuple(operation) == ("resource_transferred", 1)
    assert validate_worlds(database_path) == []


def test_resource_transfer_between_characters_updates_both_balances(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    transfer_resource(**_grant_arguments(database_path, "grant-player"))
    transfer_resource(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="transfer-player-1",
        expected_revision=1,
        actor_entity_id="player",
        recipient_entity_id="patient-2",
        resource_type="coin",
        quantity=10,
        source_entity_id="player",
    )

    resources = read_resources(
        database_path,
        world_id=WARD_WORLD_ID,
        owner_entity_ids=["player", "patient-2"],
    )
    assert resources["resources"] == [
        {"owner_entity_id": "patient-2", "resource_type": "coin", "quantity": 10},
        {"owner_entity_id": "player", "resource_type": "coin", "quantity": 15},
    ]
    assert validate_worlds(database_path) == []


def test_resource_transfer_is_exactly_idempotent(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    arguments = _grant_arguments(database_path, "resource-replay")

    first = transfer_resource(**arguments)
    replay = transfer_resource(**arguments)

    assert first == {"already_applied": False, "world_revision": 1}
    assert replay == {"already_applied": True, "world_revision": 1}
    assert (
        read_resources(
            database_path,
            world_id=WARD_WORLD_ID,
            owner_entity_ids=["player"],
        )["resources"][0]["quantity"]
        == 25
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("quantity", 0, "positive integer"),
        ("quantity", -5, "positive integer"),
        ("resource_type", "", "must not be blank"),
        ("operation_id", "", "must not be blank"),
    ],
)
def test_resource_transfer_rejects_invalid_input(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    database_path = _ward_database(tmp_path)
    arguments: dict[str, Any] = _grant_arguments(database_path)
    arguments[field] = value

    with pytest.raises(ResourceConflict, match=message):
        transfer_resource(**arguments)


def test_resource_transfer_rejects_missing_or_non_character_entities(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    with pytest.raises(ResourceNotFound, match="recipient character not found"):
        transfer_resource(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="missing-recipient",
            expected_revision=0,
            actor_entity_id="player",
            recipient_entity_id="bed-1",
            resource_type="coin",
            quantity=1,
        )
    with pytest.raises(ResourceNotFound, match="source character not found"):
        transfer_resource(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="missing-source",
            expected_revision=0,
            actor_entity_id="player",
            recipient_entity_id="player",
            resource_type="coin",
            quantity=1,
            source_entity_id="bed-2",
        )


def test_resource_transfer_rejects_overdraft_and_self_transfer(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    transfer_resource(**_grant_arguments(database_path, "grant-small"))

    with pytest.raises(ResourceConflict, match="does not have enough"):
        transfer_resource(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="overdraft",
            expected_revision=1,
            actor_entity_id="player",
            recipient_entity_id="patient-2",
            resource_type="coin",
            quantity=100,
            source_entity_id="player",
        )
    with pytest.raises(ResourceConflict, match="cannot target itself"):
        transfer_resource(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="self-transfer",
            expected_revision=1,
            actor_entity_id="player",
            recipient_entity_id="player",
            resource_type="coin",
            quantity=1,
            source_entity_id="player",
        )


def test_turn_runner_can_persist_a_reward_and_retrieve_it_later(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I complete the rodent job and get paid.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_transfer_resource",
                recipient_entity_id="player",
                resource_type="coin",
                quantity=50,
            ),
        ),
        operation_id_factory=lambda: "turn-reward-1",
    )

    assert result.outcome is TurnOutcome.SUCCESS
    assert result.after.world.revision == 1
    assert result.after.resources == [
        {"owner_entity_id": "player", "resource_type": "coin", "quantity": 50}
    ]
    assert result.after.recent_events[0].event_type == "resource_transferred"


def test_turn_runner_maps_resource_errors(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    missing = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I get paid by someone who is not here.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_transfer_resource",
                recipient_entity_id="player",
                resource_type="coin",
                quantity=1,
                source_entity_id="missing-quest-giver",
            ),
        ),
        operation_id_factory=lambda: "turn-reward-missing",
    )
    assert missing.outcome is TurnOutcome.MISSING_RESOURCE
    assert missing.after.world.revision == 0

    rejected = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I pay myself from my own pocket.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_transfer_resource",
                recipient_entity_id="player",
                resource_type="coin",
                quantity=1,
                source_entity_id="player",
            ),
        ),
        operation_id_factory=lambda: "turn-reward-conflict",
    )
    assert rejected.outcome is TurnOutcome.MUTATION_REJECTED
    assert rejected.after.world.revision == 0


def test_validation_reports_corrupted_resource_links(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    seed_general_world(database_path)
    transfer_resource(**_grant_arguments(database_path, "validation-grant"))

    with connect_database(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "UPDATE resources SET updated_event_id = 'missing-event' WHERE world_id = ?",
            (WARD_WORLD_ID,),
        )
        connection.execute(
            "UPDATE resources SET owner_entity_id = 'hen' WHERE world_id = ?",
            (WARD_WORLD_ID,),
        )
        connection.commit()

    codes = {issue.code for issue in validate_worlds(database_path)}
    assert "resource_updated_event_mismatch" in codes
    assert "resource_owner_not_character" in codes
