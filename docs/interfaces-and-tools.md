# Interfaces and Tools

Technical reference for Mutable Realms: environment variables, commands, HTTP API, MCP tools, and the Hermes narration setup. For design and development guidance see [maintenance-guide.md](maintenance-guide.md); for the narration agent's behavioral contract see [narration-agent-contract.md](narration-agent-contract.md).

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `MUTABLE_REALMS_DB_PATH` | Path of the authoritative SQLite database. Required by the server and most commands. | — |
| `MUTABLE_REALMS_PORT` | HTTP port for `npm run serve`. | `8790` |
| `MUTABLE_REALMS_NARRATOR_PROFILE` | Hermes profile used by the turn relay. | `mutable-realms-narration` |
| `MUTABLE_REALMS_NARRATOR_TIMEOUT` | Turn relay timeout in seconds. Values are bounded to 5–300 seconds. | `120` |
| `MUTABLE_REALMS_START_NARRATOR_TIMEOUT` | World-start narration timeout in seconds. Values are bounded to 5–300 seconds. | `240` |

The live database lives outside Git in a bind-mounted state directory; backups are written beside it.

## npm scripts

| Command | Purpose |
| --- | --- |
| `npm test` | Run the backend test suite (pytest). |
| `npm run lint` | Ruff (backend) + TypeScript check. |
| `npm run serve` | Start one backend worker on `MUTABLE_REALMS_PORT`. |
| `npm run frontend-build` | Build the frontend into `frontend/dist/`. |
| `npm run frontend-check` | Type-check the frontend (`tsc --noEmit`). |
| `npm run migrate` | Apply pending checksummed migrations. |
| `npm run seed` | Create the deterministic ward and town worlds if absent. |
| `npm run validate` | Check foreign keys and cross-table world invariants. |
| `npm run backup -- [--backup-dir DIR]` | SQLite online-backup snapshot with verification. |
| `npm run move-entity -- …` | Revision-checked, idempotent character move. |
| `npm run world-context -- …` | Read-only context snapshot for one world. |
| `npm run world-turn -- …` | Execute one structured turn decision deterministically. |
| `npm run create-scenario -- …` | Create one authoring scenario (title, optional description). |
| `npm run update-scenario -- …` | Update a scenario's title and/or description. |
| `npm run set-scenario-element -- …` | Upsert one scenario story element. |
| `npm run remove-scenario -- …` | Remove a scenario and its elements (destructive). |
| `npm run create-world-from-scenario -- …` | Instance a new world from a scenario (copies title/description/elements). |
| `npm run update-world -- …` | Update a world's title and/or description (revision-checked). |
| `npm run set-world-element -- …` | Upsert one world-owned story element (revision-checked). |
| `npm run remove-world -- …` | Remove a world and all of its state (destructive, revision-checked). |
| `npm run world-tools` | Run the MCP tool server over stdio. |

## CLI commands

All commands accept `--db-path` to override `MUTABLE_REALMS_DB_PATH`.

```sh
# Lifecycle and safety
npm run migrate          # idempotent; rejects modified/unsupported history
npm run seed             # idempotent; ward-world + town-world
npm run validate         # read-only invariant check; exit 1 on violations
npm run backup           # verified snapshot into backups/; prints path + SHA-256

# Deterministic turn seam (acceptance/debugging)
npm run world-turn -- \
  --world-id ward-world \
  --player-id player \
  --player-action "Treat the patient in the first bed." \
  --turn-operation-id turn-treatment-1 \
  --decision-json '{"kind":"perform_one_supported_operation","operation":{"operation_type":"world_treat_and_discharge_patient","patient_id":"patient-1","bed_id":"bed-1"}}'
```

`world-turn` prints a JSON payload with `outcome` (one of `success`, `no_mutation`, `idempotent_replay`, `clarification`, `capability_gap`, `invalid_action`, `missing_resource`, `mutation_rejected`, `stale_revision`, `tool_failure`), `before`/`after` contexts, `decision`, `mutation`, `message`, and `attempts`. Fresh operation IDs per turn are part of the idempotency contract.

```sh
npm run world-context -- --world-id "$WORLD_ID" --event-limit 10
npm run move-entity -- --world-id "$WORLD_ID" --operation-id "$OP" \
  --expected-revision "$REV" --entity-id "$ENTITY" \
  --destination-location-id "$DEST" --actor-entity-id "$ACTOR"
```

### Scenario authoring

