from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from backend.world.agent_tools import (
    inspect_entity,
    list_events,
    move_world_entity,
    read_world_status,
    record_world_social_interaction,
    treat_and_discharge_world_patient,
    validate_world_state,
)
from backend.world.context import build_world_context

mcp = FastMCP(
    "Mutable Realms World Tools",
    instructions=(
        "Inspect and mutate authoritative Mutable Realms state. Read context before "
        "choosing an operation, supply the observed world revision to mutations, "
        "and read state again before narrating a result."
    ),
)

EventLimit = Annotated[int, Field(ge=1, le=100)]


def get_database_path() -> Path:
    """Resolve the server-bound authoritative database without creating it."""
    configured = os.environ.get("MUTABLE_REALMS_DB_PATH")
    if not configured:
        raise RuntimeError("MUTABLE_REALMS_DB_PATH is required")
    path = Path(configured).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError(f"authoritative database does not exist: {path}")
    return path


def get_session_binding() -> tuple[str, str] | None:
    """Return optional trusted narration binding from process configuration."""
    world_id = os.environ.get("MUTABLE_REALMS_WORLD_ID")
    player_id = os.environ.get("MUTABLE_REALMS_PLAYER_ID")
    if (world_id is None) != (player_id is None):
        raise RuntimeError(
            "MUTABLE_REALMS_WORLD_ID and MUTABLE_REALMS_PLAYER_ID must be configured together"
        )
    if world_id is None or player_id is None:
        return None
    if not world_id.strip() or not player_id.strip():
        raise RuntimeError("trusted world and player binding must not be blank")
    return world_id, player_id


def resolve_world_id(requested_world_id: str) -> str:
    """Reject caller-selected worlds when a narration session is bound."""
    binding = get_session_binding()
    if binding is not None and requested_world_id != binding[0]:
        raise RuntimeError("requested world is outside the trusted narration session")
    return requested_world_id


def resolve_actor_entity_id(requested_actor_entity_id: str | None) -> str | None:
    """Use the trusted session player instead of a caller-selected actor."""
    binding = get_session_binding()
    if binding is None:
        return requested_actor_entity_id
    if requested_actor_entity_id is not None and requested_actor_entity_id != binding[1]:
        raise RuntimeError("requested actor is outside the trusted narration session")
    return binding[1]


def ensure_bound_player(world_id: str) -> None:
    """Verify that the configured player is the world's authoritative player."""
    binding = get_session_binding()
    if binding is not None:
        context = build_world_context(get_database_path(), world_id=resolve_world_id(world_id))
        if context.player.id != binding[1]:
            raise RuntimeError("trusted player is not bound to the requested world")


@mcp.tool()
def world_status(world_id: str) -> dict[str, Any]:
    """Read world identity, current revision, and supported mutation tool names."""
    ensure_bound_player(world_id)
    return read_world_status(get_database_path(), world_id=resolve_world_id(world_id))


@mcp.tool()
def world_context(world_id: str, event_limit: EventLimit = 10) -> dict[str, Any]:
    """Build bounded, deterministic context for the world's next player turn."""
    ensure_bound_player(world_id)
    return build_world_context(
        get_database_path(), world_id=resolve_world_id(world_id), recent_event_limit=event_limit
    ).model_dump()


@mcp.tool()
def world_inspect_entity(world_id: str, entity_id: str) -> dict[str, Any]:
    """Read one entity's authoritative generic state and current placement."""
    ensure_bound_player(world_id)
    return inspect_entity(
        get_database_path(), world_id=resolve_world_id(world_id), entity_id=entity_id
    )


@mcp.tool()
def world_events(world_id: str, limit: EventLimit = 10) -> dict[str, list[dict[str, Any]]]:
    """Read the newest persisted world events, bounded to 1-100 rows."""
    ensure_bound_player(world_id)
    return {
        "events": list_events(get_database_path(), world_id=resolve_world_id(world_id), limit=limit)
    }


@mcp.tool()
def world_move_entity(
    world_id: str,
    operation_id: str,
    expected_revision: int,
    entity_id: str,
    destination_location_id: str,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Atomically move an entity using an idempotency key and observed revision."""
    ensure_bound_player(world_id)
    return move_world_entity(
        get_database_path(),
        world_id=resolve_world_id(world_id),
        operation_id=operation_id,
        expected_revision=expected_revision,
        entity_id=entity_id,
        destination_location_id=destination_location_id,
        actor_entity_id=resolve_actor_entity_id(actor_entity_id),
    )


@mcp.tool()
def world_treat_and_discharge_patient(
    world_id: str,
    operation_id: str,
    expected_revision: int,
    patient_id: str,
    bed_id: str,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Atomically recover and discharge an admitted patient from their ward bed."""
    ensure_bound_player(world_id)
    return treat_and_discharge_world_patient(
        get_database_path(),
        world_id=resolve_world_id(world_id),
        operation_id=operation_id,
        expected_revision=expected_revision,
        patient_id=patient_id,
        bed_id=bed_id,
        actor_entity_id=resolve_actor_entity_id(actor_entity_id),
    )


@mcp.tool()
def world_record_social_interaction(
    world_id: str,
    operation_id: str,
    expected_revision: int,
    subject_entity_id: str,
    object_entity_id: str,
    relationship_category: str,
    relationship_delta: Annotated[int, Field(ge=-100, le=100)],
    memory: Annotated[str, Field(min_length=1, max_length=500)],
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Atomically update one relationship and store one concise linked memory."""
    ensure_bound_player(world_id)
    actor = resolve_actor_entity_id(actor_entity_id)
    if actor is None:
        raise RuntimeError("social interaction requires a trusted actor")
    return record_world_social_interaction(
        get_database_path(),
        world_id=resolve_world_id(world_id),
        operation_id=operation_id,
        expected_revision=expected_revision,
        actor_entity_id=actor,
        subject_entity_id=subject_entity_id,
        object_entity_id=object_entity_id,
        relationship_category=relationship_category,
        relationship_delta=relationship_delta,
        memory=memory,
    )


@mcp.tool()
def world_validate() -> dict[str, Any]:
    """Check all authoritative worlds and return structured invariant violations."""
    if get_session_binding() is not None:
        raise RuntimeError("world validation is only available on an unbound administration server")
    return validate_world_state(get_database_path())


def main() -> None:
    """Run the native Hermes-compatible MCP server over standard I/O."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
