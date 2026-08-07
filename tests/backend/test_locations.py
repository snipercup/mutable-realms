from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.persistence.database import connect_database
from backend.persistence.migrations import migrate_database
from backend.scenarios.ward.seed import WARD_WORLD_ID, seed_ward_world
from backend.world.locations import (
    LocationStateConflict,
    LocationStateNotFound,
    read_location_properties,
    update_location,
)
from backend.world.turns import (
    DecisionKind,
    OperationDecision,
    TurnDecision,
    TurnOutcome,
    run_turn,
)
from backend.world.validation import validate_worlds
from tests.backend.general_world import seed_general_world


def _ward_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "world.sqlite3"
    migrate_database(database_path)
    assert seed_ward_world(database_path)
    return database_path


def _update_arguments(
    database_path: Path, operation_id: str = "location-clean-1"
) -> dict[str, Any]:
    return {
        "database_path": database_path,
        "world_id": WARD_WORLD_ID,
        "operation_id": operation_id,
        "expected_revision": 0,
        "actor_entity_id": "player",
        "location_id": "ward",
        "property": "cleanliness",
        "value": 80,
    }


def test_location_property_update_persists_ledger_event_and_readback(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    result = update_location(**_update_arguments(database_path))

    assert result == {"already_applied": False, "world_revision": 1}
    properties = read_location_properties(
        database_path, world_id=WARD_WORLD_ID, location_ids=["ward"]
    )
    assert properties == {
        "properties": [{"location_id": "ward", "property": "cleanliness", "value": 80}]
    }
    with connect_database(database_path) as connection:
        event = connection.execute(
            "SELECT event_type, world_revision, actor_entity_id FROM events"
        ).fetchone()
        operation = connection.execute(
            "SELECT operation_type, completed_revision FROM operations"
        ).fetchone()
    assert tuple(event) == ("location_updated", 1, "player")
    assert tuple(operation) == ("location_updated", 1)
    assert validate_worlds(database_path) == []


def test_location_rename_persists_identity_evolution(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    result = update_location(
        database_path,
        world_id=WARD_WORLD_ID,
        operation_id="location-rename-1",
        expected_revision=0,
        actor_entity_id="player",
        location_id="ward",
        display_name="Riverside Ward",
    )

    assert result == {"already_applied": False, "world_revision": 1}
    with connect_database(database_path) as connection:
        name = connection.execute(
            "SELECT name FROM locations WHERE id = 'ward' AND world_id = ?",
            (WARD_WORLD_ID,),
        ).fetchone()[0]
    assert name == "Riverside Ward"
    assert validate_worlds(database_path) == []


def test_location_update_is_exactly_idempotent(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    arguments = _update_arguments(database_path, "location-replay")

    first = update_location(**arguments)
    replay = update_location(**arguments)

    assert first == {"already_applied": False, "world_revision": 1}
    assert replay == {"already_applied": True, "world_revision": 1}
    assert (
        read_location_properties(
            database_path, world_id=WARD_WORLD_ID, location_ids=["ward"]
        )["properties"][0]["value"]
        == 80
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("value", 101, "between 0 and 100"),
        ("value", -1, "between 0 and 100"),
        ("display_name", "", "display name must not be blank"),
        ("property", "", "property must not be blank"),
        ("operation_id", "", "must not be blank"),
    ],
)
def test_location_update_rejects_invalid_input(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    database_path = _ward_database(tmp_path)
    arguments: dict[str, Any] = _update_arguments(database_path)
    arguments[field] = value

    with pytest.raises(LocationStateConflict, match=message):
        update_location(**arguments)


def test_location_update_requires_property_and_value_together(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    with pytest.raises(LocationStateConflict, match="value is required"):
        update_location(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="missing-value",
            expected_revision=0,
            actor_entity_id="player",
            location_id="ward",
            property="cleanliness",
        )
    with pytest.raises(LocationStateConflict, match="property is required"):
        update_location(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="missing-property",
            expected_revision=0,
            actor_entity_id="player",
            location_id="ward",
            value=80,
        )


def test_location_update_rejects_missing_location(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    with pytest.raises(LocationStateNotFound, match="location not found"):
        update_location(
            database_path,
            world_id=WARD_WORLD_ID,
            operation_id="missing-location",
            expected_revision=0,
            actor_entity_id="player",
            location_id="no-such-place",
            display_name="Nowhere",
        )


def test_turn_runner_can_persist_a_location_effect_and_retrieve_it_later(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    result = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="The ward is scrubbed clean after the rodent work.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_update_location",
                location_id="ward",
                property="cleanliness",
                value=75,
            ),
        ),
        operation_id_factory=lambda: "turn-clean-1",
    )

    assert result.outcome is TurnOutcome.SUCCESS
    assert result.after.world.revision == 1
    assert result.after.current_location.properties == [
        {"location_id": "ward", "property": "cleanliness", "value": 75}
    ]
    assert result.after.recent_events[0].event_type == "location_updated"


def test_turn_runner_maps_location_errors(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)

    missing = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I renovate a place that does not exist.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_update_location",
                location_id="no-such-place",
                display_name="Nowhere",
            ),
        ),
        operation_id_factory=lambda: "turn-location-missing",
    )
    assert missing.outcome is TurnOutcome.MISSING_RESOURCE
    assert missing.after.world.revision == 0

    invalid = run_turn(
        database_path,
        world_id=WARD_WORLD_ID,
        player_id="player",
        player_action="I set a property without a value.",
        decide=lambda _action, _context: TurnDecision(
            kind=DecisionKind.PERFORM_OPERATION,
            operation=OperationDecision(
                operation_type="world_update_location",
                location_id="ward",
                property="cleanliness",
            ),
        ),
        operation_id_factory=lambda: "turn-location-invalid",
    )
    assert invalid.outcome is TurnOutcome.INVALID_ACTION
    assert invalid.after.world.revision == 0


def test_validation_reports_corrupted_location_property_links(tmp_path: Path) -> None:
    database_path = _ward_database(tmp_path)
    seed_general_world(database_path)
    update_location(**_update_arguments(database_path, "validation-clean"))

    with connect_database(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "UPDATE location_properties SET updated_event_id = 'missing-event' WHERE world_id = ?",
            (WARD_WORLD_ID,),
        )
        connection.execute(
            "UPDATE location_properties SET location_id = 'ocean-farm' WHERE world_id = ?",
            (WARD_WORLD_ID,),
        )
        connection.commit()

    codes = {issue.code for issue in validate_worlds(database_path)}
    assert "location_property_updated_event_mismatch" in codes
    assert "location_property_world_mismatch" in codes
