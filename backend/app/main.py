from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.app.narrator import HermesNarrator, Narrator, NarratorError
from backend.app.read_models import (
    EntityRead,
    LocationRead,
    PlayerRead,
    ScenarioCreateRequest,
    ScenarioElementRequest,
    ScenarioMutationResponse,
    ScenarioRead,
    ScenarioUpdateRequest,
    TurnRequest,
    TurnResponse,
    WorldCreateRequest,
    WorldCreateResponse,
    WorldDetailRead,
    WorldElementRequest,
    WorldEventRead,
    WorldMapRead,
    WorldMutationResponse,
    WorldProvisionRequest,
    WorldRead,
    WorldUpdateRequest,
)
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
from backend.world.context import build_world_context
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
from backend.world.scenarios import (
    ScenarioConflict,
    ScenarioNotFound,
    create_scenario,
    list_scenarios,
    read_scenario,
    remove_scenario,
    set_scenario_element,
    update_scenario,
)
from backend.world.turns import TurnDecision, run_turn
from backend.world.worlds import (
    WorldAdminConflict,
    WorldAdminNotFound,
    create_world_from_scenario,
    remove_world,
    set_world_element,
    update_world,
    world_provision_player,
)

DEFAULT_FRONTEND_PATH = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(
    database_path: str | Path | None = None,
    *,
    frontend_path: str | Path | None = DEFAULT_FRONTEND_PATH,
    narrator: Narrator | None = None,
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
            return WorldDetailRead.model_validate(
                read_world(get_database_path(), world_id)
            )
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
    def update_world_route(
        world_id: str, request: WorldUpdateRequest
    ) -> WorldMutationResponse:
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
    def world_map(world_id: str) -> WorldMapRead:
        try:
            return WorldMapRead.model_validate(
                get_world_map(get_database_path(), world_id=world_id)
            )
        except WorldNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error

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

    @application.get("/api/scenarios", tags=["scenario reads"])
    def scenarios() -> list[ScenarioRead]:
        return [
            ScenarioRead.model_validate(scenario)
            for scenario in list_scenarios(get_database_path())
        ]

    @application.get("/api/scenarios/{scenario_id}", tags=["scenario reads"])
    def scenario(scenario_id: str) -> ScenarioRead:
        try:
            return ScenarioRead.model_validate(
                read_scenario(get_database_path(), scenario_id)
            )
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
            revision_before = read_world_status(database_path, world_id=world_id)[
                "world"
            ]["revision"]
        except WorldNotFound as error:
            raise HTTPException(status_code=404, detail="world not found") from error
        try:
            context = build_world_context(database_path, world_id=world_id).model_dump()
        except PlayerNotFound:
            context = None
        try:
            narration = narrator(world_id, request.player_id, request.player_action, context)
        except NarratorError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        after_status = read_world_status(database_path, world_id=world_id)
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
