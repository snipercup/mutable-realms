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


@mcp.tool()
def world_status(world_id: str) -> dict[str, Any]:
    """Read world identity, current revision, and supported mutation tool names."""
    return read_world_status(get_database_path(), world_id=world_id)


@mcp.tool()
def world_context(world_id: str, event_limit: EventLimit = 10) -> dict[str, Any]:
    """Build bounded, deterministic context for the world's next player turn."""
    return build_world_context(
        get_database_path(), world_id=world_id, recent_event_limit=event_limit
    ).model_dump()


@mcp.tool()
def world_inspect_entity(world_id: str, entity_id: str) -> dict[str, Any]:
    """Read one entity's authoritative generic state and current placement."""
    return inspect_entity(
        get_database_path(), world_id=world_id, entity_id=entity_id
    )


@mcp.tool()
def world_events(
    world_id: str, limit: EventLimit = 10
) -> dict[str, list[dict[str, Any]]]:
    """Read the newest persisted world events, bounded to 1-100 rows."""
    return {"events": list_events(get_database_path(), world_id=world_id, limit=limit)}


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
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        entity_id=entity_id,
        destination_location_id=destination_location_id,
        actor_entity_id=actor_entity_id,
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
        world_id=world_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        patient_id=patient_id,
        bed_id=bed_id,
        actor_entity_id=actor_entity_id,
    )


@mcp.tool()
def world_validate() -> dict[str, Any]:
    """Check all authoritative worlds and return structured invariant violations."""
    return validate_world_state(get_database_path())


def main() -> None:
    """Run the native Hermes-compatible MCP server over standard I/O."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
