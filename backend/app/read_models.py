from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorldRead(StrictReadModel):
    id: str
    name: str
    revision: int = Field(ge=0)
    description: str | None = None
    source_scenario_id: str | None = None


class WorldElementRead(StrictReadModel):
    element_type: str
    content: str
    updated_at: str


class PlayerSummaryRead(StrictReadModel):
    id: str
    name: str
    basic_info: str | None = None
    character_definition_id: str | None = None
    location_id: str | None = None
    location_name: str | None = None


class PlayerCharacterRead(StrictReadModel):
    id: str
    name: str
    basic_info: str | None
    created_at: str


class WorldDetailRead(WorldRead):
    elements: list[WorldElementRead] = Field(default_factory=list)
    player: PlayerSummaryRead | None = None


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


class WorldCreateRequest(StrictReadModel):
    world_id: str
    scenario_id: str
    operation_id: str


class WorldCreateResponse(StrictReadModel):
    already_applied: bool
    world_id: str
    world_revision: int = Field(ge=1)
    source_scenario_id: str


class WorldUpdateRequest(StrictReadModel):
    title: str | None = None
    description: str | None = None
    operation_id: str
    expected_revision: int = Field(ge=0)


class WorldElementRequest(StrictReadModel):
    content: str = Field(min_length=1)
    operation_id: str
    expected_revision: int = Field(ge=0)


class WorldMutationResponse(StrictReadModel):
    already_applied: bool
    world_id: str
    world_revision: int = Field(ge=1)


class WorldProvisionRequest(StrictReadModel):
    player_name: str = Field(min_length=1)
    location_name: str = Field(min_length=1)
    operation_id: str
    expected_revision: int = Field(ge=0)


class PlayerCharacterCreateRequest(StrictReadModel):
    character_id: str
    name: str = Field(min_length=1)
    basic_info: str | None = None
    operation_id: str


class PlayerCharacterUpdateRequest(StrictReadModel):
    name: str | None = None
    basic_info: str | None = None
    operation_id: str


class PlayerCharacterMutationResponse(StrictReadModel):
    already_applied: bool
    character_id: str


class WorldCharacterInstanceRequest(StrictReadModel):
    character_id: str
    location_name: str = Field(min_length=1)
    location_description: str | None = None
    operation_id: str
    expected_revision: int = Field(ge=0)


class WorldStartRequest(StrictReadModel):
    character_id: str
    operation_id: str
    expected_revision: int = Field(ge=0)


class WorldStartResponse(StrictReadModel):
    outcome: str
    narration: str
    world_id: str
    character_id: str
    player_id: str
    location_id: str
    location_name: str
    revision_before: int = Field(ge=0)
    revision_after: int = Field(ge=0)
