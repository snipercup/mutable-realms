# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Directional sibling edge placement without the center ring — in progress

**Goal:** keep sibling locations out of the child overview by placing them directly against the map element's edge. Their edge position should reflect their direction relative to the current location: north at the top, south at the bottom, east on the right, west on the left, and diagonal directions near the corresponding corners.

**Recommendation:** remove the obsolete centered dotted ring entirely. Use the rectangular map boundary as the visual separation: children remain in the central/street composition, while siblings hug an inset from the relevant edge. Directional edge placement is clearer than a second interior ring and gives players an immediate sense of where travel or neighboring geography lies.

**Scope:**

- Use derived frontend placement only; do not change authoritative locations, links, routes, or direction metadata.
- Place cardinal siblings along the corresponding map edge and diagonal siblings near the corresponding corner.
- Keep a small inset so sibling shapes and labels remain visible rather than clipped by the SVG viewport.
- Reserve a 64-pixel strip inside every edge of the rectangular map element and place sibling nodes inside that strip.
- Render the reserved edge strip as a subtle visual (low-opacity band plus a thin inner boundary line) that does not draw attention.
- Apply deterministic offsets for multiple siblings sharing a direction or edge.
- Use deterministic edge fallback for siblings without direction metadata.
- Place sibling labels and direction/range metadata inward from the edge without covering child buildings or the street road.
- Remove the centered dotted `map-scope-border` ring; the map edge and layer separation provide the visual boundary.
- Preserve the central child layout, Main Street road visualization, semantic map forms, and flat-map fallback.

**Out of scope:** changes to containment, movement links, route semantics, coordinates, authoritative map state, or narrator-generated geometry.

**Implementation status:** the centered dotted ring and its CSS are removed; the ring radius constants and the old interior-perimeter projection path are deleted. The map canvas is landscape (`800 × 480`, viewBox aspect matching the wide page panel) so the derived map fills the element's rectangle instead of a portrait letterbox. Scoped maps place siblings only through the rectangular edge projection, with cardinal directions on the matching edge, diagonals near corners, deterministic same-edge offsets, and an edge fallback for missing directions. A 64-pixel reserved strip is drawn inside every edge (`map-edge-strip` low-opacity band plus `map-edge-strip-inner` thin boundary line), and sibling nodes are centered within that strip so they hug the rectangular map border on all four sides. The street road and central child layouts are unchanged and fit the landscape canvas.

**Verification:** `272` backend tests pass; `npm run lint` passes Ruff and TypeScript; `npm run frontend-build` passes; and `git diff --check` passes. Live DOM measurement against the recreated Aerthalon world on port 8790 confirmed the fresh bundle is served, the SVG renders landscape (`1100 × 660`, aspect `1.667` matching the `800 × 480` viewBox), the strip band sits `44px` inside every edge (equal on left/right/top/bottom), the south sibling (Lantern Plaza) sits at `y=448` (32 units from the bottom edge) and the east sibling (River Elaris bridge) at `x=768` (32 units from the right edge), and the ten child buildings remain in two rows clear of the strip. No authoritative state was touched.

## Recently completed


