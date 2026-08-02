from __future__ import annotations

import json
from pathlib import Path

from backend.persistence.database import connect_database
from backend.world.mutations import (
    MutationConflict,
    MutationNotFound,
    MutationResult,
    StaleWorldRevision,
    event_id,
)

_EVENT_TYPE = "patient_treated_and_discharged"


def treat_and_discharge_patient(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    patient_id: str,
    bed_id: str,
    actor_entity_id: str | None = None,
) -> MutationResult:
    """Atomically recover and discharge one ward patient."""
    if not operation_id.strip():
        raise MutationConflict("operation ID must not be blank")

    payload = {
        "bed_id": bed_id,
        "patient_id": patient_id,
    }
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    request_json = json.dumps(
        {
            **payload,
            "actor_entity_id": actor_entity_id,
            "expected_revision": expected_revision,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                """
                SELECT operation_type, request_json, result_json, completed_revision
                FROM operations
                WHERE world_id = ? AND operation_id = ?
                """,
                (world_id, operation_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["operation_type"] != _EVENT_TYPE
                    or existing["request_json"] != request_json
                ):
                    raise MutationConflict(
                        "operation ID was already used for a different request"
                    )
                connection.rollback()
                stored_result = json.loads(existing["result_json"])
                return MutationResult(
                    stored_result["world_revision"], already_applied=True
                )

            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise MutationNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise StaleWorldRevision(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )

            patient = connection.execute(
                """
                SELECT c.condition, c.disposition
                FROM characters c
                JOIN entities e ON e.id = c.entity_id
                WHERE c.entity_id = ? AND e.world_id = ? AND c.role = 'patient'
                """,
                (patient_id, world_id),
            ).fetchone()
            if patient is None:
                raise MutationNotFound(f"patient not found: {patient_id}")
            if patient["disposition"] != "admitted":
                raise MutationConflict(f"patient is not admitted: {patient_id}")

            bed = connection.execute(
                """
                SELECT b.occupant_entity_id, b.location_id
                FROM beds b
                JOIN entities e ON e.id = b.entity_id
                WHERE b.entity_id = ? AND e.world_id = ?
                """,
                (bed_id, world_id),
            ).fetchone()
            if bed is None:
                raise MutationNotFound(f"bed not found: {bed_id}")
            if bed["occupant_entity_id"] != patient_id:
                raise MutationConflict(f"patient {patient_id} does not occupy bed {bed_id}")

            placement = connection.execute(
                "SELECT location_id FROM entity_locations WHERE entity_id = ?",
                (patient_id,),
            ).fetchone()
            if placement is None or placement["location_id"] != bed["location_id"]:
                raise MutationConflict(
                    f"patient {patient_id} is not placed at bed {bed_id}'s location"
                )

            if actor_entity_id is not None:
                actor = connection.execute(
                    "SELECT 1 FROM entities WHERE id = ? AND world_id = ?",
                    (actor_entity_id, world_id),
                ).fetchone()
                if actor is None:
                    raise MutationNotFound(f"actor not found: {actor_entity_id}")

            next_revision = expected_revision + 1
            connection.execute(
                """
                UPDATE characters
                SET condition = 'recovered', disposition = 'discharged'
                WHERE entity_id = ?
                """,
                (patient_id,),
            )
            connection.execute(
                "UPDATE beds SET occupant_entity_id = NULL WHERE entity_id = ?",
                (bed_id,),
            )
            connection.execute(
                "DELETE FROM entity_locations WHERE entity_id = ?",
                (patient_id,),
            )
            revision_update = connection.execute(
                "UPDATE worlds SET revision = ? WHERE id = ? AND revision = ?",
                (next_revision, world_id, expected_revision),
            )
            if revision_update.rowcount != 1:
                raise StaleWorldRevision("world revision changed during mutation")

            result_json = json.dumps(
                {"world_revision": next_revision}, separators=(",", ":")
            )
            connection.execute(
                """
                INSERT INTO operations(
                    world_id, operation_id, operation_type, request_json,
                    result_json, completed_revision
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    world_id,
                    operation_id,
                    _EVENT_TYPE,
                    request_json,
                    result_json,
                    next_revision,
                ),
            )
            connection.execute(
                """
                INSERT INTO events(
                    id, world_id, operation_id, event_type, actor_entity_id,
                    summary, payload_json, world_revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id(world_id, operation_id),
                    world_id,
                    operation_id,
                    _EVENT_TYPE,
                    actor_entity_id,
                    f"{patient_id} recovered and was discharged from {bed_id}",
                    payload_json,
                    next_revision,
                ),
            )
            connection.commit()
            return MutationResult(next_revision, already_applied=False)
        except Exception:
            connection.rollback()
            raise
