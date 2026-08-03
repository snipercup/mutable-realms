from __future__ import annotations

from pathlib import Path

import pytest

from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.social import (
    SocialConflict,
    SocialNotFound,
    read_social_context,
    record_social_interaction,
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


def test_social_interaction_persists_relationship_and_event_linked_memory(
    tmp_path: Path,
) -> None:
    database_path = _ward_database(tmp_path)

    result = record_social_interaction(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="social-1",
        expected_revision=0,
        actor_entity_id="player",
        subject_entity_id="player",
        object_entity_id="patient-1",
        relationship_category="trusted",
        relationship_delta=15,
        memory="The player stayed with Patient 1 during recovery.",
    )

    assert result == {"already_applied": False, "world_revision": 1}
    social = read_social_context(
        database_path,
        world_id=WARD_WORLD_ID,
        viewer_entity_id="player",
        related_entity_ids=["patient-1"],
    )
    assert social["relationships"] == [
        {
            "category": "trusted",
            "object_entity_id": "patient-1",
            "score": 15,
            "subject_entity_id": "player",
        }
    ]
    assert len(social["memories"]) == 1
    memory = social["memories"][0]
    assert memory["content"] == "The player stayed with Patient 1 during recovery."
    assert memory["entity_id"] == "player"
    assert memory["world_revision"] == 1
    assert memory["event_id"].startswith("event-")
    assert memory["id"].startswith("memory-")


def test_social_interaction_is_exactly_idempotent(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    arguments = {
        "database_path": database_path,
        "world_id": WARD_WORLD_ID,
        "operation_id": "social-replay",
        "expected_revision": 0,
        "actor_entity_id": "player",
        "subject_entity_id": "player",
        "object_entity_id": "patient-1",
        "relationship_category": "trusted",
        "relationship_delta": 15,
        "memory": "The player stayed with Patient 1 during recovery.",
    }

    first = record_social_interaction(**arguments)
    replay = record_social_interaction(**arguments)

    assert first == {"already_applied": False, "world_revision": 1}
    assert replay == {"already_applied": True, "world_revision": 1}
    assert (
        read_social_context(
            database_path,
            world_id=WARD_WORLD_ID,
            viewer_entity_id="player",
            related_entity_ids=["patient-1"],
        )["relationships"][0]["score"]
        == 15
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("relationship_delta", 101, "between -100 and 100"),
        ("relationship_category", "", "category must not be blank"),
        ("memory", "", "memory must not be blank"),
    ],
)
def test_social_interaction_rejects_invalid_input(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    database_path = _ward_database(tmp_path)
    arguments: dict[str, object] = {
        "database_path": database_path,
        "world_id": WARD_WORLD_ID,
        "operation_id": "invalid-social",
        "expected_revision": 0,
        "actor_entity_id": "player",
        "subject_entity_id": "player",
        "object_entity_id": "patient-1",
        "relationship_category": "trusted",
        "relationship_delta": 15,
        "memory": "A concise memory.",
    }
    arguments[field] = value

    with pytest.raises(SocialConflict, match=message):
        record_social_interaction(**arguments)


def test_social_interaction_rejects_cross_world_or_non_character_entities(
    tmp_path: Path,
) -> None:
    database_path = _ward_database(tmp_path)

    with pytest.raises(SocialNotFound, match="object character not found"):
        record_social_interaction(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="missing-social",
            expected_revision=0,
            actor_entity_id="player",
            subject_entity_id="player",
            object_entity_id="bed-1",
            relationship_category="trusted",
            relationship_delta=1,
            memory="A memory.",
        )


def test_turn_runner_can_persist_a_social_consequence_and_retrieve_it_later(
    tmp_path: Path,
) -> None:
    database_path = _ward_database(tmp_path)

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I reassure Patient 1 and remember their recovery.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_record_social_interaction",
                subject_entity_id="player",
                object_entity_id="patient-1",
                relationship_category="trusted",
                relationship_delta=10,
                memory="The player reassured Patient 1 during recovery.",
            ),
        ),
        operation_id_factory=lambda: "turn-social-1",
    )

    assert result.outcome is TurnOutcome.SUCCESS
    assert result.after.world.revision == 1
    assert result.after.relationships[0]["score"] == 10
    assert result.after.memories[0]["content"].startswith("The player reassured")


def test_turn_runner_maps_social_missing_resource_to_missing_resource(
    tmp_path: Path,
) -> None:
    database_path = _ward_database(tmp_path)

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I reassure someone who is not here.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_record_social_interaction",
                subject_entity_id="player",
                object_entity_id="missing-patient",
                relationship_category="trusted",
                relationship_delta=1,
                memory="A concise memory.",
            ),
        ),
        operation_id_factory=lambda: "turn-social-missing",
    )

    assert result.outcome is TurnOutcome.MISSING_RESOURCE
    assert result.after.world.revision == 0


def test_turn_runner_maps_social_conflict_to_mutation_rejected(
    tmp_path: Path,
) -> None:
    database_path = _ward_database(tmp_path)

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I create an impossible relationship.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_record_social_interaction",
                subject_entity_id="player",
                object_entity_id="player",
                relationship_category="trusted",
                relationship_delta=1,
                memory="A concise memory.",
            ),
        ),
        operation_id_factory=lambda: "turn-social-conflict",
    )

    assert result.outcome is TurnOutcome.MUTATION_REJECTED
    assert result.after.world.revision == 0


def test_validation_reports_social_cross_world_links(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    seed_general_world(database_path)
    record_social_interaction(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="social-validation",
        expected_revision=0,
        actor_entity_id="player",
        subject_entity_id="player",
        object_entity_id="patient-1",
        relationship_category="trusted",
        relationship_delta=1,
        memory="A concise memory.",
    )

    from backend.persistence.database import connect_database

    with connect_database(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "UPDATE relationships SET updated_event_id = ? WHERE world_id = ?",
            ("missing-event", WARD_WORLD_ID),
        )
        connection.execute(
            "UPDATE memories SET entity_id = ? WHERE world_id = ?",
            ("farmer", WARD_WORLD_ID),
        )
        connection.commit()

    codes = {issue.code for issue in validate_worlds(database_path)}
    assert "relationship_updated_event_mismatch" in codes
    assert "memory_entity_world_mismatch" in codes
