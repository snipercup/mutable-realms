from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from backend.world.agent_tools import (
    move_world_entity,
    read_world_status,
    record_world_social_interaction,
    transfer_world_resource,
    treat_and_discharge_world_patient,
)
from backend.world.context import WorldContext, build_world_context
from backend.world.mutations import (
    MutationConflict,
    MutationNotFound,
    StaleWorldRevision,
)
from backend.world.resources import ResourceConflict, ResourceNotFound
from backend.world.social import SocialConflict, SocialNotFound


class DecisionKind(StrEnum):
    NARRATE = "narrate_without_mutation"
    PERFORM_OPERATION = "perform_one_supported_operation"
    CLARIFICATION = "request_clarification"
    CAPABILITY_GAP = "capability_gap"


OperationType = Literal[
    "world_move_entity",
    "world_treat_and_discharge_patient",
    "world_record_social_interaction",
    "world_transfer_resource",
]


class OperationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_type: OperationType
    entity_id: str | None = None
    destination_location_id: str | None = None
    patient_id: str | None = None
    bed_id: str | None = None
    subject_entity_id: str | None = None
    object_entity_id: str | None = None
    relationship_category: str | None = None
    relationship_delta: int | None = None
    memory: str | None = None
    recipient_entity_id: str | None = None
    resource_type: str | None = None
    quantity: int | None = None
    source_entity_id: str | None = None

    @model_validator(mode="after")
    def require_operation_arguments(self) -> OperationDecision:
        resource_args = (
            self.recipient_entity_id,
            self.resource_type,
            self.quantity is not None,
            self.source_entity_id,
        )
        if self.operation_type == "world_move_entity":
            if any(
                (
                    self.patient_id,
                    self.bed_id,
                    self.subject_entity_id,
                    self.object_entity_id,
                    self.relationship_category,
                    self.relationship_delta is not None,
                    self.memory,
                    *resource_args,
                )
            ):
                raise ValueError("move operation cannot include unrelated arguments")
            if not self.entity_id or not self.destination_location_id:
                raise ValueError("world_move_entity requires entity_id and destination_location_id")
        elif self.operation_type == "world_treat_and_discharge_patient":
            if self.entity_id is not None or self.destination_location_id is not None:
                raise ValueError("ward operation cannot include movement arguments")
            if any(
                (
                    self.subject_entity_id,
                    self.object_entity_id,
                    self.relationship_category,
                    self.relationship_delta is not None,
                    self.memory,
                    *resource_args,
                )
            ):
                raise ValueError("ward operation cannot include social or resource arguments")
            if not self.patient_id or not self.bed_id:
                raise ValueError("world_treat_and_discharge_patient requires patient_id and bed_id")
        elif self.operation_type == "world_record_social_interaction":
            if any((self.entity_id, self.destination_location_id, self.patient_id, self.bed_id)):
                raise ValueError("social operation cannot include movement or ward arguments")
            if any(resource_args):
                raise ValueError("social operation cannot include resource arguments")
            if (
                not self.subject_entity_id
                or not self.object_entity_id
                or not self.relationship_category
                or self.relationship_delta is None
                or not self.memory
            ):
                raise ValueError("social operation requires relationship and memory arguments")
        else:
            if any(
                (
                    self.entity_id,
                    self.destination_location_id,
                    self.patient_id,
                    self.bed_id,
                    self.subject_entity_id,
                    self.object_entity_id,
                    self.relationship_category,
                    self.relationship_delta is not None,
                    self.memory,
                )
            ):
                raise ValueError(
                    "resource operation cannot include movement, ward, or social arguments"
                )
            if (
                not self.recipient_entity_id
                or not self.resource_type
                or self.quantity is None
                or self.quantity <= 0
            ):
                raise ValueError(
                    "world_transfer_resource requires recipient_entity_id, resource_type, "
                    "and a positive quantity"
                )
        return self


class TurnDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DecisionKind
    operation: OperationDecision | None = None
    message: str | None = None

    @model_validator(mode="after")
    def require_decision_shape(self) -> TurnDecision:
        if self.kind is DecisionKind.PERFORM_OPERATION and self.operation is None:
            raise ValueError("perform_one_supported_operation requires operation")
        if self.kind is not DecisionKind.PERFORM_OPERATION and self.operation is not None:
            raise ValueError("only operation decisions may include an operation")
        return self


class TurnOutcome(StrEnum):
    NO_MUTATION = "no_mutation"
    SUCCESS = "success"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    CLARIFICATION = "clarification"
    CAPABILITY_GAP = "capability_gap"
    INVALID_ACTION = "invalid_action"
    MISSING_RESOURCE = "missing_resource"
    MUTATION_REJECTED = "mutation_rejected"
    STALE_REVISION = "stale_revision"
    TOOL_FAILURE = "tool_failure"


@dataclass(frozen=True)
class TurnResult:
    outcome: TurnOutcome
    before: WorldContext
    after: WorldContext
    decision: TurnDecision
    mutation: dict[str, object] | None
    message: str | None
    attempts: int


DecisionProvider = Callable[[str, WorldContext], TurnDecision | dict[str, object]]
OperationIdFactory = Callable[[], str]


def _result(
    outcome: TurnOutcome,
    before: WorldContext,
    after: WorldContext,
    decision: TurnDecision,
    *,
    mutation: dict[str, object] | None = None,
    message: str | None = None,
    attempts: int,
) -> TurnResult:
    return TurnResult(
        outcome=outcome,
        before=before,
        after=after,
        decision=decision,
        mutation=mutation,
        message=message or decision.message,
        attempts=attempts,
    )


def _execute_operation(
    database_path: str | Path,
    *,
    world_id: str,
    player_id: str,
    operation_id: str,
    expected_revision: int,
    operation: OperationDecision,
) -> dict[str, object]:
    if operation.operation_type == "world_move_entity":
        assert operation.entity_id is not None
        assert operation.destination_location_id is not None
        result = move_world_entity(
            database_path,
            world_id=world_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            entity_id=operation.entity_id,
            destination_location_id=operation.destination_location_id,
            actor_entity_id=player_id,
        )
        return {
            "already_applied": result["already_applied"],
            "entity_id": result["entity_id"],
            "location_id": result["location_id"],
            "world_revision": result["world_revision"],
        }

    if operation.operation_type == "world_treat_and_discharge_patient":
        assert operation.patient_id is not None
        assert operation.bed_id is not None
        result = treat_and_discharge_world_patient(
            database_path,
            world_id=world_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            patient_id=operation.patient_id,
            bed_id=operation.bed_id,
            actor_entity_id=player_id,
        )
        return {
            "already_applied": result["already_applied"],
            "world_revision": result["world_revision"],
        }

    if operation.operation_type == "world_transfer_resource":
        assert operation.recipient_entity_id is not None
        assert operation.resource_type is not None
        assert operation.quantity is not None
        result = transfer_world_resource(
            database_path,
            world_id=world_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            actor_entity_id=player_id,
            recipient_entity_id=operation.recipient_entity_id,
            resource_type=operation.resource_type,
            quantity=operation.quantity,
            source_entity_id=operation.source_entity_id,
        )
        return {
            "already_applied": result["already_applied"],
            "world_revision": result["world_revision"],
        }

    assert operation.subject_entity_id is not None
    assert operation.object_entity_id is not None
    assert operation.relationship_category is not None
    assert operation.relationship_delta is not None
    assert operation.memory is not None
    return record_world_social_interaction(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        actor_entity_id=player_id,
        subject_entity_id=operation.subject_entity_id,
        object_entity_id=operation.object_entity_id,
        relationship_category=operation.relationship_category,
        relationship_delta=operation.relationship_delta,
        memory=operation.memory,
    )


