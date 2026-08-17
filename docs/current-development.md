# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Controlled narrator-driven lazy expansion — complete

**Goal:** allow the narrator to propose bounded new locations and links through structured, validated, revision-aware operations when play reaches an expandable boundary.

**Proposed scope:** accept one bounded structured proposal for one ordinary location tied to an existing anchor, with duplicate-name/ID/proposal checks, a default 100-location expansion budget, optional explicit containment, and optional explicit physical adjacency. Proposal acceptance is atomic, revision-aware, exactly idempotent, and available to the narrator through MCP; no route/entity/procedural geography generation is implied.

**Out of scope:** unrestricted procedural world generation, silent regeneration, multi-parent containment, and unbounded prompt/map expansion.

**Verification:** pending; this idea is only registered for the next slice.

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
| Controlled narrator-driven lazy expansion (migration 0014, bounded structured location proposals, duplicate/budget checks, atomic HTTP/MCP expansion) | 2026-08-17 | pending user commit; suggested `Add controlled location expansion` |

**Route verification:** `243` backend tests pass; `npm run lint` passes Ruff and TypeScript; `npm run frontend-build` passes; and a temporary server on port 8795 accepted route creation at revision `0 → 1`, traveled the player from `harbor` to `city` at `1 → 2` without a `location_links` row, and replayed the same travel operation with `already_applied: true` without another revision. SQLite readback confirmed `world_route_set`, `entity_route_traveled`, the route endpoints, and final player placement; port 8795 was stopped and confirmed closed.

**Expansion verification:** `248` backend tests pass; `npm run lint` passes Ruff and TypeScript; `npm run frontend-build` passes; and a temporary server on port 8795 accepted a structured `market` proposal at revision `0 → 1`, created its `city` containment and `harbor` physical link, replayed the proposal without another revision, and rejected a duplicate name with HTTP `409`. SQLite readback confirmed `location_expanded`, the proposal ledger, final location data, containment, link, and world revision; port 8795 was stopped and confirmed closed.

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
