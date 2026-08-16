# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Narrator-driven world start — complete (2026-08-16)

**Goal:** let a player begin an unprovisioned world by selecting a reusable player-character definition and starting through the narrator. The narrator should use the selected world's authoritative opening scene and context to establish the first scene, while the system creates the world-specific character instance at a world-appropriate starting location.

**Scope:**
1. **Begin-story flow** — add a play/start path for worlds with no player instance. The player selects an existing reusable character definition; the flow must not ask for or store a starting location on the definition.
2. **Narrator start contract** — provide the selected world, opening scene, and character definition snapshot to the narrator. The narrator chooses or proposes the initial location from the world's context and returns structured start information alongside player-facing opening narration.
3. **Validated instancing** — create the copied world-specific character, starting location, placement, and initial event atomically through a named, revision-aware, idempotent operation. The starting location belongs exclusively to the world instance.
4. **Playable transition** — after successful start, refresh server truth and enter the normal turn loop without exposing tool calls, reasoning, or administrative details in the player-facing response.
5. **Failure and compatibility behavior** — preserve the existing Manage-page character-selection/starting-location flow, reject invalid or incomplete narrator start results without partial state, and keep already-provisioned worlds unchanged.

**Out of scope for this slice:** nested locations, thematic maps, procedural kingdom-wide generation, character progression or inventory templates, and cross-world travel. The narrator may select or author the starting location for this world start, but broad procedural geography generation remains deferred.

**Verification:** complete. Added the structured narrator start contract and `POST /api/worlds/{world_id}/start`. Tests cover selected-world/character context, valid and invalid JSON start results, playerless-world failure without mutation, atomic character/location creation, exact replay without a second narrator call, and operation reuse conflicts. Full checks: 224 tests passed, `npm run lint`, and frontend build. Temporary HTTP verification with an injected narrator created `world-start-player` at `Elaris`, copied the character definition, advanced revision 1→2, and replayed the identical response; a deliberately slow narrator left the mid-start player read at 404 and then committed the instance once. World readback confirmed the instance and location. The temporary server was stopped and port 8795 verified closed. Manual acceptance verification after a container restart (2026-08-16): the original playerless-world flow was repeated in the browser—select world, select reusable character, click **Begin your story**—and the narrator established the world-specific opening successfully; the start panel did not oscillate and normal play became available.

**Suggested sequencing:** complete — playerless-world start state → narrator start contract → validated world-specific character instancing → Play UI transition → temporary-database and HTTP verification.

**Follow-up hardening:** complete. Start requests are serialized against the five-second frontend poll; start progress disables competing world refresh controls; start failures remain visible across later polls until world selection or retry; the injected start narrator is stored on application state; start failures expose only safe categories (`invalid_start_response`, `narrator_timeout`, or unavailable); structured start JSON rejects unexpected fields and bounds location/name/description/narration lengths. Focused and full regression coverage added.

**Commit:** suggested branch `narrator-world-start` — `Start playerless worlds through the narrator`.

## Recently completed

| Idea | Completed | Commit |
| --- | --- | --- |
| Scenario authoring and world management (scenario CRUD + elements, world instancing, world update/elements/remove) | 2026-08-08 | on main via `scenario-authoring` · `world-instancing` · `world-management` |
| World management interface (play ⇄ manage view, scenario/world CRUD UI, instancing, `#manage` deep link) | 2026-08-10 | on main via `world-management-interface` |
| Player provisioning (create a player + starting location so instanced worlds are playable; play view empty state) | 2026-08-10 | on main via `player-provisioning` |
| Reusable player characters and world-specific instances (character CRUD, selection, copied world instances) | 2026-08-16 | on main via `reusable-player-characters` |

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