def run_turn(
    database_path: str | Path,
    *,
    world_id: str,
    player_id: str,
    player_action: str,
    decide: DecisionProvider,
    operation_id_factory: OperationIdFactory | None = None,
) -> TurnResult:
    """Execute one structured narrated turn without giving model code storage access.

    ``decide`` is the model-facing seam: it receives trusted context and untrusted
    player text, and must return a validated ``TurnDecision``. This function owns
    session binding, capability checks, operation identity, stale-revision retry,
    mutation dispatch, and authoritative post-turn rereading.
    """
    operation_id = (operation_id_factory or (lambda: f"turn-{uuid4()}"))()
    before = build_world_context(database_path, world_id=world_id)
    if before.player.id != player_id:
        raise ValueError("player_id does not match the world's bound player")

    attempts = 0
    while True:
        attempts += 1
        status = read_world_status(database_path, world_id=world_id)
        try:
            decision = TurnDecision.model_validate(decide(player_action, before))
        except ValidationError as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.INVALID_ACTION,
                before,
                after,
                TurnDecision(
                    kind=DecisionKind.CAPABILITY_GAP,
                    message=f"decision output was invalid: {error}",
                ),
                message="decision output was invalid",
                attempts=attempts,
            )

        if decision.kind is DecisionKind.NARRATE:
            after = build_world_context(database_path, world_id=world_id)
            return _result(TurnOutcome.NO_MUTATION, before, after, decision, attempts=attempts)
        if decision.kind is DecisionKind.CLARIFICATION:
            after = build_world_context(database_path, world_id=world_id)
            return _result(TurnOutcome.CLARIFICATION, before, after, decision, attempts=attempts)
        if decision.kind is DecisionKind.CAPABILITY_GAP:
            after = build_world_context(database_path, world_id=world_id)
            return _result(TurnOutcome.CAPABILITY_GAP, before, after, decision, attempts=attempts)

        assert decision.operation is not None
        if decision.operation.operation_type not in status["available_mutations"]:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.CAPABILITY_GAP,
                before,
                after,
                decision,
                message="requested operation is not advertised for this world",
                attempts=attempts,
            )

        try:
            mutation = _execute_operation(
                database_path,
                world_id=world_id,
                player_id=player_id,
                operation_id=operation_id,
                expected_revision=before.world.revision,
                operation=decision.operation,
            )
        except StaleWorldRevision as error:
            if attempts >= 2:
                after = build_world_context(database_path, world_id=world_id)
                return _result(
                    TurnOutcome.STALE_REVISION,
                    before,
                    after,
                    decision,
                    message=str(error),
                    attempts=attempts,
                )
            before = build_world_context(database_path, world_id=world_id)
            continue
        except MutationNotFound as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.MISSING_RESOURCE,
                before,
                after,
                decision,
                message=str(error),
                attempts=attempts,
            )
        except SocialNotFound as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.MISSING_RESOURCE,
                before,
                after,
                decision,
                message=str(error),
                attempts=attempts,
            )
        except ResourceNotFound as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.MISSING_RESOURCE,
                before,
                after,
                decision,
                message=str(error),
                attempts=attempts,
            )
        except MutationConflict as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.MUTATION_REJECTED,
                before,
                after,
                decision,
                message=str(error),
                attempts=attempts,
            )
        except SocialConflict as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.MUTATION_REJECTED,
                before,
                after,
                decision,
                message=str(error),
                attempts=attempts,
            )
        except ResourceConflict as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.MUTATION_REJECTED,
                before,
                after,
                decision,
                message=str(error),
                attempts=attempts,
            )
        except (AssertionError, ValueError) as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.INVALID_ACTION,
                before,
                after,
                decision,
                message=str(error),
                attempts=attempts,
            )
        except Exception as error:
            after = build_world_context(database_path, world_id=world_id)
            return _result(
                TurnOutcome.TOOL_FAILURE,
                before,
                after,
                decision,
                message=str(error),
                attempts=attempts,
            )

        after = build_world_context(database_path, world_id=world_id)
        outcome = (
            TurnOutcome.IDEMPOTENT_REPLAY if mutation["already_applied"] else TurnOutcome.SUCCESS
        )
        return _result(
            outcome,
            before,
            after,
            decision,
            mutation=mutation,
            attempts=attempts,
        )
