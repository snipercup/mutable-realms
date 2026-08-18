from __future__ import annotations

import json
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from backend.persistence.database import connect_database, connect_readonly_database
from backend.world.mutations import event_id
from backend.world.worlds import WorldAdminConflict, WorldAdminNotFound

_LOCATION_HIERARCHY_EVENT = "location_hierarchy_set"
_LOCATION_SCOPE_PROMOTION_EVENT = "location_scope_promotion_set"
_MAX_KIND_LENGTH = 100


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def set_location_hierarchy(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    location_id: str,
    parent_location_id: str | None,
    kind: str | None = None,
    is_map_scope: bool = False,
    is_default_scope: bool = False,
) -> dict[str, Any]:
    """Set one location's containment and descriptive map metadata atomically."""
    if not operation_id.strip():
        raise WorldAdminConflict("operation ID must not be blank")
    if not location_id.strip():
        raise WorldAdminConflict("location ID must not be blank")
    normalized_parent = parent_location_id.strip() if parent_location_id else None
    normalized_kind = kind.strip() if kind else None
    if normalized_kind is not None and len(normalized_kind) > _MAX_KIND_LENGTH:
        raise WorldAdminConflict(f"location kind must be at most {_MAX_KIND_LENGTH} characters")
    if is_default_scope and not is_map_scope:
        raise WorldAdminConflict("a default scope must also be a map scope")
    if normalized_parent == location_id:
        raise WorldAdminConflict("location containment would create a cycle")

    request = {
        "expected_revision": expected_revision,
        "is_default_scope": is_default_scope,
        "is_map_scope": is_map_scope,
        "kind": normalized_kind,
        "location_id": location_id,
        "parent_location_id": normalized_parent,
    }
    request_json = _canonical_json(request)

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_type, request_json, result_json FROM operations "
                "WHERE world_id = ? AND operation_id = ?",
                (world_id, operation_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["operation_type"] != _LOCATION_HIERARCHY_EVENT
                    or existing["request_json"] != request_json
                ):
                    raise WorldAdminConflict(
                        "operation ID was already used for a different request"
                    )
                connection.rollback()
                result = json.loads(existing["result_json"])
                result["already_applied"] = True
                return result

            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise WorldAdminNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise WorldAdminConflict(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )
            location = connection.execute(
                "SELECT 1 FROM locations WHERE world_id = ? AND id = ?",
                (world_id, location_id),
            ).fetchone()
            if location is None:
                raise WorldAdminNotFound(f"location not found: {location_id}")
            if normalized_parent is not None:
                parent = connection.execute(
                    "SELECT 1 FROM locations WHERE world_id = ? AND id = ?",
                    (world_id, normalized_parent),
                ).fetchone()
                if parent is None:
                    raise WorldAdminConflict(f"parent location not found: {normalized_parent}")
                cycle = connection.execute(
                    """
                    WITH RECURSIVE ancestors(location_id) AS (
                        SELECT ?
                        UNION ALL
                        SELECT lc.parent_location_id
                        FROM location_containment lc
                        JOIN ancestors a ON a.location_id = lc.child_location_id
                        WHERE lc.world_id = ?
                    )
                    SELECT 1 FROM ancestors WHERE location_id = ? LIMIT 1
                    """,
                    (normalized_parent, world_id, location_id),
                ).fetchone()
                if cycle is not None:
                    raise WorldAdminConflict("location containment would create a cycle")

            connection.execute(
                "DELETE FROM location_containment WHERE world_id = ? AND child_location_id = ?",
                (world_id, location_id),
            )
            if normalized_parent is not None:
                connection.execute(
                    "INSERT INTO location_containment("
                    "world_id, child_location_id, parent_location_id) "
                    "VALUES (?, ?, ?)",
                    (world_id, location_id, normalized_parent),
                )
            connection.execute(
                """INSERT INTO location_metadata(
                    world_id, location_id, kind, is_map_scope, is_default_scope
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(world_id, location_id) DO UPDATE SET
                    kind = excluded.kind,
                    is_map_scope = excluded.is_map_scope,
                    is_default_scope = excluded.is_default_scope
                """,
                (
                    world_id,
                    location_id,
                    normalized_kind,
                    int(is_map_scope),
                    int(is_default_scope),
                ),
            )

            next_revision = expected_revision + 1
            result = {
                "already_applied": False,
                "location_id": location_id,
                "world_id": world_id,
                "world_revision": next_revision,
            }
            result_json = _canonical_json(result)
            connection.execute(
                "UPDATE worlds SET revision = ? WHERE id = ? AND revision = ?",
                (next_revision, world_id, expected_revision),
            )
            connection.execute(
                """INSERT INTO operations(
                    world_id, operation_id, operation_type, request_json,
                    result_json, completed_revision
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    world_id,
                    operation_id,
                    _LOCATION_HIERARCHY_EVENT,
                    request_json,
                    result_json,
                    next_revision,
                ),
            )
            connection.execute(
                """INSERT INTO events(
                    id, world_id, operation_id, event_type, actor_entity_id,
                    summary, payload_json, world_revision
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)""",
                (
                    event_id(world_id, operation_id),
                    world_id,
                    operation_id,
                    _LOCATION_HIERARCHY_EVENT,
                    f"Configured location hierarchy for {location_id}",
                    _canonical_json(
                        {
                            "is_default_scope": is_default_scope,
                            "is_map_scope": is_map_scope,
                            "kind": normalized_kind,
                            "location_id": location_id,
                            "parent_location_id": normalized_parent,
                        }
                    ),
                    next_revision,
                ),
            )
            connection.commit()
            return result
        except (WorldAdminConflict, WorldAdminNotFound):
            connection.rollback()
            raise
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise WorldAdminConflict(str(error)) from error


def set_location_scope_promotion(
    database_path: str | Path,
    *,
    world_id: str,
    operation_id: str,
    expected_revision: int,
    scope_location_id: str,
    location_id: str,
    is_promoted: bool,
) -> dict[str, Any]:
    """Add or remove one explicit landmark promotion for a map scope."""
    if not operation_id.strip():
        raise WorldAdminConflict("operation ID must not be blank")
    if not scope_location_id.strip() or not location_id.strip():
        raise WorldAdminConflict("scope and landmark location IDs must not be blank")
    if scope_location_id == location_id:
        raise WorldAdminConflict("a map scope cannot promote itself")
    request = {
        "expected_revision": expected_revision,
        "is_promoted": is_promoted,
        "location_id": location_id,
        "scope_location_id": scope_location_id,
    }
    request_json = _canonical_json(request)

    with connect_database(database_path) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_type, request_json, result_json FROM operations "
                "WHERE world_id = ? AND operation_id = ?",
                (world_id, operation_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["operation_type"] != _LOCATION_SCOPE_PROMOTION_EVENT
                    or existing["request_json"] != request_json
                ):
                    raise WorldAdminConflict(
                        "operation ID was already used for a different request"
                    )
                connection.rollback()
                result = json.loads(existing["result_json"])
                result["already_applied"] = True
                return result

            world = connection.execute(
                "SELECT revision FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()
            if world is None:
                raise WorldAdminNotFound(f"world not found: {world_id}")
            if world["revision"] != expected_revision:
                raise WorldAdminConflict(
                    f"expected world revision {expected_revision}, found {world['revision']}"
                )
            scope = connection.execute(
                "SELECT COALESCE(m.is_map_scope, 0) AS is_map_scope "
                "FROM locations l LEFT JOIN location_metadata m "
                "ON m.world_id = l.world_id AND m.location_id = l.id "
                "WHERE l.world_id = ? AND l.id = ?",
                (world_id, scope_location_id),
            ).fetchone()
            if scope is None:
                raise WorldAdminNotFound(f"scope location not found: {scope_location_id}")
            if not scope["is_map_scope"]:
                raise WorldAdminConflict("promotion scope must be a map scope")
            landmark = connection.execute(
                "SELECT 1 FROM locations WHERE world_id = ? AND id = ?",
                (world_id, location_id),
            ).fetchone()
            if landmark is None:
                raise WorldAdminConflict(f"location not found: {location_id}")
            direct_child = connection.execute(
                "SELECT 1 FROM location_containment "
                "WHERE world_id = ? AND child_location_id = ? AND parent_location_id = ?",
                (world_id, location_id, scope_location_id),
            ).fetchone()
            if direct_child is not None:
                raise WorldAdminConflict("direct children do not need promotion")

            if is_promoted:
                connection.execute(
                    "INSERT INTO location_scope_promotions("
                    "world_id, scope_location_id, location_id) VALUES (?, ?, ?)",
                    (world_id, scope_location_id, location_id),
                )
            else:
                connection.execute(
                    "DELETE FROM location_scope_promotions "
                    "WHERE world_id = ? AND scope_location_id = ? AND location_id = ?",
                    (world_id, scope_location_id, location_id),
                )
            next_revision = expected_revision + 1
            result = {
                "already_applied": False,
                "is_promoted": is_promoted,
                "location_id": location_id,
                "scope_location_id": scope_location_id,
                "world_id": world_id,
                "world_revision": next_revision,
            }
            connection.execute(
                "UPDATE worlds SET revision = ? WHERE id = ? AND revision = ?",
                (next_revision, world_id, expected_revision),
            )
            connection.execute(
                "INSERT INTO operations(world_id, operation_id, operation_type, "
                "request_json, result_json, completed_revision) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    world_id,
                    operation_id,
                    _LOCATION_SCOPE_PROMOTION_EVENT,
                    request_json,
                    _canonical_json(result),
                    next_revision,
                ),
            )
            connection.execute(
                "INSERT INTO events(id, world_id, operation_id, event_type, actor_entity_id, "
                "summary, payload_json, world_revision) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
                (
                    event_id(world_id, operation_id),
                    world_id,
                    operation_id,
                    _LOCATION_SCOPE_PROMOTION_EVENT,
                    f"{'Promoted' if is_promoted else 'Removed promotion for'} {location_id} "
                    f"on {scope_location_id}",
                    _canonical_json(request),
                    next_revision,
                ),
            )
            connection.commit()
            return result
        except (WorldAdminConflict, WorldAdminNotFound):
            connection.rollback()
            raise
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise WorldAdminConflict(str(error)) from error


def read_location_ancestors(
    database_path: str | Path,
    *,
    world_id: str,
    location_id: str,
    _connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return ancestors from root to immediate parent."""
    context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with context as connection:
        rows = connection.execute(
            """
            WITH RECURSIVE ancestors(id, depth) AS (
                SELECT parent_location_id, 1
                FROM location_containment
                WHERE world_id = ? AND child_location_id = ?
                UNION ALL
                SELECT lc.parent_location_id, a.depth + 1
                FROM location_containment lc
                JOIN ancestors a ON a.id = lc.child_location_id
                WHERE lc.world_id = ?
            )
            SELECT l.id, l.name, l.description, m.kind,
                   COALESCE(m.is_map_scope, 0) AS is_map_scope,
                   COALESCE(m.is_default_scope, 0) AS is_default_scope
            FROM ancestors a
            JOIN locations l ON l.world_id = ? AND l.id = a.id
            LEFT JOIN location_metadata m ON m.world_id = l.world_id AND m.location_id = l.id
            ORDER BY a.depth DESC
            """,
            (world_id, location_id, world_id, world_id),
        ).fetchall()
    return [dict(row) for row in rows]


def read_scoped_world_map(
    database_path: str | Path,
    *,
    world_id: str,
    player_location_id: str | None,
    scope_location_id: str | None = None,
    limit: int = 100,
    _connection: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Return one visible scope graph, or None for a legacy flat-world map."""
    if not 1 <= limit <= 100:
        raise ValueError("map location limit must be between 1 and 100")
    context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with context as connection:
        resolved_scope_id = scope_location_id
        if resolved_scope_id is not None:
            exists = connection.execute(
                "SELECT 1 FROM locations WHERE world_id = ? AND id = ?",
                (world_id, resolved_scope_id),
            ).fetchone()
            if exists is None:
                raise KeyError(f"location not found: {resolved_scope_id}")
        elif player_location_id is not None:
            resolved_scope_id = player_location_id
        if resolved_scope_id is None:
            return None

        base_select = """
            SELECT l.id, l.name, l.description, m.kind,
                   COALESCE(m.is_map_scope, 0) AS is_map_scope,
                   COALESCE(m.is_default_scope, 0) AS is_default_scope,
                   COALESCE(m.geography_role, 'local') AS geography_role,
                   m.direction,
                   m.range_band,
                   0 AS is_promoted,
                   0 AS is_neighbor,
                   (SELECT COUNT(*) FROM location_containment children
                    WHERE children.world_id = l.world_id
                      AND children.parent_location_id = l.id) AS child_count
            FROM locations l
            LEFT JOIN location_metadata m
              ON m.world_id = l.world_id AND m.location_id = l.id
        """
        scope = connection.execute(
            base_select + " WHERE l.world_id = ? AND l.id = ?",
            (world_id, resolved_scope_id),
        ).fetchone()
        assert scope is not None
        child_rows = connection.execute(
            base_select
            + " JOIN location_containment lc ON lc.world_id = l.world_id "
            + "AND lc.child_location_id = l.id "
            + "WHERE l.world_id = ? AND lc.parent_location_id = ? "
            + "ORDER BY l.name, l.id LIMIT ?",
            (world_id, resolved_scope_id, limit + 1),
        ).fetchall()
        sibling_select = base_select.replace("0 AS is_neighbor", "1 AS is_neighbor")
        parent = connection.execute(
            "SELECT parent_location_id FROM location_containment "
            "WHERE world_id = ? AND child_location_id = ?",
            (world_id, resolved_scope_id),
        ).fetchone()
        if parent is None:
            sibling_rows = connection.execute(
                sibling_select
                + " WHERE l.world_id = ? AND l.id <> ? "
                + "AND NOT EXISTS (SELECT 1 FROM location_containment parent "
                + "WHERE parent.world_id = l.world_id "
                + "AND parent.child_location_id = l.id) "
                + "ORDER BY l.name, l.id LIMIT ?",
                (world_id, resolved_scope_id, limit + 1),
            ).fetchall()
        else:
            sibling_rows = connection.execute(
                sibling_select
                + " JOIN location_containment sibling_parent "
                + "ON sibling_parent.world_id = l.world_id "
                + "AND sibling_parent.child_location_id = l.id "
                + "WHERE l.world_id = ? AND l.id <> ? "
                + "AND sibling_parent.parent_location_id = ? "
                + "ORDER BY l.name, l.id LIMIT ?",
                (world_id, resolved_scope_id, parent["parent_location_id"], limit + 1),
            ).fetchall()
        promoted_select = base_select.replace("0 AS is_promoted", "1 AS is_promoted")
        promoted_rows = connection.execute(
            promoted_select
            + " JOIN location_scope_promotions lsp ON lsp.world_id = l.world_id "
            + "AND lsp.location_id = l.id "
            + "WHERE lsp.world_id = ? AND lsp.scope_location_id = ? "
            + "AND NOT EXISTS (SELECT 1 FROM location_containment direct "
            + "WHERE direct.world_id = l.world_id AND direct.child_location_id = l.id "
            + "AND direct.parent_location_id = lsp.scope_location_id) "
            + "ORDER BY l.name, l.id LIMIT ?",
            (world_id, resolved_scope_id, limit + 1),
        ).fetchall()
        total = connection.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM location_containment "
            " WHERE world_id = ? AND parent_location_id = ?) + "
            "(SELECT COUNT(*) FROM location_scope_promotions promotion "
            " WHERE promotion.world_id = ? AND promotion.scope_location_id = ? "
            " AND NOT EXISTS (SELECT 1 FROM location_containment direct "
            "  WHERE direct.world_id = promotion.world_id "
            "  AND direct.child_location_id = promotion.location_id "
            "  AND direct.parent_location_id = promotion.scope_location_id))",
            (world_id, resolved_scope_id, world_id, resolved_scope_id),
        ).fetchone()[0]
        visible_children = sorted(
            [*child_rows, *promoted_rows, *sibling_rows],
            key=lambda row: (row["name"], row["id"]),
        )[:limit]
        visible_rows = [scope, *visible_children]
        visible_ids = {row["id"] for row in visible_rows}

        linked: dict[str, list[str]] = {}
        boundaries: list[dict[str, str]] = []
        for row in connection.execute(
            """
            SELECT ll.location_a, ll.location_b, a.name AS name_a, b.name AS name_b
            FROM location_links ll
            JOIN locations a ON a.world_id = ll.world_id AND a.id = ll.location_a
            JOIN locations b ON b.world_id = ll.world_id AND b.id = ll.location_b
            WHERE ll.world_id = ? ORDER BY ll.location_a, ll.location_b
            """,
            (world_id,),
        ):
            first, second = row["location_a"], row["location_b"]
            if first in visible_ids and second in visible_ids:
                linked.setdefault(first, []).append(second)
                linked.setdefault(second, []).append(first)
            elif first in visible_ids:
                boundaries.append(
                    {
                        "from_location_id": first,
                        "to_location_id": second,
                        "to_location_name": row["name_b"],
                    }
                )
            elif second in visible_ids:
                boundaries.append(
                    {
                        "from_location_id": second,
                        "to_location_id": first,
                        "to_location_name": row["name_a"],
                    }
                )

        route_chain: list[dict[str, Any]] = []
        pending: list[tuple[str, int, tuple[str, ...]]] = [(resolved_scope_id, 0, ())]
        seen_routes: set[str] = set()
        while pending and len(route_chain) < 100:
            origin_id, depth, route_path = pending.pop(0)
            for route in connection.execute(
                """
                SELECT r.route_id, r.name, r.description, r.route_kind,
                       r.origin_location_id, r.destination_location_id,
                       destination.name AS destination_name,
                       COALESCE(metadata.geography_role, 'route') AS geography_role,
                       metadata.direction, metadata.range_band
                FROM world_routes r
                JOIN locations destination
                  ON destination.world_id = r.world_id
                 AND destination.id = r.destination_location_id
                LEFT JOIN location_metadata metadata
                  ON metadata.world_id = r.world_id
                 AND metadata.location_id = r.destination_location_id
                WHERE r.world_id = ? AND r.origin_location_id = ? AND r.is_active = 1
                ORDER BY r.route_id
                """,
                (world_id, origin_id),
            ):
                route_id = route["route_id"]
                if route_id in seen_routes or route_id in route_path:
                    continue
                seen_routes.add(route_id)
                route_chain.append({**dict(route), "chain_depth": depth + 1})
                pending.append(
                    (
                        route["destination_location_id"],
                        depth + 1,
                        (*route_path, route_id),
                    )
                )
        range_order = {"short": 0, "mid": 1, "long": 2}
        route_chain.sort(
            key=lambda item: (
                range_order.get(item["range_band"], 3),
                item["chain_depth"],
                item["direction"] or "",
                item["name"],
                item["route_id"],
            )
        )

        counts: dict[str, dict[str, int]] = {}
        for row in connection.execute(
            """
            SELECT el.location_id, e.kind, COUNT(*) AS count
            FROM entity_locations el
            JOIN entities e ON e.id = el.entity_id
            WHERE e.world_id = ? AND el.location_id IS NOT NULL
            GROUP BY el.location_id, e.kind ORDER BY el.location_id, e.kind
            """,
            (world_id,),
        ):
            counts.setdefault(row["location_id"], {})[row["kind"]] = row["count"]

        ancestors = read_location_ancestors(
            database_path,
            world_id=world_id,
            location_id=resolved_scope_id,
            _connection=connection,
        )
        breadcrumbs = [
            {
                key: ancestor[key]
                for key in ("id", "name", "kind", "is_map_scope", "is_default_scope")
            }
            for ancestor in ancestors
        ]
        player_visible_location_id = None
        if player_location_id in visible_ids:
            player_visible_location_id = player_location_id
        elif player_location_id is not None:
            player_ancestors = read_location_ancestors(
                database_path,
                world_id=world_id,
                location_id=player_location_id,
                _connection=connection,
            )
            player_visible_location_id = next(
                (
                    ancestor["id"]
                    for ancestor in reversed(player_ancestors)
                    if ancestor["id"] in visible_ids
                ),
                None,
            )

    locations = [
        {
            **dict(row),
            "entity_kinds": counts.get(row["id"], {}),
            "linked_location_ids": sorted(linked.get(row["id"], [])),
        }
        for row in sorted(visible_rows, key=lambda item: (item["name"], item["id"]))
    ]
    return {
        "boundary_links": sorted(
            boundaries,
            key=lambda item: (item["from_location_id"], item["to_location_id"]),
        ),
        "route_chain": route_chain,
        "breadcrumbs": breadcrumbs,
        "child_total": total,
        "has_more": total > limit,
        "locations": locations,
        "player_location_id": player_location_id,
        "player_visible_location_id": player_visible_location_id,
        "scope_location": {
            key: scope[key] for key in ("id", "name", "kind", "is_map_scope", "is_default_scope")
        },
    }


def read_location_descendants(
    database_path: str | Path,
    *,
    world_id: str,
    location_id: str,
    limit: int = 100,
    _connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return descendants breadth-first with a strict response bound."""
    if not 1 <= limit <= 100:
        raise ValueError("location descendant limit must be between 1 and 100")
    context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with context as connection:
        rows = connection.execute(
            """
            WITH RECURSIVE descendants(id, depth, path) AS (
                SELECT child_location_id, 1, '|' || child_location_id || '|'
                FROM location_containment
                WHERE world_id = ? AND parent_location_id = ?
                UNION ALL
                SELECT lc.child_location_id, d.depth + 1,
                       d.path || lc.child_location_id || '|'
                FROM location_containment lc
                JOIN descendants d ON d.id = lc.parent_location_id
                WHERE lc.world_id = ?
                  AND instr(d.path, '|' || lc.child_location_id || '|') = 0
            )
            SELECT l.id, l.name, l.description, d.depth, m.kind,
                   COALESCE(m.is_map_scope, 0) AS is_map_scope,
                   COALESCE(m.is_default_scope, 0) AS is_default_scope
            FROM descendants d
            JOIN locations l ON l.world_id = ? AND l.id = d.id
            LEFT JOIN location_metadata m ON m.world_id = l.world_id AND m.location_id = l.id
            ORDER BY d.depth, l.name, l.id
            LIMIT ?
            """,
            (world_id, location_id, world_id, world_id, limit + 1),
        ).fetchall()
    return {
        "has_more": len(rows) > limit,
        "locations": [dict(row) for row in rows[:limit]],
    }


def read_location_children(
    database_path: str | Path,
    *,
    world_id: str,
    parent_location_id: str,
    limit: int = 100,
    _connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Return a stable, bounded page of direct children."""
    if not 1 <= limit <= 100:
        raise ValueError("location child limit must be between 1 and 100")
    context = (
        closing(connect_readonly_database(database_path))
        if _connection is None
        else nullcontext(_connection)
    )
    with context as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM location_containment "
            "WHERE world_id = ? AND parent_location_id = ?",
            (world_id, parent_location_id),
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT l.id, l.name, l.description, m.kind,
                   COALESCE(m.is_map_scope, 0) AS is_map_scope,
                   COALESCE(m.is_default_scope, 0) AS is_default_scope
            FROM location_containment lc
            JOIN locations l ON l.world_id = lc.world_id AND l.id = lc.child_location_id
            LEFT JOIN location_metadata m ON m.world_id = l.world_id AND m.location_id = l.id
            WHERE lc.world_id = ? AND lc.parent_location_id = ?
            ORDER BY l.name, l.id
            LIMIT ?
            """,
            (world_id, parent_location_id, limit),
        ).fetchall()
    return {"has_more": total > len(rows), "locations": [dict(row) for row in rows], "total": total}
