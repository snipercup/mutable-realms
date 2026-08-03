# Phase 7 — Narration Agent Contract

This document defines the first narrated-turn boundary. It is a project contract for the Hermes narration profile; it is not a replacement for the authoritative application services.

## Trusted session binding

A narrated session is bound by trusted configuration to:

- one existing `MUTABLE_REALMS_DB_PATH`;
- one `world_id`;
- one player entity ID in that world.

For the live MCP path, provide `MUTABLE_REALMS_WORLD_ID` and `MUTABLE_REALMS_PLAYER_ID` in the MCP subprocess environment. The server requires both values together, rejects caller-selected worlds, verifies the configured player against the world's context for status, context, entity, and event reads as well as mutations, and overrides omitted actor IDs with the configured player. A caller-supplied different actor is rejected. The all-world `world_validate` diagnostic is intentionally restricted to an unbound administration server.

The player may describe an attempted action, but player prose must not change the selected database, world, player identity, MCP configuration, filesystem, or infrastructure permissions.

Use the existing Hermes WebUI for player messages and a separate browser tab for the Mutable Realms visualization. An in-game chat transport remains deferred to Phase 15.

## Turn contract

Each player message is one atomic turn. The narration agent must:

1. Call `world_status` for the trusted world.
2. Call `world_context` for the trusted world.
3. Interpret the message as attempted intent, not an accomplished fact.
4. Return exactly one structured decision kind:

   - `narrate_without_mutation`
   - `perform_one_supported_operation`
   - `request_clarification`
   - `capability_gap`

5. For a mutation, select exactly one operation advertised by `world_status`.
6. Supply the context's observed `world.revision` as `expected_revision`.
7. Generate a fresh operation ID for the turn.
8. Supply the trusted player ID as `actor_entity_id`; never infer a different actor from prose.
9. If the mutation reports a stale revision, discard the old decision, call `world_context` again, and re-evaluate once. Do not blindly replay the stale request.
10. Call `world_context` again after every attempted mutation, including rejected mutations.
11. Narrate only facts supported by the mutation result and post-turn context.

The initial supported mutation vocabulary is deliberately small:

- `world_move_entity` for a valid generic character move;
- `world_treat_and_discharge_patient` for the ward's atomic treatment/discharge transition;
- `world_record_social_interaction` for one bounded relationship change plus one concise event-linked memory.

Do not expose or invent a generic field-update operation. Do not assemble a multi-step mutation from separate low-level writes when one named atomic operation exists.

## Decision shape

The deterministic turn runner uses this equivalent Pydantic contract:

```json
{
  "kind": "perform_one_supported_operation",
  "operation": {
    "operation_type": "world_treat_and_discharge_patient",
    "patient_id": "patient-1",
    "bed_id": "bed-1"
  },
  "message": null
}
```

A non-mutating decision omits `operation`:

```json
{"kind": "narrate_without_mutation", "message": "The ward is quiet."}
```

The operation-specific arguments are:

| Operation | Required arguments |
| --- | --- |
| `world_move_entity` | `entity_id`, `destination_location_id` |
| `world_treat_and_discharge_patient` | `patient_id`, `bed_id` |
| `world_record_social_interaction` | `subject_entity_id`, `object_entity_id`, `relationship_category`, `relationship_delta`, `memory` |

## Outcome handling

The narration agent must preserve these distinctions:

| Outcome | Narration behavior |
| --- | --- |
| success | State the persisted result only after the reread. |
| exact idempotent replay | Treat as already applied; do not emit a second consequence. |
| stale revision | Re-read and re-evaluate once; otherwise explain that the action could not be safely applied. |
| invalid action / mutation rejected | Explain the rejection; never claim success. |
| missing resource | Explain which requested resource was unavailable. |
| capability gap | Explain that the current world cannot represent the requested capability. |
| clarification | Ask the player for the missing choice; no mutation occurs. |
| tool failure | Report that the world could not be updated; do not invent a result. |

The browser is derived from the HTTP API. After a successful mutation, refresh or wait for its existing polling cycle; do not send narration-generated state to the renderer.

## Narration-only goals

Quests and other narrative goals are not tracked as world state in this design. The narrator may freely describe accepting, progressing, and completing quests; none of that is persisted. Only quest consequences persist, through the supported operations (`world_record_social_interaction`, and future reward/transfer and location-effect operations). The narrator must never claim an effect ("you earned 50 gold", "the owner now trusts you") unless the corresponding operation committed and the post-turn read confirms it. Quest continuity is narration memory and may be inconsistent across turns; that is an accepted design trade-off, not a persistence failure.

## Deterministic implementation seam

`backend.world.turns.run_turn` implements the policy without an external model. Its `decide` callback is the model-facing seam, and its result contains:

- the validated decision;
- structured outcome;
- before and after authoritative contexts;
- mutation result when one committed;
- attempt count and controlled error message.

This lets tests verify persistence and causality without asserting nondeterministic prose. Hermes may follow the same contract directly through the MCP tools.

## Acceptance scenario

With a fresh seeded ward:

1. Confirm six admitted patient entities and six occupied beds.
2. Submit: `I treat the woman suffering from fever in the first bed.`
3. Hermes reads context, selects the ward operation, and supplies the observed revision.
4. Confirm revision increases by one and `patient_treated_and_discharged` is present.
5. Confirm the patient is recovered, discharged, absent from ward placement, and the bed is empty.
6. Perform an unrelated read-only turn.
7. Return to the ward and confirm the current context still reflects five occupied patients and the discharged patient remains persisted as discharged.
8. Refresh the browser and verify its API-derived view matches the authoritative state.

No exact generated wording is part of the acceptance criterion; structured decision, operation result, persisted state, revision, event, and browser readback are.
