# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Make instanced worlds playable — player provisioning — complete (2026-08-10)

**Goal:** a world instanced from a scenario is not playable — it has no player and no locations, so selecting it in the play view shows `player not found` and keeps the previous world's view. Give the player a way to provision a starting state: create a player character with any name (e.g. `fate` — the same name works in any world; each world gets its own entity) and a starting location in a world that lacks them, then play there.

**Scope:**
- backend: atomic, revision-checked, idempotent `world_provision_player` — creates a starting location (`{world_id}-start`) + player character (`{world_id}-player`, role `player`) + placement + `player_provisioned` event; conflict if the world already has a player;
- reads: `GET /api/worlds/{world_id}` gains the world's player summary (id, name, location);
- CLI `provision-player` + HTTP `POST /api/worlds/{world_id}/player`;
- manage page: world editor shows the existing player or a create form (player name + starting location name);
- play view: a world without a player shows a clear empty state (with a hint to use Manage) instead of the error banner + stale view; the action form is unusable until a player exists;
- administration only — not exposed through the turn policy or narration agent.

**Out of scope:** multiple players per world; moving/renaming players later; provisioning beyond one starting location; scenario-level player templates.

**Verification:** op round-trips (provision → `world_context` shows the player at the starting location; the play view renders; a narrated turn works), double-provision and stale-revision conflicts, idempotent replay, CLI + HTTP, and a browser flow on a temporary world (provision from Manage → play).

**Suggested sequencing:**
1. ✅ Backend — **complete (2026-08-10)**: `world_provision_player` in `backend/world/worlds.py` — atomic, revision-checked, exact-request idempotent; creates starting location (`{world_id}-start`) + player character (`{world_id}-player`, role `player`) + placement + `player_provisioned` event; conflict if the world already has a player; `GET /api/worlds/{world_id}` now returns the player summary; CLI `provision-player` + HTTP `POST /api/worlds/{world_id}/player` (404/409 mapping). `tests/backend/test_world_instancing.py` grew to 30 tests (5 new: provisioning round-trip incl. context build, conflicts, replay, name reuse across worlds, CLI + API). Suite 210 passed, lint clean.
2. ✅ Manage-page player section + play-view empty state — **complete (2026-08-10)**: world editor shows "Player: name at location" once provisioned or a create form (player name + starting location) when not; the play view renders a clear empty state ("This world is not ready to play yet — provision a player…") instead of the `player not found` banner + stale previous world when the selected world has no player, and the action seam is inert until a player loads. Browser-verified reproducing the user's report on a temporary DB: playerless `world-of-earthalon` selected → empty state (no red bar, no stale map) → provisioned "fate" at "Settlement" from the Manage view (rev 1→2) → Play showed the map, Settlement, and "Entities here (1): fate" with zero JS errors.

**Commit:** suggested branch `player-provisioning` — `Add player provisioning for instanced worlds`.

## Recently completed

| Idea | Completed | Commit |
| --- | --- | --- |
| Scenario authoring and world management (scenario CRUD + elements, world instancing, world update/elements/remove) | 2026-08-08 | on main via `scenario-authoring` · `world-instancing` · `world-management` |
| World management interface (play ⇄ manage view, scenario/world CRUD UI, instancing, `#manage` deep link) | 2026-08-10 | on main via `world-management-interface` |

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
