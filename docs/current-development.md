# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### World-region framework — scenario-authored region hierarchy, instanced per world — scoped

**Goal:** give the narrator authoritative knowledge about the world's structure *before* it expands locations: kingdoms → provinces → cities (or whatever levels a scenario uses), each with descriptions, biomes/species/attributes, and declared connections. Without this, new locations are generic ("same context as the main street"). With it, a cave generated on the road in Virellea is born knowing it sits in Virellea's sunlit plains, and inter-kingdom travel routes are validated against declared adjacency.

**Key decisions (from user):**
- **The framework lives in the scenario**, like other scenario info. Every world instanced from a scenario gets the same framework (a copy), while the narrator may generate *different locations* in each world instance.
- **Not all scenarios are Aerthalon.** Levels are generic, not hard-coded to kingdom/province/city: a school scenario may have one "kingdom" (the school grounds) with sub-locations below; an interplanetary scenario may treat each planet as a top-level region. The hierarchy shape (parent → children, free-form level names) is the contract.
- **CRUD access** for the author, like the rest of the scenario data (scenario CRUD + elements pattern, Manage view).

**Design:**
- Migration `0019_scenario_regions`: `scenario_regions(scenario_id, region_id, parent_region_id, level, title, description, attributes_json)`, PK `(scenario_id, region_id)`, self-referential parent within the same scenario; `level` is free-form text (validated non-empty) so scenarios define their own hierarchy vocabulary.
- Scenario authoring services: create/update/delete scenario regions (revision-less admin ledger like `scenario_operations`), mirroring `scenarios.py`.
- Migration `0020_world_regions`: instanced copy `world_regions(world_id, region_id, parent_region_id, level, title, description, attributes_json, location_id NULL)` — copied from the scenario at world creation (alongside `world_elements`); `location_id` is the play-side binding filled in when the narrator materializes a region as a real location via expansion.
- Context: `build_world_context` resolves the player's region chain (walk containment from the current location until a location bound to a region, then include all ancestor regions — city → province → kingdom) with descriptions + attributes + declared connections; prompt renders it as authoritative `Region framework`.
- Expansion: `world_expand_location` gains optional `region_id` to bind a new location to its framework region (keeps the two layers in sync; one mutation per turn unchanged).
- Routes: narrator-facing `world_create_route` (currently admin-only `create_route`), validated against declared connections — a route is accepted only when its endpoints belong to regions the framework declares adjacent (or within the same region). Inter-kingdom travel = link (adjacent) or route (long-distance), both already authoritative for movement.
- Narrator guidance (SOUL + prompt): materialize a region when the player heads there; bind new places to their region; route only to declared neighbors; never narrate crossing a border you haven't linked or routed.

**Out of scope (this slice):** auto-materializing regions as locations; rendering regions on the player map (regions are knowledge, not playable nodes — they become locations only when materialized). The Manage-view region editor **is in scope** and is step 4 of this slice.

**Implementation status (steps 1, 2, and 4 complete — scenario-side framework + world instancing copy + Manage-view editor; committed `9fef60a` + `4c1fac6`):** migration `0019_scenario_regions` (hierarchy with free-form `level`, description, `attributes_json`, self-referential parent with cascade delete, cycle guard) and scenario authoring services `set_scenario_region` / `remove_scenario_region` (upsert + cascade remove, exact operation-ID idempotency via `scenario_operations`), with HTTP `PUT`/`DELETE /api/scenarios/{scenario_id}/regions/{region_id}` and `ScenarioRead.regions` read model. The Manage-view scenario editor now includes a **Region framework** section: hierarchical region cards (indented by depth), Add/Edit forms (level, parent select excluding self, title, description, pretty-printed attributes JSON), Save via `PUT`, Delete with descendant-cascade confirm. **Step 2 (instancing copy):** migration `0020_world_regions` (same hierarchy shape as `scenario_regions` plus the nullable play-side `location_id` binding, `ON DELETE SET NULL` to locations, self-referential parent with cascade) — `create_world_from_scenario` now copies scenario regions into `world_regions` alongside elements, reports `copied_regions` in its result, and `read_world` / `WorldDetailRead` return the instanced regions (with `location_id: null` until the narrator materializes them). The live `world-of-aerthalon` scenario carries all 7 kingdoms with a fully closed road network (zero declared-but-missing targets; Caldrith's aerial/magical contact stored separately under `connected_by_magic_to`). Remaining steps: context region-chain resolution + prompt rendering, expansion `region_id` binding, narrator-facing framework-validated `world_create_route`, SOUL/prompt guidance.

**Verification (steps 1 + 2 + 4):** `310` backend tests pass; `npm run lint` passes Ruff and TypeScript; `npm run frontend-build` passes; `git diff --check` passes. Live verification on a temporary server (port 8795, no real narrator): scenario `aerthalon` seeded via API with kingdoms `virellea`/`thurnrok`, province `virellea-elaris-province`, city `virellea-elaris` (parent + biomes/species/connections attributes); headless Chromium on the Manage view rendered all region cards in hierarchy order with `└` indentation, opened the Add-region editor (id editable, parent select populated, self excluded), opened the Edit form for `virellea` (id disabled, self excluded from parents, attributes loaded pretty-printed), and a full UI round-trip created city `virellea-greenwatch` as a child of `virellea` — confirmed persisted server-side with attributes. Step 2 instancing verified live on a copy of the real live DB: `POST /api/worlds` from `world-of-aerthalon` created `aerthalon-new-campaign` at revision 1 copying **all 7 kingdoms** into `world_regions` (correct levels, no parents, `location_id: null`, roads + attributes intact, 3 story elements copied), and exact replay returned `already_applied: true` without a second world. Port 8795 stopped and confirmed closed; temp DB removed; live DB untouched.

## Recently completed


| Idea | Completed | Commit |
| --- | --- | --- |
| Bound the narrator's turn output to 200 tokens (prompt instruction + SOUL.md rule + deterministic sentence-safe `bound_narration_tokens()` cap; no model-level token cap because Hermes applies `model.max_tokens` to the whole completion including tool calls) | 2026-08-20 | `03b0454` |
| Persist narration history so the page can reload the last messages (migration `0017_narration_history`, append/read service, `GET /api/worlds/{world_id}/narration`, record start + narrated turns, frontend history reload) | 2026-08-20 | `d2216db` |
| Feed recent narration history back into the narrator's context (story-so-far prompt block, 32k-token bound, turn route attaches history) | 2026-08-20 | `08e9114` |
| Let the narrator orient and enter newly expanded locations (map–story alignment: `direction`/`range_band`/`map_form` metadata + atomic `move_actor_to_location` on `world_expand_location`, one revision, exact idempotency) | 2026-08-20 | `76a4e7c` |
| Location memories — narrator-maintained narrative facts for places (migration `0018_location_memories`, dedup by normalized `memory_key` with `occurrence_count`, atomic record/consolidate operations, 1000-token render budget for the current location only, MCP tools + SOUL guidance) | 2026-08-20 | `1a81da0` |
| Cap the visible recent-events list (3 items) so it cannot push the input bar down (CSS-only: `max-height: 228px` + `overflow-y: auto` on `.event-list`) | 2026-08-20 | `b0a0a28` |
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
| Edge-strip sibling map placement (landscape canvas matching the panel, 32px reserved edge strip, sibling labels above nodes, deterministic no-overlap lane packing) | 2026-08-20 | `389b766` · `2f4a71e` · `3fa1b2b` |

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
