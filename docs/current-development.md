# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Show the copied region framework in the world editor (Manage view) — in progress

**Problem:** after instancing a world from a scenario, the world editor showed no sign that the region framework (e.g. Aerthalon's 7 kingdoms) was copied over, so it was hard to tell what the world is about. The API (`GET /api/worlds/{world_id}`) already returned `regions`; the frontend simply didn't type or render them.

**Fix (frontend-only):** the world editor now has a **Region framework** section: a source line ("Copied from scenario … at world creation. The narrator materializes these regions as real locations during play; until then they are knowledge only."), and one card per region (title, kebab-case id, level + parent, description, and materialization status — "materialized as location …" vs "not yet materialized (knowledge only)") with `└` indentation from the parent chain. Worlds not instanced from a scenario show "no region framework" instead.

**Verification:** `322` backend tests pass; `npm run lint` passes Ruff + TypeScript; `npm run frontend-build` passes; `git diff --check` passes. Live headless-Chromium check on a copy of the live DB (temp server, port 8795): opening the `world of Aerthalon` editor rendered the source line + **all 7 kingdom cards** (Caldrith, Draevenholt, Namaris, Serevar, Thurnrok, Vel'Quess, Virellea), each `kingdom · not yet materialized (knowledge only)`; opening `Harbor Town` (no scenario) rendered "This world is not instanced from a scenario, so it has no region framework." with zero cards. Port 8795 stopped and confirmed closed; temp DB removed; live DB untouched.

Suggested commit message: `Show copied region framework in the world editor`.

## Recently completed


| Idea | Completed | Commit |
| --- | --- | --- |
| Center sibling node labels on the node (same x, y) and clamp them inside the map so edge labels stay fully visible (frontend-only label layout) | 2026-08-21 | `7453b51` |
| World-region framework — scenario-authored region hierarchy instanced per world (migrations `0019_scenario_regions` + `0020_world_regions` + `0021_backfill`, scenario region CRUD + Manage-view editor, world instancing copy, context `region_framework` chain resolution + prompt rendering, expansion `region_id` binding, framework-validated `world_create_route`, SOUL guidance) | 2026-08-20 | `9fef60a` · `4c1fac6` · `5ede07a` · `2fa919e` |
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
