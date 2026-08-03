from __future__ import annotations

import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from backend.app.read_models import (
    EntityRead,
    LocationRead,
    PlayerRead,
    WorldEventRead,
    WorldRead,
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
from backend.world.queries import (
    EntityNotFound,
    LocationNotFound,
    PlayerNotFound,
    WorldNotFound,
    get_current_location,
    get_entity,
    get_location,
    get_player,
    list_recent_events,
    list_worlds,
)

DEFAULT_FRONTEND_PATH = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(
    database_path: str | Path | None = None,
    *,
    frontend_path: str | Path | None = DEFAULT_FRONTEND_PATH,
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

    @application.get("/api/worlds/{world_id}/player", tags=["world reads"])
    def current_player(world_id: str) -> PlayerRead:
        try:
            return PlayerRead.model_validate(get_player(get_database_path(), world_id))
        except PlayerNotFound as error:
            raise HTTPException(status_code=404, detail="player not found") from error

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

    if frontend_path is not None:
        resolved_frontend_path = Path(frontend_path)
        if resolved_frontend_path.is_dir():
            application.mount(
                "/", StaticFiles(directory=resolved_frontend_path, html=True), name="frontend"
            )

    return application


app = create_app()
