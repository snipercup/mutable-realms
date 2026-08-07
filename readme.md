# Mutable Realms

Mutable Realms is an experimental AI-driven persistent world in which an AI agent narrates a story while also changing the world in which that story takes place.

The project explores an alternative to conventional AI storytelling. Instead of relying primarily on conversation history and memories to represent what has happened, Mutable Realms maintains an explicit world state that the AI can inspect and modify. The narrated story and visual representation of the world are grounded in that persistent state.

The goal is to create open-ended experiences where actions can leave lasting, visible consequences.

## The Idea

In a conventional AI storytelling game, a player might change a place and then return later to find that generated narration has silently restored its original assumptions. A repaired bridge may be broken again, transferred property may return to its former owner, or a flock may replenish itself without an event that explains why.

Mutable Realms instead represents relevant facts as persistent world state.

After any meaningful action:

* affected entities retain their new state and location;
* later actions begin from those persisted consequences;
* related goals, relationships, or resources can change when the scenario supports them;
* the visual representation reflects current authoritative state.

The AI does not have to reconstruct these consequences from narrative memory. It can inspect what is currently true about the world.

## A Mutable World

Persistence applies to more than individual objects.

A poor district could gradually improve until it is no longer considered a slum. An abandoned waterfront could become a trading port. A temporary medical ward could eventually become unnecessary or develop into a permanent clinic.

The world should be able to change its identity as a consequence of what happens within it.

Mutable Realms therefore treats the world as something that can be altered rather than as a static backdrop for generated stories.

## Player Interaction

The primary interaction can remain as flexible as a text adventure.

A player describes an action:

> I move the chicken coop into the pressure dome before the current gets stronger.

The AI interprets the action using the current scene, relevant world state, character information, and recent events. Whether the character is an adventurer, a merchant, or a chicken farmer on the ocean floor, it narrates what happens and applies resulting changes through controlled operations.

The world state then becomes the starting point for future interactions.

This keeps much of the freedom of open-ended AI storytelling without requiring every possible player action to be implemented as a traditional game mechanic.

## Persistent Causality

Mutable Realms distinguishes between three related concepts:

1. **World state** — what is currently true.
2. **Narration** — how events and actions are described.
3. **Visualization** — how the current world is presented to the player.

World state is authoritative.

Narration and visualization should reflect that state rather than independently defining it.

This is intended to reduce common problems in generative storytelling such as forgotten changes, duplicated characters, replenished problems, resurrected rewards or relationships, and locations that repeatedly return to their original description.

## World Visualization

The world can be represented visually without requiring a conventional game engine or detailed graphics.

A location might be displayed using simple web technologies, markup, shapes, icons, sprites, or other lightweight representations. A street could consist of roads, buildings, characters, and labels. A hospital could show beds and their occupants. A quest board could display the quests that currently exist when a world tracks goals as state; worlds that treat goals as narration-only need no board.

The purpose of visualization is not graphical realism. It provides a persistent visual window into the state of the generated world.

The player may therefore experience the same world through both narration and a changing visual representation.

## Open-Ended Scenarios

Mutable Realms is intended to describe a way of representing worlds rather than one specific RPG.

The same principles could support very different scenarios:

* an adventurer exploring towns and wilderness;
* a healer working in a changing community;
* a merchant developing trade routes;
* the captain of a starship exploring space;
* a ruler overseeing a settlement;
* or scenarios created during play.

Different worlds may require different kinds of state and interaction. The system should be extensible rather than assuming that concepts such as combat, character classes, enemies, or quests must exist in every world.

The framework core currently models worlds, revisions, locations, stable entities, placement, characters, operations, and events. Scenario concepts are optional capabilities layered on that core. The deterministic recovery ward remains an end-to-end compatibility fixture under `backend/scenarios/ward/`; beds, patients, and discharge are not required by generic world reads or the browser.

## Agents and Tools

AI agents act as both storytellers and operators of the world.

Rather than requiring the language model to perform every operation through prose, agents can use deterministic tools and scripts for repeated or precise work such as:

* querying locations and characters;
* moving entities;
* transferring items;
* applying quest consequences (rewards, relationship changes);
* changing relationships or conditions;
* creating new world entities;
* validating persistent state.

The AI can concentrate on interpretation, narration, and creative decisions while conventional software handles bookkeeping and consistency.

Infrastructure work is kept conceptually separate from ordinary world interaction. A world agent should be able to change the world without needing to redesign the systems that store or display it.

## Growing Beyond Existing Capabilities

Mutable Realms does not need to understand every possible kind of world in advance.

As play develops, a player may attempt something that the existing representation cannot adequately model. This creates an opportunity to extend the world's capabilities.

