from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.persistence.database import connect_readonly_database
from backend.world.hierarchy import read_location_ancestors
from backend.world.links import read_linked_locations
from backend.world.location_memories import read_location_memories
from backend.world.locations import read_location_properties
from backend.world.queries import (
    LocationNotFound,
    WorldNotFound,
    get_location,
    get_player,
    list_recent_events,
)
from backend.world.resources import read_resources
from backend.world.social import read_social_context


class ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextWorld(ContextModel):
    id: str
    name: str
    revision: int = Field(ge=0)
    description: str | None = None
    source_scenario_id: str | None = None


class ContextPlayer(ContextModel):
    id: str
    world_id: str
    kind: str
    name: str
    role: str
    condition: str | None
    disposition: str
    location_id: str | None


class ContextEntity(ContextModel):
    id: str
    kind: str
    name: str
    role: str | None
    condition: str | None
    disposition: str | None


class ContextLocation(ContextModel):
    id: str
    world_id: str
    name: str
    description: str | None
    revision: int = Field(ge=0)
    entities: list[ContextEntity]
    properties: list[dict[str, Any]]
    memories: list[dict[str, Any]] = Field(default_factory=list)
    linked_locations: list[dict[str, Any]]


class ContextLocationReference(ContextModel):
    id: str
    name: str
    kind: str | None = None
    is_map_scope: bool = False
    is_default_scope: bool = False


class ContextEvent(ContextModel):
    id: str
    world_id: str
    operation_id: str
    event_type: str
    actor_entity_id: str | None
    summary: str
    payload: dict[str, Any]
    world_revision: int = Field(ge=1)
    occurred_at: str


class WorldContext(ContextModel):
    world: ContextWorld
    player: ContextPlayer
    current_location: ContextLocation
    location_breadcrumbs: list[ContextLocationReference] = Field(default_factory=list)
    map_scope: ContextLocationReference | None = None
    recent_events: list[ContextEvent]
    relationships: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    world_elements: list[dict[str, Any]] = Field(default_factory=list)


def build_world_context(
    database_path: str | Path,
    *,
    world_id: str,
    recent_event_limit: int = 10,
) -> WorldContext:
    """Build compact, scenario-neutral context from one SQLite snapshot."""
    if not 1 <= recent_event_limit <= 100:
        raise ValueError("recent event limit must be between 1 and 100")

    with closing(connect_readonly_database(database_path)) as connection:
        connection.execute("BEGIN")
        world = connection.execute(
            "SELECT id, name, revision, description, source_scenario_id FROM worlds WHERE id = ?",
            (world_id,),
        ).fetchone()
        if world is None:
            raise WorldNotFound(f"World {world_id!r} was not found")

        world_elements = connection.execute(
            "SELECT element_type, content FROM world_elements "
            "WHERE world_id = ? ORDER BY element_type",
            (world_id,),
        ).fetchall()

        player = get_player(database_path, world_id, _connection=connection)
        location_id = player["location_id"]
        if location_id is None:
            raise LocationNotFound(f"Player in world {world_id!r} has no current location")
        location = get_location(database_path, world_id, location_id, _connection=connection)
        location["properties"] = read_location_properties(
            database_path,
            world_id=world_id,
            location_ids=[location_id],
            _connection=connection,
        )["properties"]
        location["memories"] = read_location_memories(
            database_path,
            world_id=world_id,
            location_ids=[location_id],
            _connection=connection,
        )
        location["linked_locations"] = read_linked_locations(
            database_path,
            world_id=world_id,
            location_id=location_id,
            _connection=connection,
        )["linked_locations"]
        ancestors = read_location_ancestors(
            database_path,
            world_id=world_id,
            location_id=location_id,
            _connection=connection,
        )
        current_metadata = connection.execute(
            """
            SELECT l.id, l.name, m.kind,
                   COALESCE(m.is_map_scope, 0) AS is_map_scope,
                   COALESCE(m.is_default_scope, 0) AS is_default_scope
            FROM locations l
            LEFT JOIN location_metadata m
              ON m.world_id = l.world_id AND m.location_id = l.id
            WHERE l.world_id = ? AND l.id = ?
            """,
            (world_id, location_id),
        ).fetchone()
        reference_keys = ("id", "name", "kind", "is_map_scope", "is_default_scope")
        scope_candidates = [
            {key: dict(current_metadata)[key] for key in reference_keys},
            *[{key: ancestor[key] for key in reference_keys} for ancestor in reversed(ancestors)],
        ]
        map_scope = next(
            (candidate for candidate in scope_candidates if candidate["is_default_scope"]),
            None,
        )
        if map_scope is None:
            map_scope = next(
                (candidate for candidate in scope_candidates if candidate["is_map_scope"]),
                None,
            )
        events = list_recent_events(
            database_path,
            world_id,
            limit=recent_event_limit,
            _connection=connection,
        )
        social = read_social_context(
            database_path,
            world_id=world_id,
            viewer_entity_id=player["id"],
            related_entity_ids=[entity["id"] for entity in location["entities"]],
            _connection=connection,
        )
        resources = read_resources(
            database_path,
            world_id=world_id,
            owner_entity_ids=[entity["id"] for entity in location["entities"]] + [player["id"]],
            _connection=connection,
        )

    return WorldContext.model_validate(
        {
            "world": dict(world),
            "player": player,
            "current_location": location,
            "location_breadcrumbs": [
                {
                    key: ancestor[key]
                    for key in ("id", "name", "kind", "is_map_scope", "is_default_scope")
                }
                for ancestor in ancestors
            ],
            "map_scope": map_scope,
            "recent_events": events,
            "world_elements": [dict(element) for element in world_elements],
            **social,
            **resources,
        }
    )
