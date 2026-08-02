from __future__ import annotations

from pathlib import Path

import pytest

from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.mutations import move_entity
from backend.world.turns import (
    DecisionKind,
    OperationDecision,
    TurnDecision,
    TurnOutcome,
    run_turn,
)


def _ward_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    assert seed_ward_world(database_path)
    return database_path


def _treat_decision() -> TurnDecision:
    return TurnDecision(
        kind=DecisionKind.PERFORM_OPERATION,
        operation=OperationDecision(
            operation_type="world_treat_and_discharge_patient",
            patient_id="patient-1",
            bed_id="bed-1",
        ),
    )


def test_no_mutation_turn_preserves_revision(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="Look around the ward.",
        decide=lambda _action, _context: TurnDecision(kind=DecisionKind.NARRATE),
        operation_id_factory=lambda: "unused",
    )

    assert result.outcome is TurnOutcome.NO_MUTATION
    assert result.before.world.revision == 0
    assert result.after.world.revision == 0
    assert result.mutation is None


def test_treatment_turn_persists_and_rereads_authoritative_state(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="Treat the patient in the first bed and arrange discharge.",
        decide=lambda _action, _context: _treat_decision(),
        operation_id_factory=lambda: "turn-treatment-1",
    )

    assert result.outcome is TurnOutcome.SUCCESS
    assert result.mutation == {"already_applied": False, "world_revision": 1}
    assert result.after.world.revision == 1
    assert result.after.recent_events[0].event_type == "patient_treated_and_discharged"
    assert result.after.recent_events[0].operation_id == "turn-treatment-1"
    assert all(entity.id != "patient-1" for entity in result.after.current_location.entities)


def test_operation_id_conflict_is_not_reported_as_success(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    first = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="Treat patient one.",
        decide=lambda _action, _context: _treat_decision(),
        operation_id_factory=lambda: "same-operation",
    )
    conflict = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="Treat patient one again.",
        decide=lambda _action, _context: _treat_decision(),
        operation_id_factory=lambda: "same-operation",
    )

    assert first.outcome is TurnOutcome.SUCCESS
    assert conflict.outcome is TurnOutcome.MUTATION_REJECTED
    assert conflict.after.world.revision == 1


def test_stale_revision_refetches_context_and_redecides_once(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    decisions = 0

    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO locations(id, world_id, name) VALUES ('outside', ?, 'Outside')",
            (WARD_WORLD_ID,),
        )
        connection.commit()

    def race_decide(_action: str, context):
        nonlocal decisions
        decisions += 1
        if decisions == 1:
            move_entity(
                database_path,
                world_id=WARD_WORLD_ID,
                operation_id="outside-turn",
                expected_revision=context.world.revision,
                entity_id="player",
                destination_location_id="outside",
            )
        return _treat_decision()

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="Treat patient one.",
        decide=race_decide,
        operation_id_factory=lambda: "retry-treatment",
    )

    assert result.outcome is TurnOutcome.SUCCESS
    assert decisions == 2
    assert result.after.world.revision == 2
    assert result.after.recent_events[0].operation_id == "retry-treatment"


def test_rejected_mutation_is_not_success(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    def decide(_action, _context):
        return TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_treat_and_discharge_patient",
                patient_id="patient-1",
                bed_id="bed-2",
            ),
        )

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="Treat the wrong patient.",
        decide=decide,
        operation_id_factory=lambda: "rejected-turn",
    )

    assert result.outcome is TurnOutcome.MUTATION_REJECTED
    assert result.mutation is None
    assert result.after.world.revision == 0


def test_decision_requires_exactly_one_supported_operation(tmp_path: Path) -> None:
    _ward_database(tmp_path)
    with pytest.raises(ValueError):
        TurnDecision(kind=DecisionKind.PERFORM_OPERATION)
    with pytest.raises(ValueError):
        TurnDecision(
            kind=DecisionKind.NARRATE,
            operation=OperationDecision(
                operation_type="world_treat_and_discharge_patient",
                patient_id="patient-1",
                bed_id="bed-1",
            ),
        )


def test_capability_gap_and_clarification_do_not_mutate(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    for kind, expected in [
        (DecisionKind.CAPABILITY_GAP, TurnOutcome.CAPABILITY_GAP),
        (DecisionKind.CLARIFICATION, TurnOutcome.CLARIFICATION),
    ]:
        result = run_turn(
            database_path,
            world_id=WARD_WORLD_ID,
            player_id="player",
            player_action="Do something unsupported.",
            decide=lambda _action, _context, kind=kind: TurnDecision(kind=kind),
            operation_id_factory=lambda: "unused",
        )
        assert result.outcome is expected
        assert result.after.world.revision == 0


def test_malformed_decision_output_is_a_controlled_invalid_action(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="Do something.",
        decide=lambda _action, _context: {"kind": "not-a-decision"},  # type: ignore[return-value]
        operation_id_factory=lambda: "malformed-decision",
    )

    assert result.outcome is TurnOutcome.INVALID_ACTION
    assert result.mutation is None
    assert result.after.world.revision == 0
    assert result.message is not None
