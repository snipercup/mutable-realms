# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### World management interface — in progress (Steps 1–2 complete)

**Goal:** give the player a management view alongside the existing play view. On one page the player plays in an instanced world (map + narration); at any point they can switch to a management page that supports CRUD for worlds and scenarios: create/read/update/remove scenarios (title, description, and the three story elements), list worlds, instance a new world from a scenario, and update/remove worlds (title, description, elements). Editing a scenario never changes instanced worlds — the copy semantics are enforced by the backend and the UI must preserve them (scenario editors write scenario data only).

**Existing CRUD surface (already implemented, limited history):** scenario CRUD + elements and world instancing/update/elements/remove are complete via CLI and HTTP (`/api/scenarios`, `/api/worlds`) — see [interfaces-and-tools.md](interfaces-and-tools.md). This task is presentation-only: no backend changes expected.

**Scope:**
- navigation: a Play ⇄ Manage toggle in the existing topbar; play state (selected world, narration log) survives switching; management mutations refresh the play view on return (re-poll);
- scenario management: list + detail (elements), create form, edit title/description, elements editor (three long-form fields), delete with confirmation — wired to the existing scenario endpoints with client-generated operation IDs (`crypto.randomUUID()`);
- world management: list (revision, source scenario), instance-from-scenario form (pick scenario + world id), edit title/description, elements editor, delete with confirmation — wired to the existing world endpoints with `expected_revision` taken from the fresh list and a new operation ID per action;
- after every mutation the affected list re-fetches so revisions stay truthful; errors surface in the existing status banner;
- stays plain TypeScript + DOM (no framework), consistent with the current frontend.

**Out of scope:** authentication/authorization for management actions; bulk operations; scenario versioning/diffs; undo; anything beyond the already-implemented CRUD surface.

**Verification:** `frontend-check` + `frontend-build` + full backend suite (unchanged); browser DOM assertions for the flows (lists render from the APIs, create/edit/delete complete, an instanced world appears in the world list, scenario edits leave instanced worlds' content unchanged); a narrated turn still works after switching views.

**Suggested sequencing:**
1. ✅ Navigation shell + read-only management view — **complete (2026-08-08)**: Play ⇄ Manage toggle in the topbar (plain TypeScript + DOM, no framework); management view renders scenario and world lists from `GET /api/scenarios` and `GET /api/worlds` (world cards show revision + source scenario); play state (selected world, narration log) survives switching; empty states and error banner reused. `frontend-check` + `frontend-build` clean, backend suite unchanged (203 passed). Browser-verified on a temporary DB: Manage shows Aerthalon scenario + three worlds (Aerthalon rev 1 from scenario aerthalon, Harbor Town, Recovery Ward), Play restores with selection intact, no JS errors.
2. ✅ Scenario management UI — **complete (2026-08-10)**: create form (id/title/description), scenario editor panel (edit title/description via PATCH, per-element save buttons for the three story elements via PUT, delete with confirmation via DELETE), client-generated operation IDs (`crypto.randomUUID()`), lists re-fetch after every mutation and the editor reloads server truth. `frontend-check` + `frontend-build` clean, backend suite unchanged (203 passed). Browser-verified on a temporary DB: created "aerthalon" through the form (editor auto-opened), renamed it via Save, saved an opening scene element, deleted it with confirmation — all persisted (revision/event linkage verified in SQLite) with zero JS errors. Pitfall caught and fixed during verification: `requestJson(method, path, body)` calls had the argument order swapped, which threw before any fetch; corrected at all three call sites.
3. World management UI: instance-from-scenario, edit, elements, delete (revision-aware).
4. Integration polish: state survives switches, re-poll on return, `#manage` deep link, empty/error states; end-to-end browser verification.

**Commit:** pending.

## Recently completed

| Idea | Completed | Commit |
| --- | --- | --- |
| Scenario authoring and world management (scenario CRUD + elements, world instancing, world update/elements/remove) | 2026-08-08 | on main via `scenario-authoring` · `world-instancing` · `world-management` |

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