Scenarios are reusable authoring templates (title, description, and story elements) from which worlds are instanced later. They are administrative data — never exposed through the turn policy or the narration agent.

```sh
npm run create-scenario -- --scenario-id aerthalon --operation-id op-1 \
  --title "Aerthalon" --description "A vast ancient fantasy world."
npm run set-scenario-element -- --scenario-id aerthalon --operation-id op-2 \
  --element-type opening_scene --content "You arrive at the gates of the guild city."
npm run update-scenario -- --scenario-id aerthalon --operation-id op-3 --title "Aerthalon Reborn"
npm run remove-scenario -- --scenario-id aerthalon --operation-id op-4
```

Element types: `author_note`, `plot_essentials`, `opening_scene` (content 1–20000 characters). Scenario mutations are idempotent by caller operation ID; a removed scenario leaves no trace (its elements and operation records cascade).

### World instancing

Instancing copies the scenario's title, description, and story elements into a fresh world (revision 0 → 1 with a `world_created` event) and records `source_scenario_id`. The scenario is never modified; the world owns its copies, so the two diverge independently. Deleting a scenario leaves its instanced worlds intact (`source_scenario_id` becomes NULL).

```sh
npm run create-world-from-scenario -- --world-id aerthalon-campaign \
  --operation-id op-5 --scenario-id aerthalon
```

World management after creation is revision-checked (pass the revision your decision was based on) and idempotent by operation ID:

```sh
npm run update-world -- --world-id aerthalon-campaign --operation-id op-6 \
  --expected-revision 1 --title "Aerthalon Reborn"
npm run set-world-element -- --world-id aerthalon-campaign --operation-id op-7 \
  --expected-revision 2 --element-type opening_scene --content "New opening."
npm run remove-world -- --world-id aerthalon-campaign --operation-id op-8 \
  --expected-revision 3
```

A world instanced from a scenario has no player or locations until a reusable character is instanced. Create a definition first, then select it for a world and provide the world-specific starting location:

```sh
npm run create-player-character -- --character-id fate --operation-id character-create-1 \
  --title fate --description "Human diplomat, 24, silver hair"
npm run provision-player -- --world-id aerthalon-campaign --operation-id op-9 \
  --expected-revision 3 --player-name fate --location-name Settlement
```

The administrative `provision-player` command remains a compatibility path for directly naming a player. The management UI uses the reusable-definition instance route instead:

```http
POST /api/worlds/{world_id}/character-instance
{"character_id":"fate","location_name":"Settlement","operation_id":"…","expected_revision":3}
```

Definition edits and deletion never rewrite an existing world instance; the instance retains copied name/basic info and its own world state.

### Narrator-driven world start

World-start narration uses `MUTABLE_REALMS_START_NARRATOR_TIMEOUT` separately from normal turn narration. It defaults to 240 seconds and is clamped to 5–300 seconds. When it expires, the server logs the world ID, configured timeout, and measured elapsed duration, but the HTTP response remains the stable player-facing message `narration agent timed out while preparing the world`.

A playerless world can be started from Play mode with a reusable character definition. `POST /api/worlds/{world_id}/start` accepts `{character_id, operation_id, expected_revision}`. The relay gives the narrator the selected world read, story elements/opening scene, and reusable character snapshot. The narrator must infer an appropriate starting scale from that context, then return JSON with `start_location_name`, `locations` (3–16 objects containing `name`, `description`, `parent_name`, and `link_to_start`), and player-facing `narration`. A valid structured layout must contain the selected start as a parentless scope, at least one direct child of that start, and at least one other parentless sibling at the same scale. Street-level urban openings should include at least 10 direct children beneath the start, while the complete layout remains bounded at 16 locations; other scales may use fewer locations. Siblings are bounded nearby geography, not automatic movement links. A building or mall approach normally uses street level; a wilderness opening may use city or province scale. The selected `start_location_name` is also persisted as the player's default map scope (`is_map_scope = true`, `is_default_scope = true`), so a start at Main Street renders Main Street's child locations as the local map rather than falling back to `Map of <world>`. `parent_name` creates containment only, while `link_to_start` explicitly requests local movement adjacency. Only after that result validates does the server call the atomic character-instance operation, creating the bounded location layout, containment, explicit links, world-specific player, placement, and event in one revision. The start response includes the copied instance IDs and revisions. The operation result stores the narration so an exact replay returns the same response without invoking the narrator again. Invalid structured narrator output leaves the world playerless. Legacy narrator results containing only `location_name` and `location_description` remain compatible and create one location. The parser also normalizes two bounded model-format variants: `null` link flags become `false`, and a link flag conta...


