# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Lively semantic map shapes and a larger map canvas — in progress

**Goal:** make the map communicate the character of the current location instead of representing every place as an identical circle. The map should become twice as high, then use bounded semantic shapes appropriate to the current scale and setting: individual buildings along a street, street clusters within a district, simplified district clusters within a city, and distinct visual motifs for places such as mines and forests.

**Recommendation:** keep the narrator responsible for choosing **semantic map forms**, but keep SVG geometry deterministic in the frontend. The narrator must never emit raw SVG, arbitrary paths, CSS, scripts, or executable drawing instructions. A validated vocabulary such as `building`, `street`, `district`, `city`, `mine`, `forest`, `water`, and `landmark`, plus bounded presentation hints, gives the narrator creative control while keeping rendering safe, testable, and consistent.

**Proposed scope:**

- Increase the SVG map canvas height from `320` to `640` while preserving the current width unless layout testing shows that width also needs adjustment.
- Define a small, extensible semantic visual vocabulary for map locations and clusters. Start with street buildings, street segments, district clusters, simplified city districts, mine entrances/tunnels, forest patches/trees, water/coast, and generic landmarks.
- Let the narrator select the semantic form from the current opening context and location meaning; validate the value against an allowlist and apply deterministic defaults when omitted.
- Represent shapes as derived SVG primitives and bounded deterministic geometry—rectangles, polygons, paths from fixed templates, lines, clusters, and symbols—not narrator-authored arbitrary SVG.
- Use containment and scale to compose forms: a street's direct child buildings form a building row or block; a district's street children form bounded street clusters; a city's district children form a simplified district arrangement. Do not infer new authoritative locations from visual geometry.
- Keep child/sibling separation from the previous slice: child forms occupy the central layer, sibling forms remain on the perimeter/border layer, and the border remains visually compact.
- Preserve direction/range metadata for placement and use `kind`, geography role, and semantic form for rendering style. Missing or invalid presentation hints fall back to the generic node without rejecting an otherwise valid world.
- Keep entity counts, labels, route information, and accessibility text visible even when a location uses a non-circular shape.
- Keep all geometry bounded, deterministic, collision-aware, and derived from the current map response. The same authoritative state must produce the same rendered map after refresh.
- Add browser-verifiable data attributes for semantic form, scale/layer, and shape template so frontend tests can assert rendering without relying only on pixels.

**Out of scope:**

- Narrator-generated SVG, arbitrary drawing code, unbounded procedural geometry, or user-authored executable map content.
- New movement rules, automatic roads/routes, coordinate systems, or changes to containment.
- A full GIS engine, realistic cartography, terrain simulation, animation, zoom/pan system, or 3D rendering.
- Making the visualization authoritative or requiring every location to have a custom shape.

**Implementation status:** migration `0016_location_map_forms` adds an allowlisted `map_form` presentation hint. Structured narrator starts accept and validate the semantic form, persist it with the location metadata, and the frontend now renders fixed SVG templates for buildings, streets, districts/cities, mines, forests, water, and landmarks. The map canvas is now 640px high. Street scopes—including existing `Main Street` data whose hint predates this field—lay child buildings out in two lines beside a central road with dashed lane markings instead of a circular arrangement. Street child labels and metadata now sit outside each building, on the side away from the road, so text does not cover either the shape or the road visual. Raw SVG remains impossible through the narrator contract.

**Verification:** targeted contract and persistence tests are in progress. Full suite, lint, frontend build, and live/browser verification remain before completion.

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
| Larger street-level narrator starts (16-location bound, ten Main Street children, atomic persistence) | 2026-08-19 | `70c95d9` |

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
