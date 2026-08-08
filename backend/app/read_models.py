from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class TurnRequest(StrictReadModel):
    player_id: str
    player_action: str = Field(min_length=1)
    decision_json: str | None = None

    @field_validator("player_action")
    @classmethod
    def _player_action_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("player_action must not be blank")
        return value


class TurnResponse(StrictReadModel):
    outcome: str
    message: str | None = None
    narration: str | None = None
    revision_before: int | None = Field(default=None, ge=0)
    revision_after: int | None = Field(default=None, ge=0)
    attempts: int = Field(default=1, ge=1)
    mutation: dict[str, Any] | None = None


class ScenarioElementRead(StrictReadModel):
    element_type: str
    content: str
    updated_at: str


class ScenarioRead(StrictReadModel):
    id: str
    title: str
    description: str | None
    created_at: str
    elements: list[ScenarioElementRead] = Field(default_factory=list)


class ScenarioCreateRequest(StrictReadModel):
    scenario_id: str
    title: str = Field(min_length=1)
    description: str | None = None
    operation_id: str


class ScenarioUpdateRequest(StrictReadModel):
    title: str | None = None
    description: str | None = None
    operation_id: str


class ScenarioElementRequest(StrictReadModel):
    content: str = Field(min_length=1)
    operation_id: str


class ScenarioMutationResponse(StrictReadModel):
    already_applied: bool
    scenario_id: str