For example, a starship story might eventually require persistent star systems and exploration probes. A settlement might develop an economy that did not previously need to be simulated.

Rather than requiring all such mechanics from the beginning, infrastructure can evolve when meaningful player activity creates a reason for it.

This connects persistent AI storytelling with a broader goal of exploring how AI agents might help games acquire new content and mechanics over time.

## Context and Scale

The complete world does not need to fit inside the language model's context window.

Agents should work with the information relevant to the current situation: the player's state, current location, nearby entities, relevant memories, active events, and necessary broader context.

Persistent storage holds the rest.

This allows the world to grow while keeping individual AI interactions manageable.

## Project Goals

Mutable Realms explores whether modern AI agents can support a world that is:

* open-ended without being purely ephemeral;
* persistent without requiring every interaction to be predefined;
* visually understandable without requiring complex graphics;
* capable of remembering consequences through state rather than narration alone;
* extensible as new scenarios require new capabilities;
* and simple enough for both humans and AI agents to understand and modify.

The project is experimental. Its purpose is not to generate an infinite quantity of interchangeable content, but to investigate whether AI can help maintain a world where player actions meaningfully change what exists and what can happen next.

## Development

Mutable Realms uses Python 3.12 with `uv` for the backend and Node.js 22 with npm for the frontend. Install the locked dependencies from the repository root:

```sh
uv sync --frozen
npm ci
```

The npm scripts are the common project entry points:

| Command | Purpose |
| --- | --- |
| `npm test` | Run the backend test suite. |
| `npm run lint` | Run Ruff and TypeScript checks. |
| `npm run serve` | Start one backend worker on port 8790 by default. |
| `npm run frontend-build` | Build the frontend into `frontend/dist/`. |
| `npm run migrate` | Apply pending checksummed SQLite migrations. |
| `npm run seed` | Create the optional deterministic ward and town worlds if absent. |
| `npm run validate` | Check foreign keys and cross-table world invariants. |
| `npm run move-entity -- …` | Apply an idempotent, revision-checked local character move. |
| `npm run world-context -- …` | Build deterministic, read-only context for one world. |
| `npm run world-turn -- …` | Execute one validated structured turn decision and reread authoritative state. |
| `npm run world-tools` | Run the Phase 6 Hermes MCP tool server over stdio. |

Persistence commands and application startup use `MUTABLE_REALMS_DB_PATH`. The development container configures it as `/var/lib/mutable-realms/world.sqlite3`. For an isolated local database, set a different path before running the commands:

```sh
export MUTABLE_REALMS_DB_PATH=/tmp/mutable-realms/world.sqlite3
npm run migrate
npm run seed
npm run validate
```

`migrate` is idempotent and rejects modified or unsupported migration history. Migration `0002_generalize_entities` preserves existing ward databases while allowing scenario-defined entity kinds and character roles. `seed` is a deterministic ward example command retained for development compatibility; it is not required to create every world. `validate` is read-only and exits nonzero when authoritative state violates a supported invariant.

The Phase 5 Context Builder reads the world, player, current location, nearby generic entities, and bounded recent events from one SQLite snapshot. It returns strict scenario-neutral JSON; optional capabilities such as ward occupancy remain separate projections. The event limit defaults to 10 and must be between 1 and 100:

```sh
npm run world-context -- --world-id "$WORLD_ID" --event-limit 10
```

Context generation opens the existing database in SQLite read-only/query-only mode and does not make narration or presentation output authoritative. SQLite may maintain its normal `-wal` and `-shm` coordination files; these are database-engine artifacts, not a second authoritative store. The builder intentionally remains WAL-aware so it does not omit committed state that has not yet been checkpointed into the main database file.

### Hermes world tools

Phase 6 exposes the authoritative application services as a local stdio MCP server. Hermes receives structured tools rather than database credentials or arbitrary SQL:

| Tool | Purpose |
| --- | --- |
| `world_status` | Read world identity, revision, and currently supported mutation tools. |
| `world_context` | Build the bounded Phase 5 context snapshot. |
| `world_inspect_entity` | Read one generic entity and its optional character state. |
| `world_events` | Read a newest-first event window bounded to 1–100 rows. |
| `world_move_entity` | Invoke the generic revision-checked, idempotent move operation. |
| `world_treat_and_discharge_patient` | Invoke the ward capability's atomic treatment/discharge operation. |
| `world_record_social_interaction` | Update one bounded relationship and store one concise event-linked memory. |
| `world_transfer_resource` | Grant or transfer resource units (rewards, currency, items) between characters. |
| `world_update_location` | Rename a location and/or set one bounded property value (cleanliness, condition, prosperity, safety). |
| `world_validate` | Run deterministic database and world-invariant validation. |

