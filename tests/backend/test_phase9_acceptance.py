"""Phase 9 acceptance loop: the primary proof of persistent causality.

This mirrors docs/narration-agent-contract.md's acceptance scenario without an
external model: seed the ward, treat and discharge the first patient through the
same turn policy the narration agent uses, perform an unrelated read-only turn,
"return" to the ward, and verify the browser/API view matches authoritative
state. The narrator-visible working set must show five patients, never six.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app
from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.context import WorldContext
from backend.world.turns import (
    DecisionKind,
    OperationDecision,
    TurnDecision,
    TurnOutcome,
    run_turn,
)


def _fresh_ward(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    assert seed_ward_world(database_path)
    return database_path


def _treat_first_patient() -> TurnDecision:
    return TurnDecision(
        kind=DecisionKind.PERFORM_OPERATION,
        operation=OperationDecision(
            operation_type="world_treat_and_discharge_patient",
            patient_id="patient-1",
            bed_id="bed-1",
        ),
    )


def _patient_ids(context: WorldContext) -> list[str]:
    """Entities in the ward's current contents that the narrator sees as patients."""
    return sorted(
        entity.id for entity in context.current_location.entities if entity.role == "patient"
    )


def _character_row(database_path: Path, entity_id: str) -> tuple[str, str]:
    with connect_database(database_path) as connection:
        return connection.execute(
            "SELECT condition, disposition FROM characters WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()


def test_phase9_acceptance_loop_persists_return_state(tmp_path: Path) -> None:
    database_path = _fresh_ward(tmp_path)

    initial = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="Look around the ward.",
        decide=lambda _action, context: TurnDecision(kind=DecisionKind.NARRATE),
        operation_id_factory=lambda: "initial-look",
    )
    assert _patient_ids(initial.after) == [
        "patient-1",
        "patient-2",
        "patient-3",
        "patient-4",
        "patient-5",
        "patient-6",
    ]
    assert initial.after.world.revision == 0

    treatment = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I treat the woman suffering from fever in the first bed.",
        decide=lambda _action, _context: _treat_first_patient(),
        operation_id_factory=lambda: "turn-treatment-1",
    )
    assert treatment.outcome is TurnOutcome.SUCCESS
    assert treatment.after.world.revision == 1
    assert treatment.after.recent_events[0].event_type == "patient_treated_and_discharged"
    assert "patient-1" not in _patient_ids(treatment.after)

    with connect_database(database_path) as connection:
        condition, disposition = connection.execute(
            "SELECT condition, disposition FROM characters WHERE entity_id = 'patient-1'"
        ).fetchone()
        bed_occupant = connection.execute(
            "SELECT occupant_entity_id FROM beds WHERE entity_id = 'bed-1'"
        ).fetchone()[0]
        occupied_beds = connection.execute(
            "SELECT COUNT(*) FROM beds WHERE occupant_entity_id IS NOT NULL"
        ).fetchone()[0]
    assert (condition, disposition) == ("recovered", "discharged")
    assert bed_occupant is None
    assert occupied_beds == 5

    unrelated = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I check the ward records.",
        decide=lambda _action, _context: TurnDecision(kind=DecisionKind.NARRATE),
        operation_id_factory=lambda: "unrelated-turn",
    )
    assert unrelated.outcome is TurnOutcome.NO_MUTATION
    assert unrelated.after.world.revision == 1

    returned = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I return to the ward later.",
        decide=lambda _action, context: TurnDecision(kind=DecisionKind.NARRATE),
        operation_id_factory=lambda: "return-turn",
    )
    assert _patient_ids(returned.after) == [
        "patient-2",
        "patient-3",
        "patient-4",
        "patient-5",
        "patient-6",
    ]
    assert returned.after.world.revision == 1


def test_phase9_browser_readback_matches_authoritative_state(tmp_path: Path) -> None:
    database_path = _fresh_ward(tmp_path)

    run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I treat the woman suffering from fever in the first bed.",
        decide=lambda _action, _context: _treat_first_patient(),
        operation_id_factory=lambda: "turn-treatment-1",
    )

    # The browser is derived from the HTTP API, which is derived from SQLite.
    app = create_app(database_path)

    async def _get(path: str) -> tuple[int, Any]:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(path)
        return response.status_code, response.json()

    player_status, player = asyncio.run(_get(f"/api/worlds/{WARD_WORLD_ID}/player"))
    location_status, location = asyncio.run(_get(f"/api/worlds/{WARD_WORLD_ID}/locations/current"))
    events_status, events = asyncio.run(_get(f"/api/worlds/{WARD_WORLD_ID}/events?limit=10"))
    ward_status, ward = asyncio.run(
        _get(f"/api/worlds/{WARD_WORLD_ID}/capabilities/ward/locations/ward")
    )

    assert player_status == 200
    assert player["location_id"] == "ward"
    assert location_status == 200
    assert location["revision"] == 1
    assert len(location["entities"]) == 12  # 6 beds + 5 patients + player
    assert "patient-1" not in {entity["id"] for entity in location["entities"]}
    assert {entity["id"] for entity in location["entities"] if entity["role"] == "patient"} == {
        "patient-2",
        "patient-3",
        "patient-4",
        "patient-5",
        "patient-6",
    }
    assert events_status == 200
    assert events[0]["event_type"] == "patient_treated_and_discharged"
    assert events[0]["world_revision"] == 1
    assert ward_status == 200
    assert ward["occupied_bed_count"] == 5
    assert ward["beds"][0]["occupant"] is None