Interactive docs: `GET /docs`; generated schema: `GET /openapi.json`. Startup applies pending migrations and fails if history is invalid.

### Health

| Route | Meaning |
| --- | --- |
| `GET /health/live` | The process can answer requests. |
| `GET /health/ready` | The database is reachable and has exactly the supported schema history. |

### World reads (presentation only)

| Route | Purpose |
| --- | --- |
| `GET /api/worlds` | List worlds (including description and source scenario). |
| `GET /api/worlds/{world_id}` | One world with its owned story elements and player summary. |
| `GET /api/worlds/{world_id}/player` | Current player and placement. |
| `POST /api/worlds/{world_id}/player` | Provision a player + starting location (body `{player_name, location_name, operation_id, expected_revision}`). |
| `GET /api/worlds/{world_id}/map` | Derived map. Optional `scope_location_id` selects an administrative/read-only scope and `limit` bounds the visible graph to 1–100 direct children plus bounded sibling neighbors. Without an explicit scope, a world with a player uses the player's current location as the scope on every read; the response includes that anchor, direct children, sibling neighbors marked `is_neighbor`, exact/player-visible location IDs, `boundary_links` for exits beyond the visible set, and `route_chain` for active directed routes reachable from the scope, ordered by destination `short`, `mid`, then `long` range metadata. Route entries are informational and do not create UI travel controls. |
| `GET /api/worlds/{world_id}/locations/current` | Player's current location and generic contents. |
| `GET /api/worlds/{world_id}/locations/{location_id}` | One location and its contents. |
| `GET /api/worlds/{world_id}/entities/{entity_id}` | One entity and optional character state. |
| `GET /api/worlds/{world_id}/events?limit=20` | Newest-first events (limit 1–100). |
| `GET /api/worlds/{world_id}/capabilities/ward/locations/{location_id}` | Optional ward bed occupancy. |

### Scoped maps and location hierarchy

`locations` remain authoritative physical places. Migration `0011_location_hierarchy` adds two additive stores:

- `location_containment(world_id, child_location_id, parent_location_id)` gives each location at most one same-world parent. It is a containment relation, not a movement edge. Parentless locations are roots under the virtual world scope; legacy flat worlds therefore require no synthetic hierarchy.
- `location_metadata(world_id, location_id, kind, geography_role, direction, range_band, is_map_scope, is_default_scope)` stores descriptive kind plus explicit transition/route-orientation metadata. `geography_role` is `local`, `boundary`, or `route`; `direction` is cardinal/intercardinal; `range_band` is `short`, `mid`, or `long`. In scoped maps, these values are relative to the selected map scope: direction controls deterministic ordering/placement and range band controls coarse separation/grouping. Missing orientation falls back to stable name/ID ordering and circular placement. These fields orient presentation and do not grant movement.
- `location_scope_promotions(world_id, scope_location_id, location_id)` stores explicit presentation-only landmark promotions. Both locations must belong to the same world; a promoted location keeps its existing single containment parent.

`GET /api/worlds/{world_id}/map` without a hierarchy scope preserves the legacy flat map. The scoped response returns the current location as scope metadata plus bounded direct children, sibling neighbors, and promoted landmarks; the player-facing map renderer uses the scope name for the title but does not draw the scope node or a player highlight. Scoped maps use the SVG as the child/neighbor location index rather than repeating those locations in a separate list. When orientation metadata is present, the response keeps the scope first and orders visible locations by range, direction, name, and ID; the frontend places them using the same direction/range semantics. Boundary links remain separately exposed and rendered as exits. Internal `location_links` remain authoritative for narration and movement validation but are not rendered as scoped-map edges; flat legacy maps retain their existing link rendering. Links crossing the visible boundary appear in `boundary_links` and do not create inferred adjacency. Map zoom and scope selection are read-only presentation actions.

`PUT /api/worlds/{world_id}/locations/{location_id}/hierarchy` is an administrative world mutation. It validates same-world parents, rejects self-parenting and containment cycles, records an event, bumps the world revision, and supports exact operation replay. Reparenting changes containment metadata only; it does not add, remove, or rewrite `location_links`. Ordinary movement continues to require a direct physical link between the exact current and destination locations.

The narrator context includes only the current location's containment breadcrumb and preferred map scope. It continues to expose exact movement neighbors rather than injecting an entire scoped map.

