from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.persistence.database import connect_database
from backend.persistence.migrations import MigrationError


def test_startup_migrates_database_and_readiness_checks_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    app = create_app(database_path)

    async def run_lifespan_and_request() -> tuple[int, dict[str, str]]:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health/ready")
            return response.status_code, response.json()

    status_code, body = asyncio.run(run_lifespan_and_request())

    assert status_code == 200
    assert body == {"status": "ready"}
    with connect_database(database_path) as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [row[0] for row in versions] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_startup_fails_visibly_for_changed_applied_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "world.sqlite3"
    app = create_app(database_path)
    asyncio.run(_run_lifespan(app))
    with connect_database(database_path) as connection:
        connection.execute("UPDATE schema_migrations SET checksum = 'changed' WHERE version = 1")
        connection.commit()

    with pytest.raises(MigrationError, match="checksum"):
        asyncio.run(_run_lifespan(create_app(database_path)))


async def _run_lifespan(app: object) -> None:
    # FastAPI exposes its configured lifespan through the router.
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        pass
