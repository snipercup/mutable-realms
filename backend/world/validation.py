from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.persistence.database import connect_readonly_database


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    entity_id: str | None = None


def validate_worlds(database_path: str | Path) -> list[ValidationIssue]:
    """Return deterministic integrity and domain-invariant violations."""
    issues: list[ValidationIssue] = []
    with connect_readonly_database(database_path) as connection:
        for row in connection.execute("PRAGMA foreign_key_check"):
            issues.append(
                ValidationIssue(
                    "foreign_key_violation",
                    f"Foreign key violation in {row['table']} row {row['rowid']}",
                )
            )

        for row in connection.execute(
            """
            WITH RECURSIVE walk(world_id, start_id, current_id, path, cycle) AS (
                SELECT world_id, child_location_id, parent_location_id,
                       '|' || child_location_id || '|' || parent_location_id || '|',
                       child_location_id = parent_location_id
                FROM location_containment
                UNION ALL
                SELECT walk.world_id, walk.start_id, lc.parent_location_id,
                       walk.path || lc.parent_location_id || '|',
                       instr(walk.path, '|' || lc.parent_location_id || '|') > 0
                FROM walk
                JOIN location_containment lc
                  ON lc.world_id = walk.world_id
                 AND lc.child_location_id = walk.current_id
                WHERE walk.cycle = 0
            )
            SELECT DISTINCT world_id, start_id FROM walk
            WHERE cycle = 1 ORDER BY world_id, start_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "location_containment_cycle",
                    "Location containment contains a cycle",
                    row["start_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT p.scope_location_id, p.location_id
            FROM location_scope_promotions p
            LEFT JOIN location_metadata m
              ON m.world_id = p.world_id AND m.location_id = p.scope_location_id
            WHERE COALESCE(m.is_map_scope, 0) = 0
            ORDER BY p.world_id, p.scope_location_id, p.location_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "location_promotion_scope_not_map",
                    "Location promotion targets a non-map scope",
                    row["location_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT p.scope_location_id, p.location_id
            FROM location_scope_promotions p
            JOIN location_containment c
              ON c.world_id = p.world_id
             AND c.child_location_id = p.location_id
             AND c.parent_location_id = p.scope_location_id
            ORDER BY p.world_id, p.scope_location_id, p.location_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "location_promotion_redundant",
                    "Location promotion duplicates a direct child of the scope",
                    row["location_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT p.proposal_id
            FROM world_expansion_proposals p
            LEFT JOIN locations l
              ON l.world_id = p.world_id AND l.id = p.location_id
            LEFT JOIN locations a
              ON a.world_id = p.world_id AND a.id = p.anchor_location_id
            WHERE l.id IS NULL OR a.id IS NULL
            ORDER BY p.world_id, p.proposal_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "expansion_proposal_invalid",
                    "Expansion proposal has a missing location or anchor",
                    row["proposal_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT r.route_id
            FROM world_routes r
            LEFT JOIN locations o
              ON o.world_id = r.world_id AND o.id = r.origin_location_id
            LEFT JOIN locations d
              ON d.world_id = r.world_id AND d.id = r.destination_location_id
            WHERE o.id IS NULL OR d.id IS NULL
               OR r.origin_location_id = r.destination_location_id
            ORDER BY r.world_id, r.route_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "route_endpoint_invalid",
                    "Route has missing or identical endpoints",
                    row["route_id"],
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

        for row in connection.execute(
            """
            SELECT r.world_id, r.subject_entity_id, r.object_entity_id
            FROM relationships r
            JOIN entities subject ON subject.id = r.subject_entity_id
            JOIN entities object ON object.id = r.object_entity_id
            WHERE subject.world_id <> r.world_id
               OR object.world_id <> r.world_id
               OR r.subject_entity_id = r.object_entity_id
            ORDER BY r.world_id, r.subject_entity_id, r.object_entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "relationship_world_mismatch",
                    "Relationship endpoints do not belong to its world",
                    row["subject_entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT r.subject_entity_id, r.object_entity_id
            FROM relationships r
            LEFT JOIN characters subject ON subject.entity_id = r.subject_entity_id
            LEFT JOIN characters object ON object.entity_id = r.object_entity_id
            WHERE subject.entity_id IS NULL OR object.entity_id IS NULL
            ORDER BY r.world_id, r.subject_entity_id, r.object_entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "relationship_endpoint_not_character",
                    "Relationship endpoint is missing character state",
                    (
                        row["subject_entity_id"]
                        if row["subject_entity_id"]
                        else row["object_entity_id"]
                    ),
                )
            )

        for row in connection.execute(
            """
            SELECT m.id
            FROM memories m
            JOIN events ev ON ev.id = m.event_id
            WHERE m.world_id <> ev.world_id
            ORDER BY m.world_id, m.id
            """
        ):
            issues.append(
                ValidationIssue(
                    "memory_event_world_mismatch",
                    "Memory and linked event belong to different worlds",
                    row["id"],
                )
            )

        for row in connection.execute(
            """
            SELECT r.world_id, r.subject_entity_id, r.object_entity_id,
                   r.updated_event_id, ev.world_id AS event_world_id,
                   ev.world_revision
            FROM relationships r
            LEFT JOIN events ev ON ev.id = r.updated_event_id
            WHERE ev.id IS NULL
               OR ev.world_id <> r.world_id
               OR ev.event_type <> 'social_interaction_recorded'
               OR ev.world_revision > (SELECT revision FROM worlds WHERE id = r.world_id)
               OR json_extract(ev.payload_json, '$.relationship_score') <> r.score
               OR json_extract(ev.payload_json, '$.relationship_category') <> r.category
            ORDER BY r.world_id, r.subject_entity_id, r.object_entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "relationship_updated_event_mismatch",
                    "Relationship update event is missing or belongs to another revision/world",
                    row["subject_entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT m.id, m.world_id, entity.world_id AS entity_world_id
            FROM memories m
            JOIN entities entity ON entity.id = m.entity_id
            WHERE entity.world_id <> m.world_id
            ORDER BY m.world_id, m.id
            """
        ):
            issues.append(
                ValidationIssue(
                    "memory_entity_world_mismatch",
                    "Memory owner belongs to another world",
                    row["id"],
                )
            )

        for row in connection.execute(
            """
            SELECT r.world_id, r.owner_entity_id, entity.world_id AS entity_world_id
            FROM resources r
            JOIN entities entity ON entity.id = r.owner_entity_id
            WHERE entity.world_id <> r.world_id
            ORDER BY r.world_id, r.owner_entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "resource_owner_world_mismatch",
                    "Resource owner belongs to another world",
                    row["owner_entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT r.owner_entity_id
            FROM resources r
            LEFT JOIN characters owner ON owner.entity_id = r.owner_entity_id
            WHERE owner.entity_id IS NULL
            ORDER BY r.world_id, r.owner_entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "resource_owner_not_character",
                    "Resource owner is missing character state",
                    row["owner_entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT r.world_id, r.owner_entity_id, r.updated_event_id,
                   ev.world_id AS event_world_id, ev.world_revision
            FROM resources r
            LEFT JOIN events ev ON ev.id = r.updated_event_id
            WHERE ev.id IS NULL
               OR ev.world_id <> r.world_id
               OR ev.event_type <> 'resource_transferred'
               OR ev.world_revision > (SELECT revision FROM worlds WHERE id = r.world_id)
            ORDER BY r.world_id, r.owner_entity_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "resource_updated_event_mismatch",
                    "Resource update event is missing or belongs to another revision/world",
                    row["owner_entity_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT we.world_id, we.element_type, we.updated_event_id,
                   ev.world_id AS event_world_id, ev.world_revision
            FROM world_elements we
            LEFT JOIN events ev ON ev.id = we.updated_event_id
            WHERE ev.id IS NULL
               OR ev.world_id <> we.world_id
               OR ev.world_revision > (SELECT revision FROM worlds WHERE id = we.world_id)
            ORDER BY we.world_id, we.element_type
            """
        ):
            issues.append(
                ValidationIssue(
                    "world_element_updated_event_mismatch",
                    "World element update event is missing or belongs to another revision/world",
                    row["element_type"],
                )
            )

        for row in connection.execute(
            """
            SELECT lp.world_id, lp.location_id, location.world_id AS location_world_id
            FROM location_properties lp
            JOIN locations location ON location.id = lp.location_id
            WHERE location.world_id <> lp.world_id
            ORDER BY lp.world_id, lp.location_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "location_property_world_mismatch",
                    "Location property belongs to another world",
                    row["location_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT lp.world_id, lp.location_id, lp.updated_event_id,
                   ev.world_id AS event_world_id, ev.world_revision
            FROM location_properties lp
            LEFT JOIN events ev ON ev.id = lp.updated_event_id
            WHERE ev.id IS NULL
               OR ev.world_id <> lp.world_id
               OR ev.event_type <> 'location_updated'
               OR ev.world_revision > (SELECT revision FROM worlds WHERE id = lp.world_id)
            ORDER BY lp.world_id, lp.location_id
            """
        ):
            issues.append(
                ValidationIssue(
                    "location_property_updated_event_mismatch",
                    "Location property update event is missing or belongs to "
                    "another revision/world",
                    row["location_id"],
                )
            )

        for row in connection.execute(
            """
            SELECT ll.world_id, ll.location_a
            FROM location_links ll
            JOIN locations la ON la.id = ll.location_a
            JOIN locations lb ON lb.id = ll.location_b
            WHERE la.world_id <> ll.world_id OR lb.world_id <> ll.world_id
            ORDER BY ll.world_id, ll.location_a
            """
        ):
            issues.append(
                ValidationIssue(
                    "location_link_world_mismatch",
                    "Location link endpoint belongs to another world",
                    row["location_a"],
                )
            )

    return issues
