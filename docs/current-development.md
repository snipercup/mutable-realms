# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Cross-scale landmark promotion — proposed

**Goal:** allow selected nested locations—such as a mine, major road, or sinkhole—to appear on a broader province or kingdom overview without duplicating them or changing their physical containment.

**Proposed scope:** add explicit presentation-only scope markers, validate that promoted locations belong to the same world, include them in bounded scoped-map reads, and prove that promotion does not create movement adjacency or alter the location’s single containment parent.

**Out of scope:** fast travel, route generation, travel time/cost, narrator-driven location creation, automatic geography generation, and multi-parent containment.

**Verification:** complete. Migration `0011_location_hierarchy` adds same-world containment and descriptive scope metadata without changing legacy locations. Tests cover atomic hierarchy configuration, exact replay, cross-world parent rejection, cycle rejection and whole-world cycle diagnostics, ordered breadcrumbs, bounded descendant reads, scoped map responses, boundary exits, preferred-scope selection, flat-world maps, and HTTP hierarchy administration. The frontend type-check and build passed; the committed backend suite passed during implementation. Temporary/live readback confirmed Aerthalon remained authoritative and playable after start; flat Aerthalon stayed in compatibility mode because it has one root location and no hierarchy metadata.

**Commit:** documentation scope only — implementation should follow the vertical-slice process below.

## Recently completed

| Idea | Completed | Commit |
| --- | --- | --- |
| Scenario authoring and world management (scenario CRUD + elements, world instancing, world update/elements/remove) | 2026-08-08 | on main via `scenario-authoring` · `world-instancing` · `world-management` |
| World management interface (play ⇄ manage view, scenario/world CRUD UI, instancing, `#manage` deep link) | 2026-08-10 | on main via `world-management-interface` |
| Player provisioning (create a player + starting location so instanced worlds are playable; play view empty state) | 2026-08-10 | on main via `player-provisioning` |
| Reusable player characters and world-specific instances (character CRUD, selection, copied world instances) | 2026-08-16 | on main via `reusable-player-characters` |
| Narrator-driven world start (structured opening, atomic character/location instancing, polling/error hardening) | 2026-08-16 | `9b00c16` |
| Nested locations and scoped world maps (migration 0011, hierarchy validation, scoped reads, context breadcrumbs, map navigation) | 2026-08-17 | `8c581c9` |

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
