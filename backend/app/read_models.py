from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorldRead(StrictReadModel):
    id: str
    name: str
    revision: int = Field(ge=0)


class PlayerRead(StrictReadModel):
    id: str
    world_id: str
    kind: str
    name: str
    role: str
    condition: str | None
    disposition: str
    location_id: str | None


class LocationEntityRead(StrictReadModel):
    id: str
    kind: str
    name: str
    role: str | None
    condition: str | None
    disposition: str | None


class LocationRead(StrictReadModel):
    id: str
    world_id: str
    name: str
    description: str | None
    revision: int = Field(ge=0)
    entities: list[LocationEntityRead]


class EntityRead(StrictReadModel):
    id: str
    world_id: str
    kind: str
    name: str
    location_id: str | None
    role: str | None
    condition: str | None
    disposition: str | None


class WorldEventRead(StrictReadModel):
    id: str
    world_id: str
    operation_id: str
    event_type: str
    actor_entity_id: str | None
    summary: str
    payload: dict[str, Any]
    world_revision: int = Field(ge=1)
    occurred_at: str


class WorldMapLocationRead(StrictReadModel):
    id: str
    name: str
    description: str | None
    entity_kinds: dict[str, int]
    linked_location_ids: list[str]


class WorldMapRead(StrictReadModel):
    world: WorldRead
    player_location_id: str | None
    locations: list[WorldMapLocationRead]


class HealthRead(StrictReadModel):
    status: str
    database: str
