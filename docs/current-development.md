# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Scenario authoring and world management — in progress (Steps 1–2 complete)

**Goal:** define reusable **scenarios** — a title, description, and story elements (author's note, plot essentials, opening scene) — from which many worlds can be made. Creating a world from a scenario *instances* that content: the new world owns its own copy (title, description, elements), the scenario stays unchanged, and later edits to either side do not affect the other. Worlds remain individually manageable (rename, re-describe, set elements, remove).

**Learned from the user's example (not part of the tracker content):** these elements are *authorial story setup* — long-form prose defining tone, premise, and the opening situation. Player-facing prompt templates (pick-a-species style choices) are explicitly out of scope; the elements are static story properties the agent reads, not player questionnaires.

**Scope — scenario layer (authoring templates, admin-only):**
- migration `0007_scenarios`: `scenarios` (id, title, description) + `scenario_elements` (scenario, element type ∈ `author_note` | `plot_essentials` | `opening_scene`, content 1–20000 chars) + `scenario_operations` (operation-id idempotency + traceability; no world-revision machinery — scenarios are templates, not playable state);
- ops: `create_scenario`, `update_scenario` (title/description), `set_scenario_element`, `remove_scenario` — atomic and idempotent; CLI (`create-scenario`, `update-scenario`, `set-scenario-element`, `remove-scenario`) + HTTP;
- note: these are authoring *data*, distinct from the `backend/scenarios/` seed modules (code fixtures that create the deterministic ward/town worlds).

**Scope — world layer (instances + management):**
- migration `0008_world_metadata`: `worlds.description` (nullable) + `worlds.source_scenario_id` (nullable FK → scenarios, `ON DELETE SET NULL`);
- migration `0009_world_elements`: world-owned elements ledger (same three types, linked update event);
- `create_world_from_scenario` — copies title/description/elements into a fresh world (revision 0 → 1, `world_created` event, `source_scenario_id` set); the scenario is untouched;
- world management ops: `create_world` (bare, no scenario), `update_world` (title/description), `set_world_element`, `remove_world` (cascading delete of all world state);
- CLI + HTTP for all; deliberately NOT exposed through the turn policy or the narration agent (administration, not per-turn gameplay); `world_context` gains the world's description and elements so the agent can ground a new world's opening in the authored setup.

**Copy semantics are the contract:** instancing copies; edits diverge; deleting a scenario leaves its worlds intact (`source_scenario_id` becomes NULL); removing a world removes its history with it (accepted trade-off).

**Out of scope (for now):** scenario versioning/diffs; live-linking or propagation between scenario and worlds; scenario/world management UI in the page; player/location provisioning for new worlds (a created world is not yet playable until entity/location creation exists — a roadmap item); soft-delete; a global audit trail of removals.

**Verification:** full suite + lint; migration compatibility (existing worlds gain `description = NULL`, `source_scenario_id = NULL`); scenario round-trips (create/update/elements/remove) with idempotent replay; instantiate → world has copied title/description/elements, revision 1, `world_created` event; scenario unchanged after instantiation AND after world edits; world edits never touch the scenario; deleting a scenario keeps its worlds; cascade removal checks; a created world with elements appears in `world-context`; live checks via CLI + HTTP against temporary scenario/world only (never the live ward/town worlds).

**Suggested sequencing:**
1. ✅ Scenario authoring — **complete (2026-08-08)**: migration `0007_scenarios` (scenarios + scenario_elements + scenario_operations), `backend/world/scenarios.py` (create/update/set-element/remove + reads), CLI (`create-scenario`, `update-scenario`, `set-scenario-element`, `remove-scenario` + npm scripts), HTTP (`GET/POST /api/scenarios`, `PATCH`, `PUT …/elements/{type}`, `DELETE`), and `tests/backend/test_scenarios.py` (20 tests: persistence, exact-request idempotent replay, duplicate-id and operation-reuse conflicts, element upsert/validation, cascade removal, CLI roundtrip, API roundtrip with 404/409; suite 180 passed, lint clean). Live-verified via CLI and HTTP on a temporary database only.
2. ✅ Instantiation — **complete (2026-08-08)**: migrations `0008_world_metadata` (`worlds.description` + `worlds.source_scenario_id` ON DELETE SET NULL) and `0009_world_elements` (world-owned element ledger linked to events); `backend/world/worlds.py::create_world_from_scenario` (copies title/description/elements, revision 0 → 1, `world_created` event, operation-ID idempotency); CLI `create-world-from-scenario` + `POST /api/worlds`; `world_context` and world reads now expose description, source scenario, and `world_elements`; validation gained the `world_element_updated_event_mismatch` coherence check. `tests/backend/test_world_instancing.py` (13 tests: copy semantics, scenario unchanged, divergence on scenario edit, replay, conflicts, scenario deletion keeps worlds with NULL source, context readback, validation corruption, CLI + API roundtrips; suite 193 passed, lint clean). Live-verified via CLI and HTTP on a temporary database only — the scenario stayed byte-identical after instancing.
3. World management remainder: `update_world`, `set_world_element`, `remove_world` + cascade tests.

**Commit:** pending.

## Recently completed

| Idea | Completed | Commit |
| --- | --- | --- |

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
