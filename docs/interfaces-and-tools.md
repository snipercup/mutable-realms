# Interfaces and Tools

Technical reference for Mutable Realms: environment variables, commands, HTTP API, MCP tools, and the Hermes narration setup. For design and development guidance see [maintenance-guide.md](maintenance-guide.md); for the narration agent's behavioral contract see [narration-agent-contract.md](narration-agent-contract.md).

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `MUTABLE_REALMS_DB_PATH` | Path of the authoritative SQLite database. Required by the server and most commands. | — |
| `MUTABLE_REALMS_PORT` | HTTP port for `npm run serve`. | `8790` |
| `MUTABLE_REALMS_NARRATOR_PROFILE` | Hermes profile used by the turn relay. | `mutable-realms-narration` |
| `MUTABLE_REALMS_NARRATOR_TIMEOUT` | Turn relay timeout in seconds. | `120` |

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

## HTTP API

Interactive docs: `GET /docs`; generated schema: `GET /openapi.json`. Startup applies pending migrations and fails if history is invalid.

### Health

| Route | Meaning |
| --- | --- |
| `GET /health/live` | The process can answer requests. |
| `GET /health/ready` | The database is reachable and has exactly the supported schema history. |

### World reads (presentation only)

| Route | Purpose |
| --- | --- |
| `GET /api/worlds` | List worlds. |
| `GET /api/worlds/{world_id}/player` | Current player and placement. |
| `GET /api/worlds/{world_id}/map` | Derived map: every location with entity-kind counts and linked locations, plus the player's location. |
| `GET /api/worlds/{world_id}/locations/current` | Player's current location and generic contents. |
| `GET /api/worlds/{world_id}/locations/{location_id}` | One location and its contents. |
| `GET /api/worlds/{world_id}/entities/{entity_id}` | One entity and optional character state. |
| `GET /api/worlds/{world_id}/events?limit=20` | Newest-first events (limit 1–100). |
| `GET /api/worlds/{world_id}/capabilities/ward/locations/{location_id}` | Optional ward bed occupancy. |

### Player turns

`POST /api/worlds/{world_id}/turns` — body `{player_id, player_action, decision_json?}`.

- **With `decision_json`**: the deterministic seam over HTTP (same `run_turn` path as `world-turn`); tests and scripted play drive exact decisions. Returns `{outcome, message, revision_before, revision_after, attempts, mutation}`.
- **Without it**: relays the action to the bound narration agent (`hermes --profile mutable-realms-narration chat`), which reads the world, performs at most one supported mutation, and returns player-facing narration. Returns `{outcome: "narrated_turn", narration, revision_before, revision_after}`.
- Errors: `404` unknown world · `409` player does not match the world's bound player · `422` invalid decision or blank action · `502` narration agent unavailable.

Narration is presentation-only and never persisted. The narration profile stays bound to one world and one player; the interface works for that world and the agent honestly refuses others. The relay is injectable for tests (`create_app(..., narrator=...)`).

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
| `world_validate` | Whole-world administration diagnostic; **refused when a session is bound**. |

Mutations are advertised only for worlds that support them (e.g. the ward operation only where ward state exists). Every mutation requires `world_id`, `operation_id` (fresh per call), and the observed `expected_revision`.

## Hermes narration setup

A dedicated Hermes profile is trusted-bound to one world and one player through MCP environment variables:

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
