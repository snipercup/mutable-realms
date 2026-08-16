# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Reusable player characters and world-specific instances — scoped

**Goal:** separate a reusable player-character definition from its world-specific playable instance. A player should define a character once, select that character when entering multiple worlds, and receive an independent instance whose location and gameplay state belong to the selected world.

**Scope:**
1. **Player-character definitions** — add an administrative CRUD model for reusable character definitions. The first slice contains a stable character ID, name, and basic descriptive information. Definitions are templates: they are not placed in a world, do not have a starting location, and do not change during gameplay.
2. **World-specific character instances** — add an explicit instance operation that copies a character definition into a selected world. The instance gets its own authoritative entity/character identity and world-specific state; its starting location is chosen by the world-instancing/provisioning flow, never stored on the reusable definition. A definition may be instanced into multiple worlds, with independent instances and later gameplay state.
3. **Selection flow** — expose character definitions in the management interface and require a character selection when beginning or provisioning play in a world. Keep the existing direct administrative provisioning path for advanced use while the instance path is introduced.
4. **Compatibility and invariants** — existing world-bound player entities remain valid; character definitions are separate from scenarios and worlds; deleting or editing a definition must not rewrite existing instances; instance creation is atomic, validated, idempotent, and traceable with the appropriate operation/revision rules.

**Out of scope for this slice:** narrator-driven location generation, nested locations, thematic maps, procedural kingdom-wide generation, character progression or inventory templates, and cross-world travel. The previously scoped world-scale geography steps are postponed until reusable character definitions and instances are established.

**Verification:** CRUD tests for definitions; create one definition and instance it into two worlds; confirm each world receives a distinct player/entity instance with independent locations and revisions; edit the definition and confirm existing instances are unchanged; reject duplicate or stale instance requests deterministically; browser-verify definition creation, character selection, and world-specific instance display.

**Suggested sequencing:** definition schema and CRUD → world-specific instancing operation → API/CLI and management UI → selection/provisioning integration → compatibility and browser verification.

**Commit:** pending.

## Recently completed

| Idea | Completed | Commit |
| --- | --- | --- |
| Scenario authoring and world management (scenario CRUD + elements, world instancing, world update/elements/remove) | 2026-08-08 | on main via `scenario-authoring` · `world-instancing` · `world-management` |
| World management interface (play ⇄ manage view, scenario/world CRUD UI, instancing, `#manage` deep link) | 2026-08-10 | on main via `world-management-interface` |
| Player provisioning (create a player + starting location so instanced worlds are playable; play view empty state) | 2026-08-10 | on main via `player-provisioning` |

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
