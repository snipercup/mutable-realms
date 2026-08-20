# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Bound the narrator's turn output to 200 tokens — in progress

**Goal:** keep the player-facing narration the relay returns for story turns short (~200 tokens), without limiting the narrator's tool-calling ability.

**Recommendation:** do not set `model.max_tokens`/`max_output_tokens` in the narration profile — Hermes applies that cap to the whole completion, including tool-call JSON and reasoning, so a 200-token cap would break tool use. Instead, steer length at three cooperating layers:

1. `build_narration_prompt` — explicit "at most 200 tokens, roughly 2 to 3 short paragraphs or about 150 words" instruction.
2. Narration profile `SOUL.md` — same standing rule in the profile's narration contract.
3. `bound_narration_tokens()` in `backend/app/narrator.py` — a deterministic safety net applied after `clean_narration` on the turn path, truncating at the last sentence boundary inside an ~200-token budget (coarse 4 chars/token estimate) so the cap holds even if the model ignores the prompt.

**Scope:**

- Apply to the turn narration path (`HermesNarrator.__call__`) and the prompt/SOUL for turns.
- Leave world-start narration, structured JSON contracts, and tool-calling behavior unchanged.
- Keep the cap deterministic and sentence-safe; never cut mid-word when a sentence boundary exists.

**Out of scope:** changing the model, context window, tool set, or any other narrator capability.

**Implementation status:** `backend/app/narrator.py` now instructs the turn prompt to stay within 200 tokens (2–3 short paragraphs, ~150 words) and applies a deterministic `bound_narration_tokens()` cap after `clean_narration` on the turn path, truncating at the last sentence boundary inside an ~800-character budget. The narration profile `SOUL.md` carries the same standing rule. No config-level token cap was added because Hermes applies `model.max_tokens` to the whole completion including tool calls.

**Verification:** pending implementation.

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
