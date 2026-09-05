# Mutable Realms — Maintenance and Development Guide

The original `implementation-plan.md` served its purpose: Phases 1–15 and Milestones A–H are complete, the backup slice is implemented, and the first successful prototype is demonstrated. This guide replaces that plan. It holds the durable guidance for operating and extending Mutable Realms beyond the initial prototype. Historical phase-by-phase records live in the Git history; do not recreate them here.

## Core concept

> The player changes something through narrative interaction, the world actually changes, and the system continues reasoning from that changed reality later.

That is the entire point of the project. Graphical quality, location count, and generated text volume are secondary. Every design decision in this guide protects persistent causality.

## The authoritative loop

```text
Free-form player action
        ↓
Hermes narration agent
        ↓
Relevant persisted context
        ↓
Controlled world mutations
        ↓
SQLite authoritative state
        ↓
Updated browser visualization
        ↓
Future narration grounded in the changed world
```

- **SQLite** is the single authoritative store; narration, prose, SVG, and web pages are derived views and must never contradict it.
- **FastAPI** serves read APIs, the turn relay, health routes, and the built frontend from one process (one worker).
- **Hermes** runs the narration agent as a dedicated profile configured through MCP env vars (`MUTABLE_REALMS_DB_PATH`, `MUTABLE_REALMS_WORLD_ID`, `MUTABLE_REALMS_PLAYER_ID`). The env values are **defaults**: the page's turn relay embeds the *selected* world's authoritative context into the prompt and the agent passes that world explicitly to the tools, so it narrates and mutates the world the player chose, not whatever the profile defaults to.
- **The browser** discovers worlds, renders location/entities/events/map from API data, and now accepts player actions directly (`POST /api/worlds/{world_id}/turns`), relaying them to the narration agent.

## Non-negotiable design rules