The MCP process is bound to exactly one existing database through `MUTABLE_REALMS_DB_PATH`. Tool callers cannot supply another path, missing databases are not created, and every query path opens SQLite in read-only/query-only mode. Context and event limits are enforced as 1–100 in both MCP schemas and application services. Mutation tools retain their application-service validation, expected-revision, operation-ID, transaction, and event guarantees.

From the repository root, register the server with the installed Hermes profile using the supported CLI. Replace the database path with the absolute path visible to the Hermes process:

```sh
export MUTABLE_REALMS_DB_PATH=/absolute/path/to/world.sqlite3
hermes mcp add mutable-realms \
  --command uv \
  --env "MUTABLE_REALMS_DB_PATH=$MUTABLE_REALMS_DB_PATH" \
  --args --directory "$(pwd)" run python -m backend.world.mcp_server
hermes mcp test mutable-realms
```

For a narrated session, also bind the MCP subprocess to the trusted world and player. These values are process configuration, not player-controlled tool arguments:

```sh
hermes mcp add mutable-realms-narration \
  --command uv \
  --env "MUTABLE_REALMS_DB_PATH=$MUTABLE_REALMS_DB_PATH" \
  --env "MUTABLE_REALMS_WORLD_ID=ward-world" \
  --env "MUTABLE_REALMS_PLAYER_ID=player" \
  --args --directory "$(pwd)" run python -m backend.world.mcp_server
```

When this binding is present, every MCP read rejects another world, every world/entity/event read verifies the configured player against that world's context, every mutation uses the configured player as actor, and `world_validate` is disabled because it is an all-world administration diagnostic. Use the unbound registration for validation and other trusted Phase 6 inspection/administration; do not use it as the narration session's gameplay server.

Start a new Hermes session after registration so tool discovery includes the server. `npm run world-tools` is available for direct stdio-server debugging, but it is not an interactive command and should normally be started by Hermes.

There is intentionally no generic `world_update` tool. Arbitrary field updates would bypass scenario rules. Add a named application operation and expose a correspondingly narrow MCP tool when a scenario requires a new mutation.

## Phase 10 social state

Migration `0003_social_state` adds generic, optional social state without changing the core entity model:

* `relationships` stores a bounded score/category for one directed character pair and the event that last changed it;
* `memories` stores concise text owned by an entity and linked to the authoritative event that created it;
* `world_record_social_interaction` is one atomic, idempotent, expected-revision-checked operation that updates one relationship and records one memory;
* context includes only relationships and memories involving the player and entities in the current location;
* memory content is limited to 500 characters and full chat transcripts are not accepted;
* validation checks relationship endpoint/world coherence and memory/event world coherence.

The trusted narration MCP binding exposes the social operation with the configured player as actor. Worlds with fewer than two characters do not advertise it. Social state is read from SQLite, survives process restart, and remains separate from generated narration and browser presentation.

## Narration-only goals

Quests are not tracked as world state. Accepting, progressing, and completing a quest is narration; quest continuity lives in narration memory and may be inconsistent across turns by design. What persists are a quest's effects, applied through the same named atomic operations as any other mutation: relationships (`world_record_social_interaction`), rewards and resources (`world_transfer_resource`), and entity or location changes (deferred to Phase 12). An effect must never be narrated as applied unless its operation committed. No quest board or goal lifecycle is required; a minimal completed-goal ledger may be added later only if play demands deduplication of rewards.

## Resources

Migration `0004_resources` adds a generic, optional resource ledger without changing the core entity model:

* `resources` stores a non-negative quantity of one resource type (for example `coin`) per character and the event that last changed it;
* `world_transfer_resource` is one atomic, idempotent, expected-revision-checked operation that grants units from the world (a quest reward) or transfers them between characters;
* context includes only resources owned by the player and entities in the current location;
* validation checks resource owner world/character coherence and update-event linkage;
* the operation is advertised when the world has at least one character, and the configured narration player is always the actor.

## Mutable locations

Migration `0005_location_properties` adds optional persistent location state without changing the core entity model:

* `location_properties` stores a bounded 0–100 value for scenario-defined properties (initial taxonomy: `cleanliness`, `condition`, `prosperity`, `safety`) and the event that last changed it;
* `locations.name` remains the mutable display name behind stable IDs, so a location can evolve (The Slums → Improving Riverside → Riverside Quarter) while keeping its identity;
* `world_update_location` is one atomic, idempotent, expected-revision-checked operation that renames a location and/or sets one property value;
* context includes the current location's properties; validation checks property world/location coherence and update-event linkage;
* the operation is advertised when the world has at least one location, and the configured narration player is always the actor.