| Idea | Completed | Commit |
| --- | --- | --- |
| Scenario authoring and world management (scenario CRUD + elements, world instancing, world update/elements/remove) | 2026-08-08 | on main via `scenario-authoring` · `world-instancing` · `world-management` |
| World management interface (play ⇄ manage view, scenario/world CRUD UI, instancing, `#manage` deep link) | 2026-08-10 | on main via `world-management-interface` |
| Player provisioning (create a player + starting location so instanced worlds are playable; play view empty state) | 2026-08-10 | on main via `player-provisioning` |
| Reusable player characters and world-specific instances (character CRUD, selection, copied world instances) | 2026-08-16 | on main via `reusable-player-characters` |
| Narrator-driven world start (structured opening, atomic character/location instancing, polling/error hardening) | 2026-08-16 | `9b00c16` |
| Nested locations and scoped world maps (migration 0011, hierarchy validation, scoped reads, context breadcrumbs, map navigation) | 2026-08-17 | `8c581c9` |
| Cross-scale landmark promotion (migration 0012, validated presentation promotions, promoted scoped-map nodes, HTTP administration) | 2026-08-17 | `a3bcfea` |
| Detailed travel and explicit routes (migration 0013, directed route definitions, exact-origin route travel, HTTP and MCP seams) | 2026-08-17 | `1531e67` |
| Controlled narrator-driven lazy expansion (migration 0014, bounded structured location proposals, duplicate/budget checks, atomic HTTP/MCP expansion) | 2026-08-17 | `108ed5e` |
| Narrator-driven contextual starting locations (bounded structured start layouts, contextual player placement, containment/link creation, atomic replay-safe start) | 2026-08-17 | `7ec6bc0` |
| Scoped map presentation polish (omit scope anchor node, remove redundant child list, preserve boundary exits, suppress internal scoped-map link edges) | 2026-08-17 | `78a8875` |
| Hide current location from scoped maps (scope metadata only, no player highlight) | 2026-08-18 | `c793cdf` |
| Require sibling locations in structured world starts (3–6 bounded locations with child + sibling topology) | 2026-08-18 | `c1add38` |
| Boundary geography orientation metadata (geography role, direction, range band; migration `0015`) | 2026-08-18 | `9f29fa1` |
| Explicit route-chain visualization for scoped maps (bounded active route traversal, short/mid/long lanes, informational frontend display) | 2026-08-18 | `28685d9` |
| Separate bounded world-start narration timeout (distinct 240 s start deadline, measured timeout logging, player-friendly HTTP message preserved) | 2026-08-19 | `b72fe38` |
| Coarse geographic orientation for sibling locations (direction/range ordering and deterministic map placement) | 2026-08-19 | `347d30f` |
| Separate scoped-map children and sibling neighbors (central child layer, compact perimeter sibling layer, visual border) | 2026-08-19 | `63bc423` |
| Lively semantic map shapes and street visualization (map forms, larger canvas, two-sided buildings, central road, external labels) | 2026-08-19 | `1d9422b` |

**Route verification:** `243` backend tests pass; `npm run lint` passes Ruff and TypeScript; `npm run frontend-build` passes; and a temporary server on port 8795 accepted route creation at revision `0 → 1`, traveled the player from `harbor` to `city` at `1 → 2` without a `location_links` row, and replayed the same travel operation with `already_applied: true` without another revision. SQLite readback confirmed `world_route_set`, `entity_route_traveled`, the route endpoints, and final player placement; port 8795 was stopped and confirmed closed.

**Expansion verification:** `248` backend tests pass; `npm run lint` passes Ruff and TypeScript; `npm run frontend-build` passes; and a temporary server on port 8795 accepted a structured `market` proposal at revision `0 → 1`, created its `city` containment and `harbor` physical link, replayed the proposal without another revision, and rejected a duplicate name with HTTP `409`. SQLite readback confirmed `location_expanded`, the proposal ledger, final location data, containment, link, and world revision; port 8795 was stopped and confirmed closed.

**Contextual-start verification:** `252` backend tests pass; `npm run lint` passes Ruff and TypeScript; `npm run frontend-build` passes; and a temporary server on port 8795 started an Aerthalon-like world at **Main Street** with the Adventurer's Guild as a child location and an explicit local link. The world revision advanced `1 → 2`; SQLite readback confirmed the narration was stored in the same operation result, and exact replay returned the identical response without another revision. Same-world name collisions are rejected rather than silently duplicated; port 8795 was stopped and confirmed closed. An independent review found and the implementation fixed a separate-transaction replay hazard before closeout.

**Scoped-map polish verification:** `256` backend tests pass; `npm run lint` passes Ruff and TypeScript; `npm run frontend-build` passes; and `git diff --check` passes. Temporary HTTP verification served the rebuilt frontend and confirmed the scoped map API continued returning boundary exits; the user then manually verified the Aerthalon map after pushing `78a8875`. The temporary server was stopped and port 8795 was confirmed closed. The backend map contract and authoritative movement data were unchanged.

## How an idea becomes work

1. **User describes the idea in prose** — no format required.
2. **Restate as a scoped slice** — goal, what changes, what is out of scope, how to verify. Follow the vertical-slice pattern in the maintenance guide (migration → operation → context → validation → agent surface → turn policy → docs → tests) unless the idea is presentation-only.
3. **Record the scope here** (status: scoped / in progress) before implementing.
4. **Implement and verify** — full suite, lint, and live verification proportional to risk.
5. **Flip status to complete** with verification evidence and a suggested branch + commit message; the user commits and pushes.
6. **Close the entry.** If the idea is postponed mid-way, move it as one line into the readme *Roadmap* and mark it abandoned here.

Notes on the process, learned during the plan era and still enforced:

- One supported mutation per narrated turn; authoritative state is SQLite; narration and visualization are derived views.
- Never claim a capability works without real verification output (tests + live evidence).
- Keep the tracker small: one active idea, a short closed trail, no backlog accumulation.