The expansion service is the controlled narrator-facing creation seam. `world_expand_location` accepts one structured proposal: a stable `proposal_id`, new `location_id`, existing `anchor_location_id`, bounded `name`/`description`, optional same-world `parent_location_id`, and optional explicit physical link to the anchor. It accepts at most one location per operation, records the proposal, rejects duplicate IDs/names/proposals, and enforces a default budget of 100 accepted expansions per world (overrideable by the administrative `world_expansion_limits` row). It creates the location, optional containment, optional `location_links` row, operation, event, and revision atomically. It does not generate routes, entities, or additional geography.

The active structured start contract creates 3–16 locations and may mark a parentless sibling as `geography_role: boundary` with a direction and range band. Street-level urban starts should contain at least 10 direct children beneath the selected start; other opening scales may use fewer locations within the bound. A generic road beyond a gate, a sea route, or train track endpoint can therefore be named and oriented without being confused with a static child landmark. Route records remain the authoritative directed travel chain; future map work can render short/mid/long route destinations from those records rather than inferring routes from sibling placement.

`route_chain` is a derived, bounded breadth-first presentation of active `world_routes` beginning at the map scope. Each entry contains the directed route, destination name, `chain_depth`, destination `geography_role`, direction, and range band. Cycles and duplicate route IDs are suppressed; at most 100 route entries are returned. A missing range band is sorted after `short`, `mid`, and `long`. The response does not imply that a route is accessible to the player; narrator-driven route travel remains the only gameplay mutation seam.

`POST /api/worlds/{world_id}/route-travel` and MCP `world_travel_route` apply one active route to a character. The operation requires the exact current location to equal the route origin, validates the character/actor and revision, moves only the entity placement, records `entity_route_traveled`, and supports exact replay. It does not consult or modify `location_links`; route travel is explicit transit, not inferred local adjacency. Travel is rejected when the route is inactive or absent; successful travel requires an active, present route. No time, cost, discovery, or automatic route generation is implied.


### World administration

| Route | Purpose |
| --- | --- |
| `POST /api/worlds` | Instance a world from a scenario — body `{world_id, scenario_id, operation_id}`. Returns `{already_applied, world_id, world_revision, source_scenario_id}`. |
| `PATCH /api/worlds/{world_id}` | Update title/description — body `{title?, description?, operation_id, expected_revision}`. |
| `PUT /api/worlds/{world_id}/elements/{element_type}` | Upsert one world element — body `{content, operation_id, expected_revision}`. |
| `DELETE /api/worlds/{world_id}?operation_id=…&expected_revision=…` | Remove a world and all of its state (destructive). |
| `PUT /api/worlds/{world_id}/locations/{location_id}/hierarchy` | Set one location's parent and descriptive map metadata — body `{operation_id, expected_revision, parent_location_id?, kind?, is_map_scope, is_default_scope}`. The operation is revision-aware and exactly idempotent. |
| `PUT /api/worlds/{world_id}/locations/{location_id}/scope-promotion` | Add or remove one explicit presentation promotion — body `{scope_location_id, is_promoted?, operation_id, expected_revision}`. The scope and landmark must belong to the same world; the scope must be map-capable. Exact replay is supported. |
| `POST /api/worlds/{world_id}/locations/expand` | Accept one bounded structured location proposal — body `{proposal_id, location_id, anchor_location_id, name, description?, parent_location_id?, connect_to_anchor?, actor_entity_id?, operation_id, expected_revision}`. |
| `PUT /api/worlds/{world_id}/routes/{route_id}` | Create or replace one directed route definition — body `{route_id, origin_location_id, destination_location_id, name, description?, route_kind?, is_active?, operation_id, expected_revision}`. |
| `POST /api/worlds/{world_id}/route-travel` | Apply one active route to a character at its exact origin — body `{route_id, entity_id, actor_entity_id?, operation_id, expected_revision}`. |

Errors: `404` unknown scenario or world · `409` duplicate id, operation-ID reuse, or stale revision.

### Scenario authoring

Admin endpoints for reusable authoring templates (see the CLI section for element types and idempotency semantics). Scenario ids are lowercase kebab-case.

| Route | Purpose |
| --- | --- |
| `GET /api/scenarios` | List scenarios (without elements). |
| `GET /api/scenarios/{scenario_id}` | One scenario with its elements. |
| `POST /api/scenarios` | Create — body `{scenario_id, title, description?, operation_id}`. |
| `PATCH /api/scenarios/{scenario_id}` | Update title/description — body `{title?, description?, operation_id}`. |
| `PUT /api/scenarios/{scenario_id}/elements/{element_type}` | Upsert one element — body `{content, operation_id}`. |
| `DELETE /api/scenarios/{scenario_id}?operation_id=…` | Remove a scenario (destructive). |

