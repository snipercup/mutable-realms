from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.app.narrator import (
    HermesNarrator,
    Narrator,
    NarratorError,
    NarratorStartResult,
    StartNarrator,
)
from backend.app.read_models import (
    EntityRead,
    ExpansionRequest,
    ExpansionResponse,
    LocationHierarchyMutationResponse,
    LocationHierarchyRequest,
    LocationRead,
    LocationScopePromotionMutationResponse,
    LocationScopePromotionRequest,
    NarrationEntryRead,
    NarrationHistoryRead,
    PlayerCharacterCreateRequest,
    PlayerCharacterMutationResponse,
    PlayerCharacterRead,
    PlayerCharacterUpdateRequest,
    PlayerRead,
    RouteTravelRequest,
    RouteTravelResponse,
    ScenarioCreateRequest,
    ScenarioElementRequest,
    ScenarioMutationResponse,
    ScenarioRead,
    ScenarioRegionRequest,
    ScenarioUpdateRequest,
    TurnRequest,
    TurnResponse,
    WorldCharacterInstanceRequest,
    WorldCreateRequest,
    WorldCreateResponse,
    WorldDetailRead,
    WorldElementRequest,
    WorldEventRead,
    WorldMapRead,
    WorldMutationResponse,
    WorldProvisionRequest,
    WorldRead,
    WorldRouteMutationResponse,
    WorldRouteRequest,
    WorldStartRequest,
    WorldStartResponse,
    WorldUpdateRequest,
)
from backend.persistence.database import connect_database
from backend.persistence.migrations import (
    MigrationError,
    migrate_database,
    verify_database_schema,
)
from backend.scenarios.ward.queries import (
    WardCapabilityNotFound,
    get_ward_location_state,
)
from backend.scenarios.ward.read_models import WardLocationRead
from backend.world.agent_tools import read_world_status
from backend.world.characters import (
    CharacterConflict,
    CharacterNotFound,
    create_player_character,
    list_player_characters,
    read_player_character,
    remove_player_character,
    update_player_character,
)
from backend.world.context import build_world_context
from backend.world.expansion import ExpansionConflict, ExpansionNotFound, propose_location_expansion
from backend.world.hierarchy import set_location_hierarchy, set_location_scope_promotion
from backend.world.narration_history import append_narration, read_narration_history
from backend.world.queries import (
    EntityNotFound,
    LocationNotFound,
    PlayerNotFound,
    WorldNotFound,
    get_current_location,
    get_entity,
    get_location,
    get_player,
    get_world_map,
    list_recent_events,
    list_worlds,
    read_world,
)
from backend.world.routes import RouteConflict, RouteNotFound, create_route, travel_entity_route
from backend.world.scenarios import (
    ScenarioConflict,
    ScenarioNotFound,
    create_scenario,
    list_scenarios,
    read_scenario,
    remove_scenario,
    remove_scenario_region,
    set_scenario_element,
    set_scenario_region,
    update_scenario,
)
from backend.world.turns import TurnDecision, run_turn
from backend.world.worlds import (
    WorldAdminConflict,
    WorldAdminNotFound,
    create_world_from_scenario,
    instance_player_character,
    remove_world,
    set_world_element,
    update_world,
    world_provision_player,
)

DEFAULT_FRONTEND_PATH = Path(__file__).resolve().parents[2] / "frontend" / "dist"


LOGGER = logging.getLogger(__name__)