1. **Authoritative state is SQLite.** Mutations happen only through named, validated, atomic application operations — never generic `world_update`, never direct SQL from agents, never narration-only claims of persistence.
2. **One mutation per turn.** Each narrated turn performs at most one supported operation; multi-step consequences are compound operations (e.g. treat-and-discharge), not model-assembled low-level writes.
3. **Deterministic bookkeeping.** Idempotency (caller operation ID, exact-request replay), expected-revision checks with one fresh retry, event linkage, and invariant-safe transactions are enforced in code, never by prompting.
4. **Agents reason; software bookkeeps.** Model reasoning is reserved for interpretation, creativity, and judgment. Queries, validation, and repetitive transformation are deterministic code.
5. **Retrieve working sets, not whole worlds.** Context includes only what the current scene needs (player + current-location entities, relationships, resources, properties, bounded events) on one read-only snapshot.
6. **Capability growth, not premature generality.** Add a capability only when play demands it, as one vertical slice (see below). Scenario concepts (wards, quests, inventories) must never become mandatory core abstractions.
7. **Scenario-neutrality.** No empty scenario fields leak into generic reads; capability views are separate derived projections.
8. **Preserve causality and compatibility.** Meaningful changes persist until deliberately reversed; schema changes are additive migrations; derived presentation (map, sprites, prose) never becomes authoritative.
9. **Containment is not travel.** Location parentage describes scope and ownership of place, while `location_links` remains the sole ordinary movement adjacency. Shared parents, map visibility, breadcrumbs, and zooming never permit movement.
10. **Hierarchy integrity is authoritative.** A location has at most one same-world parent; self-parenting and cycles are invalid; parent deletion is restricted by default. Reparenting changes containment only and must not silently rewrite physical links. Whole-world validation must detect corruption even if it was introduced outside the normal operation. Destructive world removal explicitly clears that world's containment rows before cascading the world, so nested locations cannot turn a valid world delete into a foreign-key failure.
11. **Scoped maps are bounded derived views.** The API may return scope metadata plus direct children, bounded sibling neighbors, explicitly promoted landmarks, exact and projected player positions, visible links, and separate boundary exits. Sibling neighbors share the current location's parent; parentless roots use the virtual world scope. The scoped frontend uses the scope name as the title and the SVG as the child/neighbor location index: it does not draw the scope location as a node, highlight the player, repeat children in a second list, or draw internal `location_links` as edges. Neighbor visibility never proves movement. Boundary exits remain visible. It must use stable ordering and explicit overflow metadata rather than loading an unbounded hierarchy into the browser or narrator context. Flat worlds remain valid roots and retain the legacy map fallback.
12. **Landmark promotion is presentation-only.** A promotion references one same-world map scope and one existing location; it does not create a second parent, duplicate a location, or add movement adjacency. Removing a promotion leaves containment and `location_links` unchanged.
13. **Routes are explicit transit edges.** A route has same-world directed endpoints and an active state. Route travel requires the entity's exact current location to equal the route origin and records an authoritative landing location; it never infers or rewrites `location_links`, containment, or map visibility.
14. **Route-chain maps are derived and bounded.** A scoped map traverses active directed `world_routes` breadth-first from its scope, suppresses cycles/duplicate route IDs, returns at most 100 route entries, and orders entries by destination `short`, `mid`, then `long` range metadata. This is informational; it never grants access or adds movement controls.
15. **Lazy expansion is bounded and explicit.** Each accepted expansion creates one ordinary location tied to an existing anchor, records a stable proposal ID, rejects duplicate names/IDs, and counts against the world's expansion budget. It never creates entities, routes, or unbounded geography implicitly; optional containment and physical adjacency are separate explicit fields.
16. **Structured world starts provide a bounded local working set.** A structured narrator start contains 3–16 locations: one parentless selected start, at least one direct child, and at least one other parentless sibling. Street-level urban openings should contain at least 10 direct children beneath the start; other opening scales may use fewer locations within the same 16-location bound. Siblings may carry explicit boundary/route orientation metadata (`geography_role`, `direction`, `range_band`) and bounded semantic presentation metadata (`map_form`) for roads, buildings, districts, cities, mines, forests, water, or landmarks. In scoped maps, direction and range are relative to the selected scope and drive deterministic presentation ordering/placement; missing values use stable name/ID fallback. These fields are presentation metadata, not inferred movement permissions. Legacy top-level `location_name`/`location_description` starts remain compatible as a one-location fallback.
17. **World starts are bounded layouts.** A structured narrator-driven start creates 3–16 locations selected from the opening context, with one explicit parentless player start, at least one direct child, at least one parentless sibling, optional single-parent containment, and only explicitly requested local links. Legacy one-location starts remain compatible. The selected player start is marked as the default local map scope, but it is never made its own parent. It must not infer movement from containment, generate an unbounded map, overwrite existing locations, or regenerate an already-started world. The entire layout, map-scope metadata, and player placement commit atomically at one world revision and replay exactly by operation ID.
18. **Narration-only goals.** Quests are not tracked as world state; only their effects persist through named operations. Accepted trade-off: nothing prevents narrating a quest twice — if double rewards ever hurt play, add a minimal completed-goal ledger (quest identifier + completion event, no lifecycle/board).
19. **Location memories are narrative facts; quantified facts are properties.** `location_memories` holds condensed story-beats ("Fate fixed a cart at the farmstead") deduplicated by a normalized `memory_key` with an `occurrence_count`; `location_properties` holds exact, bounded, mechanical values (ward patient counts, visits). The narrator chooses per fact: counts and invariants → properties, story-beats → memories. Only the current location's memories enter context, under a 1000-token render budget; identical memories combine into counted form and the narrator summarizes on overflow.
20. **Narration history is presentation state, not world state.** `narration_history` is an append-only world-scoped transcript (start narration + every narrated turn's player action and agent narration). It never bumps revisions, writes events, or enters the operation ledger, and cascades away with the world. Every turn is a fresh Hermes chat session; continuity comes from embedding up to 100 recent entries (32,000-token bound) as a labeled, explicitly non-authoritative history block.
21. **The region framework is knowledge, not state.** Scenario-authored regions (`scenario_regions`, free-form levels such as kingdom/province/city, planet, or school grounds) are copied into each world (`world_regions`) at instancing and backfilled for worlds created before migration `0020`. Regions are knowledge; they become locations only when the narrator materializes them via `world_expand_location` with `region_id`, which binds `world_regions.location_id`. Context resolves the player's region chain (containment walk up to a bound region, then all region ancestors). Routes are validated against the framework: `world_create_route` accepts only routes whose endpoints resolve to regions that share an ancestor or are declared adjacent via `connected_by_road_to` (skipped when a world has no regions).
22. **The narration cap is prompt + SOUL + deterministic truncation, never model config.** The 150-token turn-narration bound lives in the prompt instruction (primary), the SOUL rule, and `bound_narration_tokens()` (sentence-safe backend truncation). Never use Hermes `model.max_tokens`/`max_output_tokens` for it: Hermes applies that cap to the entire completion including tool-call JSON and reasoning, which breaks tool use.
23. **Start-response boundary normalization is narrow and deterministic.** Common compass abbreviations from models (`N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`, case-insensitive) are canonicalized to full direction names before persistence; unknown directions remain invalid. Missing optional `parent_region_id` defaults to `null`, but a declared child region should include its parent explicitly so the framework hierarchy is preserved.
24. **Player-facing movement history uses names, not storage IDs.** Movement mutations capture entity and source/destination location names in the event payload and write a friendly summary. The recent-events read model also reconstructs that summary from the payload IDs for legacy `entity_moved` events, preserving compatibility without rewriting historical rows; if referenced records are unavailable, it falls back to the stored summary.

## System inventory

The full command, API, MCP tool, and environment-variable reference lives in [interfaces-and-tools.md](interfaces-and-tools.md). At a glance: 21 additive migrations (`0001` initial through `0021` backfill_world_regions); the agent-facing atomic operations (`world_move_entity`, `world_travel_route`, `world_create_route`, `world_expand_location`, `world_treat_and_discharge_patient`, `world_record_social_interaction`, `world_record_location_memory`, `world_consolidate_location_memories`, `world_transfer_resource`, `world_update_location`); revision-aware administrative services for scenarios (including region framework authoring), world instancing, location hierarchy, cross-scale landmark promotion, route definitions, and bounded location expansion; and the `POST /api/worlds/{world_id}/turns` relay (deterministic with `decision_json`, narrated without it).

## Adding a capability — the vertical slice

Every new capability follows the same pattern. Implement one slice end to end; record the scope in this guide first, then flip it to complete with verification evidence.

1. **Migration `000N`** — additive, strict tables, FKs, `updated_event_id` linkage to `events`, CHECK constraints, indexes. Never edit history.
2. **Atomic operation service** — one `BEGIN IMMEDIATE` transaction: expected-revision check → exact-request idempotency via caller operation ID → revision bump + operation record + event + state change. Error types map to turn outcomes (`MISSING_RESOURCE`, `MUTATION_REJECTED`).
3. **Context working set** — add the read projection on the same read-only snapshot; keep it bounded.
4. **Validation** — coherence checks mirroring the existing ones (owner world/character match, event linkage).
5. **Agent surface** — `agent_tools.py` wrapper + `world_status` advertisement rule (capability advertised only for worlds that support it) + MCP tool with schema bounds.
6. **Turn policy** — `turns.py`: `OperationType`, per-operation argument validator, dispatch branch, error mapping.
7. **Docs** — this guide (scope → complete), `readme.md`, `docs/narration-agent-contract.md`.
8. **Tests** — migration compatibility, atomic persistence, exact idempotency, invalid inputs, rejection paths, turn orchestration, validation corruption.

Expected churn when adding a migration or MCP tool — hardcoded assertions in existing tests break by design: `test_migrations.py` (applied-count tuples), `test_startup.py` (schema-version list), `test_mcp_server.py` (tool-name list), `test_agent_tools.py` (`available_mutations` per world), `test_context.py` (full-dict context shape). Update them; these are bookkeeping, not regressions.

Verification gate before claiming a capability works: full suite (`uv run pytest -q`), `npm run lint` (ruff + tsc), and the deterministic CLI seam (`npm run world-turn` with a validated decision JSON — it proves the end-to-end path that in-process tests cannot).

## Operations

The command reference is in [interfaces-and-tools.md](interfaces-and-tools.md). The operational rules that matter:

- **State boundary**: live DB at `MUTABLE_REALMS_DB_PATH` (outside Git, bind-mounted host state dir). Backup files belong beside it.
- **Migration workflow**: `backup → migrate → validate`. Restore is manual: stop the worker, replace `world.sqlite3` with a snapshot, run `npm run validate` before resuming mutations.
- **Boot**: `scripts/start-mutable-realms.sh` runs migrate → seed → optional frontend build → uvicorn; wired through Dockerfile + compose.
- **Health**: `/health/live` (process answers) vs `/health/ready` (DB reachable, supported schema). Full world validation is a separate diagnostic.
- **Container gotchas**: (1) the Hermes WebUI keeps ONE long-lived MCP subprocess per profile shared across chats — after changing MCP code, restart the container or the agent keeps the old tool list; (2) a boot-started server on 8790 keeps old backend code until a container restart — verify new routes on your own port first.

## Testing strategy

Persistent state is game logic. Unit tests cover domain rules; persistence tests cover reads, writes, transactions, constraints, and migrations; API tests cover queries and mutations through supported interfaces; integration tests cover sequences across application recreation (e.g. treat → discharge → close → reopen → verify persisted). Persistence tests use temporary database files, never the live world. Keep small regression fixtures. The deterministic layer must be testable without Hermes or any external model — never depend on nondeterministic LLM output in tests.

## Database migration standard

Schema changes are versioned from the first schema. Versioned SQL files + a schema-version table with SHA-256 checksums are sufficient; reject modified, missing, noncontiguous, or unsupported history. Every migration preserves existing world state when practical. Never depend on manually editing production world databases. Before risky work: `backup → migrate → validate`.

## Observability

Logs should identify startup, migrations, world mutations, validation failures, API errors, and agent operation failures. Avoid logging huge prompts or full world state by default. Distinguish three conditions as the system grows: application operational (liveness), world valid (validation), agent reachable (narration relay). World-start narration has its own bounded timeout; timeout warnings must include the world ID, configured timeout, and measured elapsed duration, while the API may return a stable player-facing error.

## Security boundaries

The narration agent operates through narrow MCP tools, not unrestricted shell. Treat generated content and player input as untrusted data — narrative text must never become executable code because it appears in world state. Keep secrets (API keys, OAuth tokens) out of Git, world data, prompts, event history, and frontend bundles. Bind services to localhost-facing ports unless wider access is deliberate.

## Avoid premature systems

Do not add: PostgreSQL, Redis, message queues, microservices, Kubernetes, ECS frameworks, complex plugin architectures, generic scripting languages, multiplayer synchronization, procedural generation frameworks, vector databases, embeddings, WebSockets, full-text search, large frontend frameworks. Any may eventually become justified; none should be introduced because a hypothetical future might need them. Prefer the smallest architecture that supports persistent causality correctly.

## Phase 16 — capability requests

When the narration agent meets play that existing infrastructure cannot persist (e.g. "I deploy probes to map nearby star systems"), it must not redesign the database. It should produce a structured capability request:

```text
CAPABILITY GAP

Current world cannot persist:
- exploration probes
- star-system surveys

Required behavior:
- probes remain deployed
- survey progress changes over time
- discoveries persist
```

The infrastructure side then implements the general capability as a vertical slice. Do not implement autonomous schema evolution; this loop is the controlled mechanism for the game's mechanics to evolve in response to play.

## Development history

| Work | Delivered | Verified |
| --- | --- | --- |
| Steps 1–3 | Plan tightening, tooling, dev image | 2026-08-01 |
| Phase 1 / Milestone A | Authoritative world slice: migrations, validation, atomic treat-and-discharge | 2026-08-01 |
| Phase 2 | Read API + generic browser visualization | 2026-08-01 |
| Scenario-neutrality | `0002_generalize_entities`, scenario modules | 2026-08-02 |
| Phases 3–7 | Controlled mutations, event history, context builder, MCP tools, narrated turn policy | 2026-08 |
| Phase 8 | Consistency validation audit (`missing_bed_state` gap fixed) | 2026-08 |
| Phase 9 / Milestone E | Full gameplay loop acceptance; persisted return across rebuild | 2026-08 |
| Phase 10 / Milestone F | Social state: relationships + memories (`0003`) | 2026-08-02 |
| Phase 11 / Milestone G | Resources (`0004`), quests narration-only, effects persist | 2026-08-05 |
| Phase 12 / Milestone H | Mutable locations (`0005`) | 2026-08-05 |
| Phase 13 | Location links + adjacency-constrained travel (`0006`) | 2026-08-05 |
| Phase 14 | Derived SVG map view | 2026-08 |
| Phase 15 | Direct player interface: turn relay + page input | 2026-08-08 |
| §22 slice | `backup` command with verified artifacts | 2026-08-08 |
| Scenario + worlds idea | Scenarios (templates) · world instancing · world management (create/update/elements/remove) · `0007`–`0009` | 2026-08-08 |
| Nested locations, promotions, routes, and controlled expansion | `0011`–`0014`; hierarchy/scoped maps, presentation promotions, explicit routes, bounded narrator expansion | 2026-08-17 |
| Contextual narrator world starts | Bounded structured start layouts, contextual player placement, containment/link creation, atomic replay-safe start | 2026-08-17 |
| Map orientation, forms, and route chains | Boundary orientation metadata (`0015`), map forms (`0016`), scoped-map children/sibling separation, route-chain visualization, edge-strip lane-packed sibling labels | 2026-08-17 → 2026-08-20 |
| Narrator turn output cap | 150-token bound: prompt instruction + SOUL rule + deterministic sentence-safe truncation (`03b0454`; later tuned 200 → 150) | 2026-08-20 |
| Narration history + context feed | `0017_narration_history`, start/turn recording, page reload, story-so-far prompt block (32k bound) (`d2216db`, `08e9114`) | 2026-08-20 |
| Expansion orientation + atomic actor move | `direction`/`range_band`/`map_form` metadata + `move_actor_to_location` on `world_expand_location` (`76a4e7c`) | 2026-08-20 |
| Location memories | `0018_location_memories`, dedup by `memory_key` with `occurrence_count`, record/consolidate operations, 1000-token render budget (`1a81da0`) | 2026-08-20 |
| World-region framework | `0019_scenario_regions` authoring + Manage editor, `0020_world_regions` instancing, `0021` backfill, context region chain, expansion `region_id` binding, framework-validated `world_create_route` (`9fef60a`, `4c1fac6`, `5ede07a`, `2fa919e`) | 2026-08-20 |

The current live state (2026-08-20): the `aerthalon` world (from the `world-of-aerthalon` scenario) is the primary play world, its region framework holds all seven kingdoms with a closed declared road network; the narration profile is bound to `town-world` / `sailor` as MCP defaults but the relay always passes the selected world explicitly.