Errors: `404` unknown scenario · `409` duplicate id or operation-ID reuse.

### Player turns

`POST /api/worlds/{world_id}/turns` — body `{player_id, player_action, decision_json?}`.

- **With `decision_json`**: the deterministic seam over HTTP (same `run_turn` path as `world-turn`); tests and scripted play drive exact decisions. Returns `{outcome, message, revision_before, revision_after, attempts, mutation}`.
- **Without it**: builds the selected world's authoritative context (world, player, location, story elements, recent events) and relays the action to the narration agent (`hermes --profile mutable-realms-narration chat`) with that context embedded in the prompt, so the agent narrates the world the page chose. The agent performs at most one supported mutation, then returns player-facing narration. Returns `{outcome: "narrated_turn", narration, revision_before, revision_after}`. The relay runs the CLI in quiet mode and strips rendered reasoning and meta-commentary so `narration` is the immersive prose only (the narration profile also sets `display.show_reasoning: false`).
- Errors: `404` unknown world · `409` player does not match the world's player · `422` invalid decision or blank action · `502` narration agent unavailable.

Narration is presentation-only and never persisted. The narration profile's MCP env provides a default world+player, but the relayed turn tells the agent which world is authoritative and the tools accept that world explicitly. The relay is injectable for tests (`create_app(..., narrator=...)`).

## MCP tools (Hermes)

The MCP server (`python -m backend.world.mcp_server`) exposes controlled application services, never SQL or database paths:

| Tool | Purpose |
| --- | --- |
| `world_status` | World identity, revision, and currently supported mutation tools (`available_mutations`). |
| `world_context` | Bounded context snapshot (player, location, entities, relationships, resources, properties, events). |
| `world_inspect_entity` | One entity and optional character state. |
| `world_events` | Newest-first event window. |
| `world_move_entity` | Revision-checked, idempotent move; destination must be linked. |
| `world_treat_and_discharge_patient` | Ward compound operation (recover + discharge + free bed). |
| `world_record_social_interaction` | Relationship upsert + memory insert. |
| `world_transfer_resource` | Grant from the world or transfer between characters. |
| `world_update_location` | Rename a location and/or set one property value. |
| `world_validate` | Whole-world administration diagnostic; **refused when a session binding is configured**. |

Mutations are advertised only for worlds that support them (e.g. the ward operation only where ward state exists). Every tool accepts `world_id` (optional on reads, required on mutations — naming the world explicitly on a mutation is deliberate); when omitted on a read it falls back to the profile binding. Every mutation requires `world_id`, `operation_id` (fresh per call), and the observed `expected_revision`. The page's turn relay embeds the selected world's context into the prompt and instructs the agent to pass that `world_id` explicitly, so the agent operates on the world the player chose.

## Hermes narration setup

A dedicated Hermes profile provides a default world and player through MCP environment variables (the defaults are overridden per turn by the relay):

```sh
hermes mcp add mutable-realms-narration \
  --command uv \
  --env MUTABLE_REALMS_DB_PATH=/path/to/world.sqlite3 MUTABLE_REALMS_WORLD_ID=town-world MUTABLE_REALMS_PLAYER_ID=sailor \
  --args --directory /path/to/repo run python -m backend.world.mcp_server
```

- `--env` takes space-separated `KEY=VALUE` pairs on ONE flag; repeated flags keep only the last.
- The profile's `SOUL.md` must carry the narration contract (see `docs/narration-agent-contract.md`) and hard rules: never use Hermes memory for world state, never narrate an uncommitted change, read `world_status` + `world_context` before every turn.
- **Container gotcha**: the Hermes WebUI keeps one long-lived MCP subprocess per profile, shared across chats. After changing MCP code or the binding, restart the container — a new chat does not respawn the subprocess. The page's turn relay calls `hermes` fresh per turn, so the agent picks up new code immediately; only the page's own server needs a restart to serve new backend routes.

## Frontend

Source lives in `frontend/src/` (TypeScript + Vite + plain DOM/SVG, no framework). The deployed form is the built bundle in `frontend/dist/`, served by the application server. While developing, run `npm run frontend-build` after changes; `npm run frontend-check` type-checks. The page discovers worlds, renders location/entities/events/map from API data, and accepts player actions through the turn relay.