def create_app(
    database_path: str | Path | None = None,
    *,
    frontend_path: str | Path | None = DEFAULT_FRONTEND_PATH,
    narrator: Narrator | None = None,
    start_narrator: StartNarrator | None = None,
) -> FastAPI:
    configured_path = Path(database_path) if database_path is not None else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_path = configured_path
        if resolved_path is None:
            environment_path = os.environ.get("MUTABLE_REALMS_DB_PATH")
            if not environment_path:
                raise RuntimeError("MUTABLE_REALMS_DB_PATH is required at application startup")
            resolved_path = Path(environment_path)
        migrate_database(resolved_path)
        app.state.database_path = resolved_path
        yield

    application = FastAPI(title="Mutable Realms", lifespan=lifespan)
    application.state.narrator = narrator
    application.state.start_narrator = start_narrator

    def get_database_path() -> Path:
        resolved_path = getattr(application.state, "database_path", None)
        if resolved_path is None:
            raise HTTPException(status_code=503, detail="database startup is incomplete")
        return resolved_path

    @application.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @application.get("/health/ready")
    def readiness() -> dict[str, str]:
        resolved_path = get_database_path()
        try:
            verify_database_schema(resolved_path)
        except (MigrationError, sqlite3.Error, OSError) as error:
            raise HTTPException(status_code=503, detail="database schema is not ready") from error
        return {"status": "ready"}

    @application.get("/api/worlds", tags=["world reads"])
    def worlds() -> list[WorldRead]:
        return [WorldRead.model_validate(world) for world in list_worlds(get_database_path())]

    @application.get("/api/worlds/{world_id}", tags=["world reads"])
    def world_detail(world_id: str) -> WorldDetailRead:
        try:
            return WorldDetailRead.model_validate(read_world(get_database_path(), world_id))
        except WorldNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error

    @application.post("/api/worlds", tags=["world administration"], status_code=201)
    def create_world(request: WorldCreateRequest) -> WorldCreateResponse:
        try:
            result = create_world_from_scenario(
                get_database_path(),
                world_id=request.world_id,
                operation_id=request.operation_id,
                scenario_id=request.scenario_id,
            )
        except ScenarioNotFound as error:
            raise HTTPException(status_code=404, detail="scenario not found") from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return WorldCreateResponse(
            already_applied=result["already_applied"],
            world_id=result["world_id"],
            world_revision=result["world_revision"],
            source_scenario_id=result["source_scenario_id"],
        )

    @application.patch("/api/worlds/{world_id}", tags=["world administration"])
    def update_world_route(world_id: str, request: WorldUpdateRequest) -> WorldMutationResponse:
        try:
            result = update_world(
                get_database_path(),
                world_id=world_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                title=request.title,
                description=request.description,
            )
        except WorldAdminNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return WorldMutationResponse(
            already_applied=result["already_applied"],
            world_id=result["world_id"],
            world_revision=result["world_revision"],
        )

    @application.put(
        "/api/worlds/{world_id}/elements/{element_type}",
        tags=["world administration"],
    )
    def set_world_element_route(
        world_id: str, element_type: str, request: WorldElementRequest
    ) -> WorldMutationResponse:
        try:
            result = set_world_element(
                get_database_path(),
                world_id=world_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                element_type=element_type,
                content=request.content,
            )
        except WorldAdminNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return WorldMutationResponse(
            already_applied=result["already_applied"],
            world_id=result["world_id"],
            world_revision=result["world_revision"],
        )

    @application.delete("/api/worlds/{world_id}", tags=["world administration"])
    def remove_world_route(
        world_id: str,
        operation_id: str = Query(...),
        expected_revision: int = Query(..., ge=0),
    ) -> WorldMutationResponse:
        try:
            result = remove_world(
                get_database_path(),
                world_id=world_id,
                operation_id=operation_id,
                expected_revision=expected_revision,
            )
        except WorldAdminNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return WorldMutationResponse(
            already_applied=result["already_applied"],
            world_id=result["world_id"],
            world_revision=result["world_revision"],
        )

    @application.get("/api/worlds/{world_id}/player", tags=["world reads"])
    def current_player(world_id: str) -> PlayerRead:
        try:
            return PlayerRead.model_validate(get_player(get_database_path(), world_id))
        except PlayerNotFound as error:
            raise HTTPException(status_code=404, detail="player not found") from error

    @application.post("/api/worlds/{world_id}/player", tags=["world administration"])
    def provision_player(world_id: str, request: WorldProvisionRequest) -> WorldMutationResponse:
        try:
            result = world_provision_player(
                get_database_path(),
                world_id=world_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                player_name=request.player_name,
                location_name=request.location_name,
            )
        except WorldAdminNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return WorldMutationResponse(
            already_applied=result["already_applied"],
            world_id=result["world_id"],
            world_revision=result["world_revision"],
        )

    @application.get("/api/worlds/{world_id}/map", tags=["world reads"])
    def world_map(
        world_id: str,
        scope_location_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=100),
    ) -> WorldMapRead:
        try:
            return WorldMapRead.model_validate(
                get_world_map(
                    get_database_path(),
                    world_id=world_id,
                    scope_location_id=scope_location_id,
                    limit=limit,
                )
            )
        except WorldNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        except LocationNotFound as error:
            raise HTTPException(status_code=404, detail="location not found") from error

    @application.put(
        "/api/worlds/{world_id}/locations/{location_id}/hierarchy",
        tags=["world administration"],
    )
    def configure_location_hierarchy(
        world_id: str,
        location_id: str,
        request: LocationHierarchyRequest,
    ) -> LocationHierarchyMutationResponse:
        try:
            result = set_location_hierarchy(
                get_database_path(),
                world_id=world_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                location_id=location_id,
                parent_location_id=request.parent_location_id,
                kind=request.kind,
                is_map_scope=request.is_map_scope,
                is_default_scope=request.is_default_scope,
            )
        except WorldAdminNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return LocationHierarchyMutationResponse.model_validate(result)

    @application.put(
        "/api/worlds/{world_id}/locations/{location_id}/scope-promotion",
        tags=["world administration"],
    )
    def configure_location_scope_promotion(
        world_id: str,
        location_id: str,
        request: LocationScopePromotionRequest,
    ) -> LocationScopePromotionMutationResponse:
        try:
            result = set_location_scope_promotion(
                get_database_path(),
                world_id=world_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                scope_location_id=request.scope_location_id,
                location_id=location_id,
                is_promoted=request.is_promoted,
            )
        except WorldAdminNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return LocationScopePromotionMutationResponse.model_validate(result)

    @application.post("/api/worlds/{world_id}/locations/expand", tags=["player turns"])
    def expand_location(world_id: str, request: ExpansionRequest) -> ExpansionResponse:
        try:
            result = propose_location_expansion(
                get_database_path(),
                world_id=world_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                proposal_id=request.proposal_id,
                location_id=request.location_id,
                anchor_location_id=request.anchor_location_id,
                name=request.name,
                description=request.description,
                parent_location_id=request.parent_location_id,
                connect_to_anchor=request.connect_to_anchor,
                actor_entity_id=request.actor_entity_id,
                direction=request.direction,
                range_band=request.range_band,
                map_form=request.map_form,
                move_actor_to_location=request.move_actor_to_location,
                region_id=request.region_id,
            )
        except ExpansionNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ExpansionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ExpansionResponse.model_validate(result)

    @application.put("/api/worlds/{world_id}/routes/{route_id}", tags=["world administration"])
    def set_route_route(
        world_id: str, route_id: str, request: WorldRouteRequest
    ) -> WorldRouteMutationResponse:
        if request.route_id != route_id:
            raise HTTPException(status_code=422, detail="route_id must match the URL")
        try:
            result = create_route(
                get_database_path(),
                world_id=world_id,
                route_id=route_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                origin_location_id=request.origin_location_id,
                destination_location_id=request.destination_location_id,
                name=request.name,
                description=request.description,
                route_kind=request.route_kind,
                is_active=request.is_active,
            )
        except RouteNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RouteConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return WorldRouteMutationResponse.model_validate(result)

    @application.post("/api/worlds/{world_id}/route-travel", tags=["player turns"])
    def route_travel(world_id: str, request: RouteTravelRequest) -> RouteTravelResponse:
        try:
            result = travel_entity_route(
                get_database_path(),
                world_id=world_id,
                route_id=request.route_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                entity_id=request.entity_id,
                actor_entity_id=request.actor_entity_id,
            )
        except RouteNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except RouteConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return RouteTravelResponse.model_validate(result)

    @application.get("/api/worlds/{world_id}/locations/current", tags=["world reads"])
    def current_location(world_id: str) -> LocationRead:
        try:
            return LocationRead.model_validate(get_current_location(get_database_path(), world_id))
        except (PlayerNotFound, LocationNotFound) as error:
            raise HTTPException(status_code=404, detail="location not found") from error

    @application.get("/api/worlds/{world_id}/locations/{location_id}", tags=["world reads"])
    def location(world_id: str, location_id: str) -> LocationRead:
        try:
            return LocationRead.model_validate(
                get_location(get_database_path(), world_id, location_id)
            )
        except LocationNotFound as error:
            raise HTTPException(status_code=404, detail="location not found") from error

    @application.get(
        "/api/worlds/{world_id}/capabilities/ward/locations/{location_id}",
        tags=["ward example reads"],
    )
    def ward_location(world_id: str, location_id: str) -> WardLocationRead:
        try:
            return WardLocationRead.model_validate(
                get_ward_location_state(get_database_path(), world_id, location_id)
            )
        except WardCapabilityNotFound as error:
            raise HTTPException(status_code=404, detail="ward capability not found") from error
        except LocationNotFound as error:
            raise HTTPException(status_code=404, detail="location not found") from error

    @application.get("/api/worlds/{world_id}/entities/{entity_id}", tags=["world reads"])
    def entity(world_id: str, entity_id: str) -> EntityRead:
        try:
            return EntityRead.model_validate(get_entity(get_database_path(), world_id, entity_id))
        except EntityNotFound as error:
            raise HTTPException(status_code=404, detail="entity not found") from error

    @application.get("/api/worlds/{world_id}/events", tags=["world reads"])
    def recent_events(
        world_id: str, limit: int = Query(default=20, ge=1, le=100)
    ) -> list[WorldEventRead]:
        try:
            return [
                WorldEventRead.model_validate(event)
                for event in list_recent_events(get_database_path(), world_id, limit=limit)
            ]
        except WorldNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error

    @application.get("/api/worlds/{world_id}/narration", tags=["world reads"])
    def narration_history(
        world_id: str, limit: int = Query(default=20, ge=1, le=100)
    ) -> NarrationHistoryRead:
        try:
            entries = read_narration_history(
                get_database_path(), world_id=world_id, limit=limit
            )
        except WorldNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        return NarrationHistoryRead(
            world_id=world_id,
            entries=[
                NarrationEntryRead(
                    id=entry["id"],
                    revision=entry["revision"],
                    role=entry["role"],
                    content=entry["content"],
                    occurred_at=entry["occurred_at"],
                )
                for entry in entries
            ],
        )

    @application.get("/api/player-characters", tags=["player character reads"])
    def player_characters() -> list[PlayerCharacterRead]:
        return [
            PlayerCharacterRead.model_validate(item)
            for item in list_player_characters(get_database_path())
        ]

    @application.get("/api/player-characters/{character_id}", tags=["player character reads"])
    def player_character(character_id: str) -> PlayerCharacterRead:
        try:
            return PlayerCharacterRead.model_validate(
                read_player_character(get_database_path(), character_id)
            )
        except CharacterNotFound as error:
            raise HTTPException(status_code=404, detail="player character not found") from error

    @application.post(
        "/api/player-characters", tags=["player character mutations"], status_code=201
    )
    def create_player_character_route(
        request: PlayerCharacterCreateRequest,
    ) -> PlayerCharacterMutationResponse:
        try:
            result = create_player_character(
                get_database_path(),
                character_id=request.character_id,
                operation_id=request.operation_id,
                name=request.name,
                basic_info=request.basic_info,
            )
        except CharacterConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return PlayerCharacterMutationResponse(
            already_applied=result["already_applied"], character_id=result["character_id"]
        )

    @application.patch("/api/player-characters/{character_id}", tags=["player character mutations"])
    def update_player_character_route(
        character_id: str, request: PlayerCharacterUpdateRequest
    ) -> PlayerCharacterMutationResponse:
        try:
            result = update_player_character(
                get_database_path(),
                character_id=character_id,
                operation_id=request.operation_id,
                name=request.name,
                basic_info=request.basic_info,
            )
        except CharacterNotFound as error:
            raise HTTPException(status_code=404, detail="player character not found") from error
        except CharacterConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return PlayerCharacterMutationResponse(
            already_applied=result["already_applied"], character_id=result["character_id"]
        )

    @application.delete(
        "/api/player-characters/{character_id}", tags=["player character mutations"]
    )
    def remove_player_character_route(
        character_id: str, operation_id: str = Query(...)
    ) -> PlayerCharacterMutationResponse:
        try:
            result = remove_player_character(
                get_database_path(), character_id=character_id, operation_id=operation_id
            )
        except CharacterNotFound as error:
            raise HTTPException(status_code=404, detail="player character not found") from error
        except CharacterConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return PlayerCharacterMutationResponse(
            already_applied=result["already_applied"], character_id=result["character_id"]
        )

    @application.post(
        "/api/worlds/{world_id}/character-instance", tags=["world administration"], status_code=201
    )
    def instance_player_character_route(
        world_id: str, request: WorldCharacterInstanceRequest
    ) -> WorldMutationResponse:
        try:
            result = instance_player_character(
                get_database_path(),
                world_id=world_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                character_id=request.character_id,
                location_name=request.location_name,
            )
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except WorldAdminNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        return WorldMutationResponse(
            already_applied=result["already_applied"],
            world_id=result["world_id"],
            world_revision=result["world_revision"],
        )

    @application.get("/api/scenarios", tags=["scenario reads"])
    def scenarios() -> list[ScenarioRead]:
        return [
            ScenarioRead.model_validate(scenario)
            for scenario in list_scenarios(get_database_path())
        ]

    @application.get("/api/scenarios/{scenario_id}", tags=["scenario reads"])
    def scenario(scenario_id: str) -> ScenarioRead:
        try:
            return ScenarioRead.model_validate(read_scenario(get_database_path(), scenario_id))
        except ScenarioNotFound as error:
            raise HTTPException(status_code=404, detail="scenario not found") from error

    @application.post("/api/scenarios", tags=["scenario mutations"], status_code=201)
    def create_scenario_route(request: ScenarioCreateRequest) -> ScenarioMutationResponse:
        try:
            result = create_scenario(
                get_database_path(),
                scenario_id=request.scenario_id,
                operation_id=request.operation_id,
                title=request.title,
                description=request.description,
            )
        except ScenarioConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ScenarioMutationResponse(
            already_applied=result["already_applied"],
            scenario_id=result["scenario_id"],
        )

    @application.patch("/api/scenarios/{scenario_id}", tags=["scenario mutations"])
    def update_scenario_route(
        scenario_id: str, request: ScenarioUpdateRequest
    ) -> ScenarioMutationResponse:
        try:
            result = update_scenario(
                get_database_path(),
                scenario_id=scenario_id,
                operation_id=request.operation_id,
                title=request.title,
                description=request.description,
            )
        except ScenarioNotFound as error:
            raise HTTPException(status_code=404, detail="scenario not found") from error
        except ScenarioConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ScenarioMutationResponse(
            already_applied=result["already_applied"],
            scenario_id=result["scenario_id"],
        )

    @application.put(
        "/api/scenarios/{scenario_id}/elements/{element_type}",
        tags=["scenario mutations"],
    )
    def set_scenario_element_route(
        scenario_id: str, element_type: str, request: ScenarioElementRequest
    ) -> ScenarioMutationResponse:
        try:
            result = set_scenario_element(
                get_database_path(),
                scenario_id=scenario_id,
                operation_id=request.operation_id,
                element_type=element_type,
                content=request.content,
            )
        except ScenarioNotFound as error:
            raise HTTPException(status_code=404, detail="scenario not found") from error
        except ScenarioConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ScenarioMutationResponse(
            already_applied=result["already_applied"],
            scenario_id=result["scenario_id"],
        )

    @application.delete("/api/scenarios/{scenario_id}", tags=["scenario mutations"])
    def remove_scenario_route(
        scenario_id: str, operation_id: str = Query(...)
    ) -> ScenarioMutationResponse:
        try:
            result = remove_scenario(
                get_database_path(),
                scenario_id=scenario_id,
                operation_id=operation_id,
            )
        except ScenarioNotFound as error:
            raise HTTPException(status_code=404, detail="scenario not found") from error
        except ScenarioConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ScenarioMutationResponse(
            already_applied=result["already_applied"],
            scenario_id=result["scenario_id"],
        )

    @application.put(
        "/api/scenarios/{scenario_id}/regions/{region_id}",
        tags=["scenario mutations"],
    )
    def set_scenario_region_route(
        scenario_id: str, region_id: str, request: ScenarioRegionRequest
    ) -> ScenarioMutationResponse:
        try:
            result = set_scenario_region(
                get_database_path(),
                scenario_id=scenario_id,
                operation_id=request.operation_id,
                region_id=region_id,
                level=request.level,
                title=request.title,
                description=request.description,
                parent_region_id=request.parent_region_id,
                attributes=request.attributes,
            )
        except ScenarioNotFound as error:
            raise HTTPException(status_code=404, detail="scenario not found") from error
        except ScenarioConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ScenarioMutationResponse(
            already_applied=result["already_applied"],
            scenario_id=result["scenario_id"],
        )

    @application.delete(
        "/api/scenarios/{scenario_id}/regions/{region_id}",
        tags=["scenario mutations"],
    )
    def remove_scenario_region_route(
        scenario_id: str, region_id: str, operation_id: str = Query(...)
    ) -> ScenarioMutationResponse:
        try:
            result = remove_scenario_region(
                get_database_path(),
                scenario_id=scenario_id,
                operation_id=operation_id,
                region_id=region_id,
            )
        except ScenarioNotFound as error:
            raise HTTPException(status_code=404, detail="scenario not found") from error
        except ScenarioConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return ScenarioMutationResponse(
            already_applied=result["already_applied"],
            scenario_id=result["scenario_id"],
        )

    @application.post("/api/worlds/{world_id}/start", tags=["player starts"], status_code=201)
    def start_world(world_id: str, request: WorldStartRequest) -> WorldStartResponse:
        """Start a playerless world through the narrator's structured contract."""
        database_path = get_database_path()
        try:
            with connect_database(database_path) as connection:
                operation = connection.execute(
                    "SELECT operation_type, result_json FROM operations "
                    "WHERE world_id = ? AND operation_id = ?",
                    (world_id, request.operation_id),
                ).fetchone()
            if operation is not None:
                if operation["operation_type"] != "player_character_instanced":
                    raise WorldAdminConflict("operation id already used for another operation")
                stored = json.loads(operation["result_json"])
                if (
                    stored.get("character_id") != request.character_id
                    or stored.get("revision_before") != request.expected_revision
                    or "narration" not in stored
                ):
                    raise WorldAdminConflict(
                        "operation id was already used with a different request"
                    )
                return WorldStartResponse.model_validate(
                    {key: stored[key] for key in WorldStartResponse.model_fields}
                )
            world = read_world(database_path, world_id)
            if world.get("player") is not None:
                raise WorldAdminConflict(f"world already has a player: {world_id}")
            character = read_player_character(database_path, request.character_id)
        except WorldNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        except CharacterNotFound as error:
            raise HTTPException(status_code=404, detail="player character not found") from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        starter = start_narrator or application.state.start_narrator
        if starter is None:
            starter = HermesNarrator().start
        try:
            result = starter(world_id, world, character)
        except NarratorError as error:
            if error.category == "narrator_timeout":
                LOGGER.warning(
                    "world start request timed out: world_id=%s detail=%s",
                    world_id,
                    str(error),
                )
            public_detail = {
                "invalid_start_response": "narration agent returned an invalid start response",
                "narrator_timeout": "narration agent timed out while preparing the world",
            }.get(error.category, "narration agent was unavailable")
            raise HTTPException(status_code=502, detail=public_detail) from error
        if not isinstance(result, NarratorStartResult):
            raise HTTPException(
                status_code=502, detail="narration agent returned an invalid start response"
            )
        try:
            instance = instance_player_character(
                database_path,
                world_id=world_id,
                operation_id=request.operation_id,
                expected_revision=request.expected_revision,
                character_id=request.character_id,
                location_name=result.start_location_name,
                location_description=result.location_description,
                location_layout=(
                    [
                        {
                            "name": location.name,
                            "description": location.description,
                            "parent_name": location.parent_name,
                            "link_to_start": location.link_to_start,
                            "geography_role": location.geography_role,
                            "direction": location.direction,
                            "range_band": location.range_band,
                            "region_id": location.region_id,
                        }
                        for location in result.locations
                    ]
                    if result.locations
                    else None
                ),
                result_fields={
                    "outcome": "world_started",
                    "narration": result.narration,
                    "character_id": request.character_id,
                    "player_id": f"{world_id}-player",
                    "location_id": f"{world_id}-start",
                    "location_name": result.start_location_name,
                    "revision_before": request.expected_revision,
                    "revision_after": request.expected_revision + 1,
                },
                region_layout=(
                    [
                        {
                            "region_id": region.region_id,
                            "parent_region_id": region.parent_region_id,
                            "level": region.level,
                            "title": region.title,
                            "description": region.description,
                            "attributes": region.attributes,
                        }
                        for region in result.regions
                    ]
                    if result.regions
                    else None
                ),
            )
            response = {
                "outcome": "world_started",
                "narration": result.narration,
                "world_id": world_id,
                "character_id": request.character_id,
                "player_id": instance["entity_id"],
                "location_id": instance["location_id"],
                "location_name": result.location_name,
                "revision_before": request.expected_revision,
                "revision_after": instance["world_revision"],
            }
            append_narration(
                database_path,
                world_id=world_id,
                revision=instance["world_revision"],
                role="agent",
                content=result.narration,
            )
            return WorldStartResponse.model_validate(response)
        except WorldAdminNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        except WorldAdminConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @application.post("/api/worlds/{world_id}/turns", tags=["player turns"])
    def player_turn(world_id: str, request: TurnRequest) -> TurnResponse:
        """Execute one narrated player turn.

        With ``decision_json`` this is the deterministic seam over HTTP: the
        same ``run_turn`` path the ``world-turn`` CLI uses. Without it, the
        action is relayed to the bound narration agent, which reads the world,
        performs at most one supported mutation, and returns player-facing
        narration.
        """
        database_path = get_database_path()
        if request.decision_json is not None:
            try:
                decision = TurnDecision.model_validate(json.loads(request.decision_json))
            except (json.JSONDecodeError, ValidationError) as error:
                detail = f"invalid decision_json: {error}"
                raise HTTPException(status_code=422, detail=detail) from error
            try:
                result = run_turn(
                    database_path,
                    world_id=world_id,
                    player_id=request.player_id,
                    player_action=request.player_action,
                    decide=lambda _action, _context: decision,
                )
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            except WorldNotFound as error:
                raise HTTPException(status_code=404, detail="world not found") from error
            return TurnResponse(
                outcome=result.outcome.value,
                message=result.message,
                revision_before=result.before.world.revision,
                revision_after=result.after.world.revision,
                attempts=result.attempts,
                mutation=result.mutation,
            )

        narrator = getattr(application.state, "narrator", None) or HermesNarrator()
        try:
            revision_before = read_world_status(database_path, world_id=world_id)["world"][
                "revision"
            ]
        except WorldNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        try:
            context = build_world_context(database_path, world_id=world_id).model_dump()
        except PlayerNotFound:
            context = None
        if context is not None:
            context["recent_narration"] = read_narration_history(
                database_path, world_id=world_id, limit=100
            )
        try:
            narration = narrator(world_id, request.player_id, request.player_action, context)
        except NarratorError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        after_status = read_world_status(database_path, world_id=world_id)
        append_narration(
            database_path,
            world_id=world_id,
            revision=after_status["world"]["revision"],
            role="player",
            content=request.player_action,
        )
        append_narration(
            database_path,
            world_id=world_id,
            revision=after_status["world"]["revision"],
            role="agent",
            content=narration,
        )
        return TurnResponse(
            outcome="narrated_turn",
            narration=narration,
            revision_before=revision_before,
            revision_after=after_status["world"]["revision"],
            attempts=1,
        )

    if frontend_path is not None:
        resolved_frontend_path = Path(frontend_path)
        if resolved_frontend_path.is_dir():
            application.mount(
                "/", StaticFiles(directory=resolved_frontend_path, html=True), name="frontend"
            )

    return application


app = create_app()
