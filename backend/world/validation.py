from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.persistence.database import connect_database


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    entity_id: str | None = None


def validate_worlds(database_path: str | Path) -> list[ValidationIssue]:
    """Return deterministic integrity and domain-invariant violations."""
    issues: list[ValidationIssue] = []
    with connect_database(database_path) as connection:
        for row in connection.execute("PRAGMA foreign_key_check"):
            issues.append(
                ValidationIssue(
                    "foreign_key_violation",
                    f"Foreign key violation in {row['table']} row {row['rowid']}",
                )
            )

        for row in connection.execute(
            """
            SELECT el.entity_id
            FROM entity_locations el
            JOIN entities e ON e.id = el.entity_id
            JOIN locations l ON l.id = el.location_id
            WHERE e.world_id <> l.world_id
            ORDER BY el.entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "placement_world_mismatch",
                    "Entity placement refers to a location in another world",
                    row["entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT c.entity_id
            FROM characters c
            JOIN entities e ON e.id = c.entity_id
            WHERE e.kind <> 'character'
            ORDER BY c.entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "character_kind_mismatch",
                    "Character state belongs to a non-character entity",
                    row["entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT e.id AS entity_id, e.kind
            FROM entities e
            LEFT JOIN characters c ON c.entity_id = e.id
            WHERE e.kind = 'character' AND c.entity_id IS NULL
            ORDER BY e.id
            """
        ):
            subtype = row["kind"]
            issues.append(
                ValidationIssue(
                    f"missing_{subtype}_state",
                    f"{subtype.title()} entity is missing its subtype state",
                    row["entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT b.entity_id
            FROM beds b
            JOIN entities e ON e.id = b.entity_id
            LEFT JOIN entity_locations el ON el.entity_id = b.entity_id
            WHERE e.kind <> 'bed' OR el.location_id IS NULL OR el.location_id <> b.location_id
            ORDER BY b.entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "bed_placement_mismatch",
                    "Bed state and entity placement disagree",
                    row["entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT b.entity_id AS bed_id, b.occupant_entity_id
            FROM beds b
            JOIN characters c ON c.entity_id = b.occupant_entity_id
            LEFT JOIN entity_locations el ON el.entity_id = b.occupant_entity_id
            WHERE b.occupant_entity_id IS NOT NULL
              AND (c.role <> 'patient' OR c.disposition <> 'admitted'
                   OR el.location_id IS NULL OR el.location_id <> b.location_id)
            ORDER BY b.entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "occupant_not_at_bed_location",
                    f"Bed {row['bed_id']} has an incoherent occupant",
                    row["occupant_entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT c.entity_id, c.disposition, el.location_id
            FROM characters c
            LEFT JOIN entity_locations el ON el.entity_id = c.entity_id
            WHERE (c.role = 'patient' AND (
                       (c.disposition = 'discharged' AND el.location_id IS NOT NULL)
                       OR (c.disposition <> 'discharged' AND el.location_id IS NULL)
                   ))
               OR (c.role = 'player' AND el.location_id IS NULL)
            ORDER BY c.entity_id
            """
        ):
            code = (
                "discharged_character_has_placement"
                if row["disposition"] == "discharged"
                else "active_character_missing_placement"
            )
            issues.append(
                ValidationIssue(
                    code,
                    "Character placement conflicts with disposition",
                    row["entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT w.id, w.revision,
                   (SELECT COUNT(*) FROM operations o WHERE o.world_id = w.id)
                       AS operation_count,
                   (SELECT COUNT(*) FROM events ev WHERE ev.world_id = w.id)
                       AS event_count
            FROM worlds w
            WHERE w.revision <> (SELECT COUNT(*) FROM operations o WHERE o.world_id = w.id)
               OR w.revision <> (SELECT COUNT(*) FROM events ev WHERE ev.world_id = w.id)
            ORDER BY w.id
            """
        ):
            issues.append(
                ValidationIssue(
                    "world_history_revision_mismatch",
                    f"World revision {row['revision']} has "
                    f"{row['operation_count']} operations and {row['event_count']} events",
                    row["id"],
                )
            )

        for row in connection.execute(
            """
            SELECT ev.id
            FROM events ev
            JOIN operations o
              ON o.world_id = ev.world_id AND o.operation_id = ev.operation_id
            WHERE ev.event_type <> o.operation_type
               OR ev.world_revision <> o.completed_revision
            ORDER BY ev.world_id, ev.world_revision
            """
        ):
            issues.append(
                ValidationIssue(
                    "event_operation_mismatch",
                    "Event type or revision disagrees with its operation record",
                    row["id"],
                )
            )

        for row in connection.execute(
            """
            SELECT ev.id
            FROM events ev
            JOIN entities actor ON actor.id = ev.actor_entity_id
            WHERE actor.world_id <> ev.world_id
            ORDER BY ev.world_id, ev.world_revision
            """
        ):
            issues.append(
                ValidationIssue(
                    "event_actor_world_mismatch",
                    "Event actor belongs to another world",
                    row["id"],
                )
            )

        for row in connection.execute(
            """
            SELECT o.operation_id, o.completed_revision, w.revision
            FROM operations o
            JOIN worlds w ON w.id = o.world_id
            WHERE o.completed_revision > w.revision
            ORDER BY o.world_id, o.completed_revision
            """
        ):
            issues.append(
                ValidationIssue(
                    "operation_revision_ahead_of_world",
                    f"Operation {row['operation_id']} is ahead of world revision {row['revision']}",
                )
            )

        for row in connection.execute(
            """
            SELECT ev.id, ev.world_id, ev.world_revision, w.revision
            FROM events ev
            JOIN worlds w ON w.id = ev.world_id
            WHERE ev.world_revision > w.revision
            ORDER BY ev.world_id, ev.world_revision
            """
        ):
            issues.append(
                ValidationIssue(
                    "event_revision_ahead_of_world",
                    f"Event {row['id']} is ahead of world revision {row['revision']}",
                )
            )

    return issues
