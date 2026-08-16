# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### World-scale worlds: world-aware narration, nested locations, thematic maps — in progress (Step 1 complete)

**Goal:** make worlds bigger than one town actually playable and narratable. Three linked problems surfaced by the user's Virellea experiment: (1) the narration agent is hard-bound to one world (town-world/sailor) through its profile's MCP env, so it reads and narrates the *wrong world* whenever the page selects another — Fate-at-Elaris turns described Harbor Town, and the world's opening scene never reached the agent; (2) locations are a flat list + links, so a kingdom (regions → cities → districts → streets → buildings) cannot be represented; (3) the map is plain nodes+edges, not an artistic scoped view.

**Scope (sequenced steps):**
1. ✅ World-aware narration — **complete (2026-08-10)**: the turn relay builds the selected world's authoritative context (`build_world_context`; guarded for playerless worlds) and embeds a compact snapshot — world, player, current location + entities, story elements (author's note / plot essentials / opening scene), recent events — into the narration prompt, with explicit guidance to pass `world_id=…` and the player entity id to tools and to ignore the profile's default binding. MCP tools became world-parameterized: reads accept `world_id` with the profile env as default; mutations keep `world_id` required (naming the world on a mutation is deliberate); the actor/player defaults to the binding but an explicit actor wins; the old "trusted session rejects other worlds" guards were removed — underlying ops still validate world existence, player-of-world, and expected revision. `world_validate` stays admin-only. Updated the narration contract, maintenance guide, and interfaces docs. Tests: narrator prompt now embeds context (new test with opening scene), relay tests assert the fake narrator receives the selected world's context, MCP tests rewritten for default+override semantics plus a new stdio test proving an explicit world other than the binding is read (213 passed, lint clean). Live-verified on a temporary DB: the actual prompt for the user's exact scenario ("Enter the guild hall in front of me" in a provisioned world-of-earthalon) embeds the opening scene, names player fate, and instructs `world_id=world-of-earthalon`.
2. **Narrator-driven world start** — a playerless world's Play view becomes "Begin your story": the player enters their character name, and a provisioning turn relays the selected world's context + player name to the narrator with a structured contract — read the world, choose the starting location (name + short description) from the opening scene, call the provisioning tool, then narrate the opening there. Requires extending `world_provision_player` with an optional location description and exposing it as one agent tool. Deliberate design change: starting *your own* character is player-scoped, not admin — the Manage-page form stays for advanced use; the op remains atomic, idempotent, no-double-provision.
3. **Nested locations** — `locations.parent_id` (nullable self-FK) + `kind` (region/city/district/street/building, default building); a location-administration op (create location with optional parent, kind, and links); containment navigation (enter child, leave to parent, traverse links); breadcrumbs in `world_context`; map data scoped to the player's current container (children + links + adjacent containers) so a rendered map stays small; backward compatible — existing worlds are one root scope with no parents. After this lands, the narrator-driven start can grow a small hierarchy (city → district → hall).
4. **Thematic per-scope maps** — derived, deterministic SVG per scope: containers as soft region shapes, buildings as house glyphs, streets as paths; stable seeded auto-layout; the map remains a view, never authoritative.

**Out of scope:** *procedural* kingdom-wide generation (many locations authored by code rather than by the narrator — a separate future idea); hand-authored map coordinates; cross-world travel; a live world-switching UI for the narration profile.

**Verification:** Step 1 — a relayed turn on a temporary world returns narration grounded in *that* world's context (opening scene referenced), mutations land in the selected world, and the profile-default binding still works. Step 2 — a playerless temporary world's begin-flow produces a player + starting location whose name/description reflect the opening scene, narration opens there, and the world is playable afterward. Step 3 — create nested locations via the op, move the player into a building, context shows breadcrumbs, the map returns the scoped subgraph, validation clean, migration compatible. Step 4 — the SVG renders per scope deterministically and reflects the nested state.

**Suggested sequencing:** 1 (world-aware narration — ✅ complete) → 2 (narrator-driven world start) → 3 (nested locations) → 4 (thematic maps).

**Commit:** Step 1 suggested branch `world-aware-narration` — `Narrate the selected world with embedded context`.

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
