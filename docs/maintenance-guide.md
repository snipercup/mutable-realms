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
10. **Hierarchy integrity is authoritative.** A location has at most one same-world parent; self-parenting and cycles are invalid; parent deletion is restricted by default. Reparenting changes containment only and must not silently rewrite physical links. Whole-world validation must detect corruption even if it was introduced outside the normal operation.
11. **Scoped maps are bounded derived views.** A scoped map contains its scope node and direct children, explicitly promoted landmarks, exact and projected player positions, visible links, and separate boundary exits. It must use stable ordering and explicit overflow metadata rather than loading an unbounded hierarchy into the browser or narrator context. Flat worlds remain valid roots and retain the legacy map fallback.
12. **Landmark promotion is presentation-only.** A promotion references one same-world map scope and one existing location; it does not create a second parent, duplicate a location, or add movement adjacency. Removing a promotion leaves containment and `location_links` unchanged.
13. **Routes are explicit transit edges.** A route has same-world directed endpoints and an active state. Route travel requires the entity's exact current location to equal the route origin and records an authoritative landing location; it never infers or rewrites `location_links`, containment, or map visibility.
14. **Narration-only goals.** Quests are not tracked as world state; only their effects persist through named operations. Accepted trade-off: nothing prevents narrating a quest twice — if double rewards ever hurt play, add a minimal completed-goal ledger (quest identifier + completion event, no lifecycle/board).

## System inventory

The full command, API, MCP tool, and environment-variable reference lives in [interfaces-and-tools.md](interfaces-and-tools.md). At a glance: thirteen additive migrations (`0001` initial through `0013` world_routes); five agent-facing atomic operations plus explicit route travel (`world_move_entity`, `world_travel_route`, `world_treat_and_discharge_patient`, `world_record_social_interaction`, `world_transfer_resource`, `world_update_location`); revision-aware administrative services for scenarios, world instancing, location hierarchy, cross-scale landmark promotion, and route definitions (scenario/world management through HTTP and CLI; hierarchy, promotion, and route administration through HTTP); and the `POST /api/worlds/{world_id}/turns` relay (deterministic with `decision_json`, narrated without it).

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

Logs should identify startup, migrations, world mutations, validation failures, API errors, and agent operation failures. Avoid logging huge prompts or full world state by default. Distinguish three conditions as the system grows: application operational (liveness), world valid (validation), agent reachable (narration relay).

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

The current live state (2026-08-08): ward-world and town-world both at revision 2; the narration profile is bound to town-world / sailor; the page accepts player actions for that world.
