from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from backend.world.agent_tools import (
    expand_world_location,
    inspect_entity,
    list_events,
    move_world_entity,
    read_world_status,
    record_world_social_interaction,
    transfer_world_resource,
    travel_world_route,
    treat_and_discharge_world_patient,
    update_world_location,
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


def resolve_world_id(requested_world_id: str | None) -> str:
    """Resolve the world for a tool call.

    An explicit ``world_id`` argument wins; otherwise the session binding's
    world is used when one is configured. Any world may be selected — the
    narration prompt tells the agent which world is authoritative for the
    turn, and the underlying operations validate their own preconditions.
    """
    if requested_world_id is not None:
        world_id = requested_world_id.strip()
        if not world_id:
            raise RuntimeError("world_id must not be blank")
        return world_id
    binding = get_session_binding()
    if binding is None:
        raise RuntimeError("world_id is required when no session binding is configured")
    return binding[0]


def resolve_actor_entity_id(requested_actor_entity_id: str | None) -> str | None:
    """Resolve the acting entity: explicit actor wins, else the session player."""
    if requested_actor_entity_id is not None:
        return requested_actor_entity_id
    binding = get_session_binding()
    if binding is None:
        return None
    return binding[1]


@mcp.tool()
def world_status(world_id: str | None = None) -> dict[str, Any]:
    """Read world identity, current revision, and supported mutation tool names."""
    return read_world_status(get_database_path(), world_id=resolve_world_id(world_id))


@mcp.tool()
def world_context(world_id: str | None = None, event_limit: EventLimit = 10) -> dict[str, Any]:
    """Build bounded, deterministic context for the world's next player turn."""
    return build_world_context(
        get_database_path(), world_id=resolve_world_id(world_id), recent_event_limit=event_limit
    ).model_dump()


@mcp.tool()
def world_inspect_entity(
    world_id: str | None = None, entity_id: str | None = None
) -> dict[str, Any]:
    """Read one entity's authoritative generic state and current placement."""
    if entity_id is None:
        raise RuntimeError("entity_id is required")
    return inspect_entity(
        get_database_path(), world_id=resolve_world_id(world_id), entity_id=entity_id
    )


@mcp.tool()
def world_events(
    world_id: str | None = None, limit: EventLimit = 10
) -> dict[str, list[dict[str, Any]]]:
    """Read the newest persisted world events, bounded to 1-100 rows."""
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
def world_travel_route(
    world_id: str,
    operation_id: str,
    expected_revision: int,
    route_id: str,
    entity_id: str,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Travel a character along one explicit active route."""
    return travel_world_route(
        get_database_path(),
        world_id=resolve_world_id(world_id),
        route_id=route_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        entity_id=entity_id,
        actor_entity_id=resolve_actor_entity_id(actor_entity_id),
    )


@mcp.tool()
def world_expand_location(
    world_id: str,
    operation_id: str,
    expected_revision: int,
    proposal_id: str,
    location_id: str,
    anchor_location_id: str,
    name: Annotated[str, Field(min_length=1, max_length=200)],
    description: Annotated[str, Field(max_length=2000)] = "",
    parent_location_id: str | None = None,
    connect_to_anchor: bool = False,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Accept one bounded structured proposal for a new ordinary location."""
    return expand_world_location(
        get_database_path(),
        world_id=resolve_world_id(world_id),
        operation_id=operation_id,
        expected_revision=expected_revision,
        proposal_id=proposal_id,
        location_id=location_id,
        anchor_location_id=anchor_location_id,
        name=name,
        description=description,
        parent_location_id=parent_location_id,
        connect_to_anchor=connect_to_anchor,
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
def world_transfer_resource(
    world_id: str,
    operation_id: str,
    expected_revision: int,
    recipient_entity_id: str,
    resource_type: Annotated[str, Field(min_length=1, max_length=100)],
    quantity: Annotated[int, Field(ge=1)],
    source_entity_id: str | None = None,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Atomically grant or transfer resource units between characters."""
    actor = resolve_actor_entity_id(actor_entity_id)
    if actor is None:
        raise RuntimeError("resource transfer requires a trusted actor")
    return transfer_world_resource(
        get_database_path(),
        world_id=resolve_world_id(world_id),
        operation_id=operation_id,
        expected_revision=expected_revision,
        actor_entity_id=actor,
        recipient_entity_id=recipient_entity_id,
        resource_type=resource_type,
        quantity=quantity,
        source_entity_id=source_entity_id,
    )


@mcp.tool()
def world_update_location(
    world_id: str,
    operation_id: str,
    expected_revision: int,
    location_id: str,
    display_name: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
    property: Annotated[str | None, Field(min_length=1, max_length=50)] = None,
    value: Annotated[int | None, Field(ge=0, le=100)] = None,
    actor_entity_id: str | None = None,
) -> dict[str, Any]:
    """Atomically rename a location and/or set one bounded property value."""
    actor = resolve_actor_entity_id(actor_entity_id)
    if actor is None:
        raise RuntimeError("location update requires a trusted actor")
    return update_world_location(
        get_database_path(),
        world_id=resolve_world_id(world_id),
        operation_id=operation_id,
        expected_revision=expected_revision,
        actor_entity_id=actor,
        location_id=location_id,
        display_name=display_name,
        property=property,
        value=value,
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