## Connected worlds and travel

Migration `0006_location_links` adds optional undirected adjacency between locations:

* `location_links` stores world-scoped edges in canonical `location_a < location_b` form; worlds without links simply have no travel;
* `world_move_entity` now requires the destination to be linked to the entity's current location;
* `world_context` reports `linked_locations` (reachable neighbors) for the current location, so a narrated turn can offer travel;
* after a travel turn, the context working set streams the new location's entities, properties, and events;
* the deterministic `seed` command also creates `town-world` (Harbor Town: plaza ↔ market ↔ docks ↔ tavern) so travel is immediately playable.

Phase 7 adds the model-independent turn policy in `backend.world.turns` and documents the Hermes-facing contract in `docs/narration-agent-contract.md`. A narration session must be trusted-bound to one world and player. For each player message, Hermes reads `world_status` and `world_context`, returns exactly one structured decision kind, invokes at most one advertised mutation with the observed revision and a fresh operation ID, rereads context, and narrates only the persisted result. A stale revision causes one fresh-context reevaluation; rejected, missing, unsupported, and failed operations must never be narrated as successful.

The deterministic CLI seam exercises the same policy without an external model. It accepts a validated decision JSON while preserving the original player action for the model-facing contract:

```sh
npm run world-turn -- \
  --world-id ward-world \
  --player-id player \
  --player-action "Treat the patient in the first bed." \
  --turn-operation-id turn-treatment-1 \
  --decision-json '{"kind":"perform_one_supported_operation","operation":{"operation_type":"world_treat_and_discharge_patient","patient_id":"patient-1","bed_id":"bed-1"}}'
```

This command is a deterministic acceptance/debugging seam, not a replacement for Hermes interpretation. Use the existing `hermes mcp add` registration above for live narration through the WebUI and keep the browser visualization in a separate tab.

Build the browser interface before starting the API when you want the backend to serve the complete application:

```sh
npm run frontend-build
npm run serve
```

The interface is then available at `http://localhost:8790/`. It discovers available worlds, lets the player select one, and renders that world's current location, arbitrary entity kinds, revision, and recent events. Selection is reflected in the `?world=...` URL parameter. It refreshes authoritative state every five seconds or when **Refresh state** is selected. If `frontend/dist/` is absent, the backend still starts with its API, health, and OpenAPI routes available.

The API applies pending migrations during startup and fails startup if migration history is invalid. Its health endpoints are:

* `GET /health/live` — the process can answer requests;
* `GET /health/ready` — the configured database is reachable and has exactly the supported schema history.

The initial read-only world API is documented interactively at `GET /docs` and in the generated schema at `GET /openapi.json`:

| Route | Purpose |
| --- | --- |
| `GET /api/worlds` | List available worlds for selection. |
| `GET /api/worlds/{world_id}/player` | Read the world's current player and placement. |
| `GET /api/worlds/{world_id}/locations/current` | Read the current player's location and generic entity contents. |
| `GET /api/worlds/{world_id}/locations/{location_id}` | Read a specific location and its current contents. |
| `GET /api/worlds/{world_id}/entities/{entity_id}` | Read generic entity details and optional character state. |
| `GET /api/worlds/{world_id}/events?limit=20` | Read newest-first persistent world events; limit must be 1–100. |
| `GET /api/worlds/{world_id}/capabilities/ward/locations/{location_id}` | Read optional ward bed occupancy without adding it to generic location contracts. |

These endpoints are presentation reads only. Authoritative mutations continue to pass through controlled backend application services rather than arbitrary HTTP writes or frontend state.

The first Phase 3 operation moves a character between existing locations through the local CLI. It requires a caller-generated operation ID and the world revision on which the decision was based. The destination must already be provisioned through trusted world setup or import tooling.

```sh
npm run move-entity -- \
  --world-id "$WORLD_ID" \
  --operation-id "$OPERATION_ID" \
  --expected-revision "$EXPECTED_REVISION" \
  --entity-id "$ENTITY_ID" \
  --destination-location-id "$DESTINATION_LOCATION_ID" \
  --actor-entity-id "$ACTOR_ENTITY_ID"
```

The command emits a JSON result containing the committed world revision and whether the request was an idempotent replay. It rejects stale revisions, cross-world locations, discharged characters, bed entities, and characters currently occupying a bed. The destination must already exist. The move, operation record, revision increment, and event are committed atomically. This is a trusted local administration/agent interface; the browser and HTTP API remain read-only pending an authenticated mutation design.

