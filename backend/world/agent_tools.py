from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_readonly_database
from backend.scenarios.ward.mutations import treat_and_discharge_patient
from backend.world.locations import update_location
from backend.world.mutations import move_entity
from backend.world.queries import WorldNotFound, get_entity, list_recent_events
from backend.world.resources import transfer_resource
from backend.world.social import record_social_interaction
from backend.world.validation import validate_worlds


def read_world_status(database_path: str | Path, *, world_id: str) -> dict[str, Any]:
    """Return concise world metadata and mutations supported by its capabilities."""
    with connect_readonly_database(database_path) as connection:
        world = connection.execute(
            "SELECT id, name, revision FROM worlds WHERE id = ?", (world_id,)
        ).fetchone()
        if world is None:
            raise WorldNotFound(f"World {world_id!r} was not found")
        has_ward_state = (
            connection.execute(
                """
                SELECT 1
                FROM beds b
                JOIN entities e ON e.id = b.entity_id
                WHERE e.world_id = ?
                LIMIT 1
                """,
                (world_id,),
            ).fetchone()
            is not None
        )
        has_social_state = (
            connection.execute(
                """SELECT 1 FROM characters c
            JOIN entities e ON e.id = c.entity_id
            WHERE e.world_id = ? LIMIT 1 OFFSET 1""",
                (world_id,),
            ).fetchone()
            is not None
        )
        has_characters = (
            connection.execute(
                """SELECT 1 FROM characters c
            JOIN entities e ON e.id = c.entity_id
            WHERE e.world_id = ? LIMIT 1""",
                (world_id,),
            ).fetchone()
            is not None
        )
        has_locations = (
            connection.execute(
                "SELECT 1 FROM locations WHERE world_id = ? LIMIT 1", (world_id,)
            ).fetchone()
            is not None
        )

    mutations = ["world_move_entity"]
    if has_ward_state:
        mutations.append("world_treat_and_discharge_patient")
    if has_social_state:
        mutations.append("world_record_social_interaction")
    if has_characters:
        mutations.append("world_transfer_resource")
    if has_locations:
        mutations.append("world_update_location")
    return {"world": dict(world), "available_mutations": mutations}


def inspect_entity(database_path: str | Path, *, world_id: str, entity_id: str) -> dict[str, Any]:
    """Inspect one generic entity through the authoritative read service."""
    return get_entity(database_path, world_id, entity_id)


def list_events(
    database_path: str | Path, *, world_id: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Read bounded newest-first events through the authoritative read service."""
    return list_recent_events(database_path, world_id, limit=limit)


def move_world_entity(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    entity_id: str,
    destination_location_id: str,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Apply the existing idempotent, revision-checked movement operation."""
    result = move_entity(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        entity_id=entity_id,
        destination_location_id=destination_location_id,
        actor_entity_id=actor_entity_id,
    )
    return {
        "already_applied": result.already_applied,
        "entity_id": result.entity_id,
        "location_id": result.location_id,
        "world_revision": result.world_revision,
    }


def treat_and_discharge_world_patient(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    patient_id: str,
    bed_id: str,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Apply the ward's atomic treatment-and-discharge operation."""
    result = treat_and_discharge_patient(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        patient_id=patient_id,
        bed_id=bed_id,
        actor_entity_id=actor_entity_id,
    )
    return {
        "already_applied": result.already_applied,
        "world_revision": result.world_revision,
    }


def record_world_social_interaction(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    actor_entity_id: str,
    subject_entity_id: str,
    object_entity_id: str,
    relationship_category: str,
    relationship_delta: int,
    memory: str,
) -> dict[str, Any]:
    """Atomically persist one relationship change and concise event-linked memory."""
    return record_social_interaction(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        actor_entity_id=actor_entity_id,
        subject_entity_id=subject_entity_id,
        object_entity_id=object_entity_id,
        relationship_category=relationship_category,
        relationship_delta=relationship_delta,
        memory=memory,
    )


def transfer_world_resource(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    actor_entity_id: str,
    recipient_entity_id: str,
    resource_type: str,
    quantity: int,
    source_entity_id: str | None = None,
) -> dict[str, Any]:
    """Apply the resource grant/transfer application operation."""
    return transfer_resource(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        actor_entity_id=actor_entity_id,
        recipient_entity_id=recipient_entity_id,
        resource_type=resource_type,
        quantity=quantity,
        source_entity_id=source_entity_id,
    )


def update_world_location(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    actor_entity_id: str,
    location_id: str,
    display_name: str | None = None,
    property: str | None = None,
    value: int | None = None,
) -> dict[str, Any]:
    """Apply the location rename/property application operation."""
    return update_location(
        database_path,
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        actor_entity_id=actor_entity_id,
        location_id=location_id,
        display_name=display_name,
        property=property,
        value=value,
    )


def validate_world_state(database_path: str | Path) -> dict[str, Any]:
    """Return deterministic validation results in an agent-friendly structure."""
    issues = [asdict(issue) for issue in validate_worlds(database_path)]
    return {"valid": not issues, "issues": issues}
