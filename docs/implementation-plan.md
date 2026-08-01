# Mutable Realms — Implementation Plan

## Purpose

This document defines the initial implementation direction for Mutable Realms. Players describe actions through narration, an AI agent determines and narrates their consequences, and the resulting changes are written into authoritative world state. A lightweight web client visualizes that state.

The long-term idea is broader than any one setting or mechanic: Mutable Realms should support open-ended narrative experiences in the spirit of AI-driven text adventures while grounding them in persistent, inspectable state. A ward and its patients are used only as the first concrete proof scenario. They must not become assumptions built into the platform as a whole.

The first goal is not to build a general AI game engine. The first goal is to prove a reliable loop:

**player action → relevant world state → narration and decision → validated state mutation → persistent world → updated visualization**

The initial implementation should remain deliberately small, inspectable, deterministic where possible, and easy for AI agents to modify.

---

# 1. Core Design Rules

These principles should guide all implementation decisions.

### World state is authoritative

Narration describes the world but does not define persistent truth by itself.

The visualization displays world state but is not the source of truth.

If narration, visualization, and stored state disagree, stored validated world state wins.

### Agents reason; software performs bookkeeping

Use the LLM for:

* interpreting open-ended player actions;
* deciding plausible consequences;
* narration;
* creating appropriate new world content;
* selecting existing world operations.

Use deterministic software for:

* database access;
* quantities;
* inventory transfers;
* entity movement;
* quest transitions;
* validation;
* identifiers;
* timestamps;
* event recording;
* rendering data retrieval.

### Retrieve context rather than loading the world

The world should eventually be able to become much larger than an LLM context window.

Agents should receive only the relevant working set, such as:

* player state;
* current location;
* nearby entities;
* relevant quests;
* relevant NPC memories;
* recent events;
* concise broader-world summaries.

### Prefer capability growth over premature generality

Do not attempt to model every possible game mechanic in advance.

Implement enough generic concepts to support the current world. Add new infrastructure when actual play reveals a capability the existing system cannot represent cleanly.

### Preserve causality

Changes should persist.

If six occupied beds become five, future interactions should discover five occupied beds unless another world event changes that number.

If a quest is completed, it should not silently reappear.

If a district develops into something new, its current state should become the basis of future narration.

---

# 2. Initial Technology Direction

Use common technologies with strong documentation and broad model familiarity.

## Backend

Use:

**Python + FastAPI**

The backend should provide:

* world queries;
* world mutations;
* context assembly;
* validation;
* persistence;
* event history;
* frontend API;
* health/status endpoints.

Keep the backend independent from Hermes internals wherever practical.

Hermes should interact with Mutable Realms through explicit project tools or commands rather than requiring Mutable Realms to become part of Hermes itself.

## Persistence

Use:

**SQLite**

SQLite should be the authoritative persistent world store.

Reasons:

* transactional;
* easy to inspect;
* single-project deployment;
* no additional database server;
* excellent tooling;
* easily queried by agents and humans;
* appropriate for a local single-container application.

Every database connection must enable foreign-key enforcement and a bounded busy timeout. Enable WAL mode during database initialization only after persistence and multi-connection tests confirm it behaves correctly on the mounted filesystem.

Initially run one Mutable Realms application worker. SQLite remains appropriate for this local single-user prototype, but unnecessary concurrent writer processes should not be introduced before their behavior and need are understood.

The live authoritative database must not be stored in the Git repository. The initial container deployment should use:

```text
/var/lib/mutable-realms/world.sqlite3
```

Configure this path through `MUTABLE_REALMS_DB_PATH` and bind-mount a dedicated host state directory at `/var/lib/mutable-realms`. Repository fixtures and examples may describe worlds, but mutable runtime state belongs in this separate state boundary. Backups, database sidecar files, and later world exports belong with this state boundary unless deliberately exported elsewhere.

Do not use JSON files as the long-term authoritative database.

JSON remains appropriate for:

* fixtures;
* schemas;
* configuration;
* import/export;
* debugging;
* examples.

## Frontend

Use:

**TypeScript + Vite + HTML/CSS**

Avoid a large frontend framework until the UI complexity demonstrates that one is useful.

Start with normal DOM APIs and small reusable TypeScript modules.

If component complexity later justifies a framework, evaluate that migration separately.

## World visualization

Use:

**SVG rendered inside the web interface**

SVG is well suited to simple world views because:

* locations can be represented by basic shapes;
* entities can have stable IDs;
* elements can be clickable;
* styling can be performed with CSS;
* rendering remains text-based and understandable to agents;
* sprites and richer assets can be introduced later.

The renderer should consume API data. It must not store authoritative world state in HTML or SVG.

---

# 3. Repository Structure

Create a clear separation between application code, world data, agent tooling, and tests.

A reasonable initial structure is:

```text
mutable-realms/
├── readme.md
├── pyproject.toml
├── uv.lock
├── package.json
├── package-lock.json
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── domain/
│   │   ├── services/
│   │   ├── persistence/
│   │   └── main.py
│   └── migrations/
├── frontend/
│   ├── src/
│   ├── public/
│   └── index.html
├── tools/
│   └── world/
├── tests/
│   ├── backend/
│   ├── integration/
│   └── fixtures/
└── docs/
    └── implementation-plan.md
```

Do not create directories merely to match this proposal if they have no current purpose. Keep the actual repository smaller until functionality needs them.

The authoritative repository path inside the container is:

```text
/workspace/mutable-realms
```

The corresponding host directory is bind-mounted into the container. Project code should use container paths while running inside the container and should not encode host-specific absolute paths.

Live world databases are deployment state rather than repository content. Do not place the authoritative database under `/workspace/mutable-realms`, even though that directory is persistent on the host. Keep fixtures under `tests/fixtures/` and use temporary databases for automated tests.

---

# 4. Container and Service Layout

Keep Mutable Realms, Hermes WebUI, Hermes Gateway, and the Mutable Realms web application inside the existing single container as requested.

Conceptually the container runs:

```text
Hermes WebUI
Hermes Gateway
Mutable Realms application server
```

Avoid introducing Docker-in-Docker, additional containers, PostgreSQL, Redis, message brokers, reverse proxies, or process-management platforms during the initial implementation.

The Mutable Realms application should listen on its own internal port.

Expose that port through Docker Compose for local browser access.

Development target:

```text
Browser
   |
   +---- Hermes WebUI
   |
   +---- Mutable Realms Web App
```

Production-style behavior inside the development container should eventually be:

```text
FastAPI
├── /api/...       application API
├── /health        health endpoint
└── /              built frontend assets
```

Vite's development server can be used while actively developing the frontend, but the normal deployed form should be a built static frontend served by the application server.

Do not use Vite's preview server as the permanent deployment server.

Keep startup commands explicit and ensure failure of the Mutable Realms service is visible rather than silently swallowed by background shell processes.

A later infrastructure task may improve service supervision if the existing container startup mechanism becomes unreliable.

The initial Mutable Realms server should use one application worker. Expose its host port only on `127.0.0.1` during local development. Separate liveness from readiness: liveness means the process can answer, while readiness means the configured database is reachable and its schema version is supported.

---

# 5. Phase 1 — Minimal Authoritative World Slice

Implement the smallest possible authoritative world before integrating an LLM. This phase must establish the infrastructure rules that make the stored world genuinely authoritative: versioned schema, constraints, validation, transactional application services, event recording, and persistence across application recreation.

The first database schema should model only the small set of general concepts required by the prototype, such as worlds, locations, stable entities, characters, current placement, scenario-specific state, and events. Ward-specific concepts such as beds and medical conditions may use focused relational tables without implying that every Mutable Realms world contains them.

Do not build a universal entity-component system at this stage. Prefer a straightforward relational schema with application-generated stable text IDs. Display names are mutable attributes and must not be used as identity.

Create migrations from the first schema. Application startup must apply pending migrations deterministically and fail visibly if migration or schema validation fails. Reapplying startup to an up-to-date database must be safe.

Every meaningful mutation must go through one authoritative application service layer shared by future HTTP, CLI, and Hermes interfaces. The first mutation must validate preconditions, enforce database and domain invariants, update normalized current state, increment the world's revision, and append an event in one transaction. If any part fails, none of the mutation may persist.

The first mutation interface must accept a caller-generated operation ID and enforce its uniqueness so a retry cannot apply the same action twice. It must also accept an expected world revision and reject stale requests. These guarantees belong in the first persistent slice, not only in later agent or HTTP integration.

Provide baseline world validation in this phase. At minimum, references must resolve, stable IDs must be unique, placement must be coherent, and scenario-specific occupancy constraints must be enforced. Later phases can expand validation as new capabilities are introduced.

### First proof scenario

Create one example world containing:

* one player;
* one location;
* six beds;
* six patients.

The location should represent a small ward. This is a compact integration fixture chosen because its state transition is visible and easy to verify; it is not the default shape of all future worlds.

At minimum, support persistent entities with stable IDs and enough relationships to answer:

* where is the player?
* which entities are in this location?
* which beds exist?
* which beds are occupied?
* who occupies each bed?
* what is each patient's current condition?

The fixture should use deterministic IDs so tests and debugging commands can address known entities without depending on generated display names.

### Treatment and discharge semantics

For this proof scenario, reducing six occupied beds to five is explicitly a compound domain transition rather than an implied consequence of changing a medical label. A successful `treat_and_discharge_patient` operation means:

1. the patient is verified to exist and occupy the specified bed;
2. the patient's condition becomes `recovered`;
3. the bed becomes unoccupied;
4. the recovered character remains in the world but is moved out of the ward's current contents and marked as discharged;
5. a meaningful event records the transition and affected entities;
6. the world revision increments;
7. all changes commit atomically.

Other worlds and future medical scenarios may separate treatment, recovery, movement, and discharge. This combined operation exists only to make the first persistent-causality test precise. The application should not delete the recovered character or encode healing as a universal reason for removing an entity from a location.

### Initial success condition

A deterministic application operation can treat and discharge one patient and persist the result.

Before:

```text
Ward: 6 occupied beds
```

After:

```text
Ward: 5 occupied beds
```

Closing all database connections and recreating the application must preserve the five-occupied-bed state, the recovered character, the event, and the incremented world revision.

This is the first important milestone.

---

# 6. Phase 2 — Read API and Visualization

Expose read-only application endpoints.

Initial API capabilities should include:

```text
GET current player
GET current location
GET location contents
GET entity details
GET recent world events
```

Exact routes can follow conventional REST naming and should be documented through FastAPI's generated OpenAPI schema.

Build a small browser interface displaying the ward.

Initial visualization can be extremely simple:

```text
WARD

[●] [●] [●]
[●] [●] [●]

6 patients
```

Represent beds and characters through SVG elements.

After a state mutation, refreshing the browser must show the new authoritative state.

Then add lightweight automatic refreshing or push updates only if useful. Polling is acceptable for the first prototype. Do not introduce WebSockets merely because they are available.

### Success condition

Database state changes independently of the frontend, and the frontend correctly renders those changes.

---

# 7. Phase 3 — Expand Controlled World Mutations

Expand the authoritative application service layer established in Phase 1 as actual scenarios require more operations.

Possible operations include:

```text
move_entity
update_condition
set_bed_occupant
add_item
remove_item
transfer_item
update_relationship
create_event
```

Implement only operations required by actual prototype scenarios. Prefer domain-level operations that complete a valid transition over exposing low-level setters that let a caller create partial or contradictory state. Low-level primitives may remain internal implementation details.

Each operation must:

1. validate input;
2. verify referenced entities;
3. enforce relevant invariants;
4. perform all related writes transactionally;
5. record a meaningful world event;
6. increment the world's monotonic revision;
7. return the resulting authoritative state.

Mutating interfaces must accept a caller-generated operation ID protected by a uniqueness constraint so retries do not apply the same action twice. They should also accept an expected world revision when the caller is acting on previously retrieved context. A revision mismatch must reject the mutation and require fresh context rather than applying a decision to stale state.

Do not allow the narration agent to construct arbitrary SQL.

Direct database inspection may remain available to the infrastructure specialist for debugging.

Ordinary world interaction should use controlled tools.

---

# 8. Phase 4 — Expand Event History

Expand the append-oriented event history introduced with the first mutation.

Examples:

```text
patient_treated_and_discharged
entity_moved
quest_completed
item_transferred
relationship_changed
location_changed
```

Events exist for:

* debugging;
* history;
* context generation;
* narrative continuity;
* auditing agent actions.

Events are not the sole source of truth.

The current normalized world state remains directly queryable.

Store enough information to understand what changed without duplicating the entire database on every action.

Meaningful operations should record:

```text
who caused the change
what changed
which entities were affected
when it occurred
optional narrative summary
operation ID
world revision produced by the change
```

---

# 9. Phase 5 — Context Builder

Create a deterministic context-building service.

Given the player and current location, it should assemble a compact structured representation containing only information likely to matter for the next interaction.

For example:

```text
PLAYER
Current location: ward

LOCATION
Ward
6 beds
5 occupied

NEARBY CHARACTERS
...

ACTIVE LOCAL QUESTS
...

RELEVANT MEMORIES
...

RECENT EVENTS
...
```

Prefer structured machine-readable output internally.

A human-readable representation may also be offered because it is useful for debugging prompts.

The context builder should have explicit limits.

Do not retrieve the complete world's history by default.

This service becomes one of the key boundaries between the persistent world and the narration agent.

---

# 10. Phase 6 — Hermes World Tools

Create a small agent-facing tool layer.

Hermes should be able to perform operations such as:

```text
world status
world context
world inspect <entity>
world move ...
world update ...
world events ...
world validate
```

The exact interface may be implemented as project scripts, CLI commands, Hermes skills/tools, or a small HTTP client depending on what integrates most cleanly with the installed Hermes version.

Prefer one authoritative application service layer underneath every interface.

For example:

```text
Hermes CLI/tool
       |
       v
Application service
       |
       v
SQLite
```

and:

```text
Browser API
       |
       v
Application service
       |
       v
SQLite
```

Do not independently implement world-changing logic in both the HTTP API and agent scripts.

---

# 11. Phase 7 — Narration Agent Prototype

Once deterministic world operations work reliably, integrate the narration profile.

For each player turn:

```text
1. Receive player action.
2. Retrieve current context.
3. Interpret the player's attempted action.
4. Decide plausible consequences.
5. Perform required world mutations through tools.
6. Read resulting authoritative state.
7. Produce narration consistent with the result.
8. Browser visualization reflects the updated state.
```

The narration agent must distinguish between:

```text
PLAYER INTENT
"I treat the patient and help arrange her discharge."

WORLD RESULT
"The treatment succeeds, and the recovered patient is discharged."

STATE CHANGE
patient.condition = recovered
patient.disposition = discharged
patient.location = outside ward
bed.occupant = null
```

Player statements are attempts or declarations of intent unless the scenario establishes that the player has authority to make them automatically true.

The narration agent must not claim state changes that it failed to persist.

---

# 12. Phase 8 — Expand Consistency Validation

Expand the baseline validation established in Phase 1 before increasing world complexity.

Validate invariants such as:

* IDs are unique;
* references resolve;
* an entity cannot occupy incompatible locations simultaneously;
* a bed cannot have multiple occupants;
* quantities cannot become invalid;
* completed quests do not remain available;
* relationships point to valid entities.

Provide:

```text
world validate
```

The infrastructure agent should be able to run this after migrations or suspicious world changes.

Where practical, reject invalid writes rather than attempting to repair them afterward. Validation added for a new capability should normally arrive with that capability rather than being postponed to this phase; this phase is a deliberate system-wide review before broader gameplay expansion.

---

# 13. Phase 9 — First Complete Gameplay Loop

Recreate the motivating ward scenario.

Initial state:

```text
6 occupied beds
```

Player tells the narrator:

```text
I treat the woman suffering from fever in the first bed.
```

The complete system should:

```text
retrieve ward state
→ identify the patient
→ interpret the action
→ determine the outcome
→ persist the recovery and discharge
→ clear the patient's occupancy and move her out of the ward
→ record the event
→ narrate the result
→ update the web view
```

The player then performs unrelated actions and later returns.

The narrator must discover that the ward contains five current patients and that the recovered character exists elsewhere, rather than generating six new patients from the generic concept of "a ward."

This is the primary proof of concept.

Do not expand scope substantially until this behavior is reliable.

---

# 14. Phase 10 — NPC Memory and Relationships

Once physical state is reliable, add persistent social state.

Separate structured facts from narrative memories.

Structured information may include:

```text
relationship score/category
faction
current disposition
known player identity
location
status
```

Narrative memory may include concise statements such as:

```text
The player stayed with Mara during her illness and successfully treated her fever.
```

Memories should reference entities and events where practical.

Do not store full chat transcripts as NPC memory.

Retrieve only memories relevant to the current interaction.

---

# 15. Phase 11 — Quests

Add quests after characters and locations are persistent.

Quest state should be explicit:

```text
available
active
completed
failed
cancelled
```

A quest board should query current quest state.

Completing a quest must therefore naturally remove it from the available board without relying on narration memory.

Quest objectives should reference world entities or conditions wherever practical.

This allows quests to reflect actual world changes instead of remaining detached story text.

---

# 16. Phase 12 — Mutable Locations

Introduce persistent higher-level location properties.

Examples:

```text
prosperity
safety
cleanliness
population
purpose
condition
display name
tags
```

Do not assume every world needs these exact properties.

Use them only when a scenario requires them.

The important capability is that location identity can evolve.

Example:

```text
The Slums
   ↓
Improving Riverside
   ↓
Riverside Quarter
```

Future context should describe the current Riverside Quarter while retaining enough historical information for characters to remember what it used to be.

---

# 17. Phase 13 — Multiple Locations and Travel

Expand from one scene into a small connected world.

Introduce explicit location relationships such as:

```text
ward
  ↔ main street
      ↔ guild hall
      ↔ market
      ↔ riverside
```

Travel should update authoritative player location.

Context retrieval should then naturally change its working set.

This phase demonstrates that the system can stream relevant world context rather than continually accumulating prompt content.

---

# 18. Phase 14 — Richer Visualization

Only after state and narration work reliably should visual complexity grow.

Potential additions:

* sprites;
* map icons;
* character portraits;
* tooltips;
* location labels;
* clickable objects;
* camera movement;
* scene transitions;
* small animations;
* contextual panels;
* quest board UI;
* character information;
* inventory views.

Maintain one rule:

**visual complexity must not increase world-state complexity unnecessarily.**

A sprite remains a presentation of an entity rather than becoming a second definition of that entity.

---

# 19. Phase 15 — Direct Player Interface

Initially, using Hermes WebUI for narration and a second browser tab for visualization is acceptable and desirable.

It keeps the experiment simple.

After the gameplay loop proves useful, evaluate integrating player input directly into the Mutable Realms frontend.

Possible final interaction:

```text
┌─────────────────────────────────────┐
│              WORLD                  │
│                                     │
│        visual representation        │
│                                     │
├─────────────────────────────────────┤
│ narration                           │
│                                     │
├─────────────────────────────────────┤
│ What do you do?                     │
│ >                                   │
└─────────────────────────────────────┘
```

At that point the custom frontend can communicate with Hermes or an appropriate agent API behind the scenes.

Do not make this integration a prerequisite for proving the world model.

---

# 20. Phase 16 — Infrastructure Extension Requests

Later, allow the narration/world agent to recognize when player activity requires a capability that does not exist.

Example:

```text
Player:
I deploy automated probes to map nearby star systems.
```

Existing infrastructure may have no concept of:

```text
star systems
probes
survey progress
```

The narration agent should not casually redesign the database.

Instead, it may produce a structured capability request for the infrastructure specialist.

Conceptually:

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

The infrastructure specialist can then implement a general capability.

This is the point where Mutable Realms begins moving toward the larger idea of a game whose mechanics can evolve in response to play.

Do not implement autonomous schema evolution during the initial project.

---

# 21. Testing Strategy

Treat persistent state as game logic.

Use automated tests from the beginning.

Prioritize:

### Unit tests

Test domain rules and validation.

### Persistence tests

Test reads, writes, transactions, constraints, and migrations.

### API tests

Test world queries and mutations through supported interfaces.

### Integration tests

Test sequences such as:

```text
create patient
→ assign bed
→ treat and discharge patient transactionally
→ close every database connection
→ recreate the application against the same database file
→ verify the patient remains recovered and discharged
→ verify the bed remains empty
→ verify the event and world revision remain present
```

Also test migration idempotency, foreign-key enforcement on every connection, constraint failures, transaction rollback, stale revision rejection, and duplicate operation-ID handling. Persistence tests must use temporary database files rather than the live world database.

### Regression fixtures

Keep small known worlds that reproduce important bugs.

The initial ward world should become a permanent integration fixture.

Avoid tests that depend on nondeterministic LLM output unless specifically testing model integration.

The deterministic world layer should be testable without Hermes or an external model.

---

# 22. Database Migration Standard

Schema changes must be versioned from the first schema, before persistent worlds become valuable.

Initially use a lightweight migration system appropriate to the selected Python persistence approach. Versioned SQL files and a schema-version table are sufficient unless demonstrated complexity justifies a larger migration framework.

Never depend on developers manually editing production world databases.

Every migration should preserve existing world state whenever practical.

Before risky migration work:

```text
backup
→ migrate
→ validate
```

Database backups and world export/import should become supported operations before worlds become valuable.

The initial backup boundary is the configured state directory containing `world.sqlite3` and any SQLite WAL/SHM sidecar files. Backup procedures must use a SQLite-safe snapshot method rather than copying only the main database file while writes may be active. After restoration or migration, run world validation before resuming mutations.

---

# 23. Observability

Keep diagnostics simple but useful.

Application logs should clearly identify:

```text
startup
database migrations
world mutations
validation failures
API errors
agent operation failures
```

Avoid logging huge prompts or complete world state by default.

Provide separate liveness and readiness endpoints. Liveness verifies that the process can answer; readiness verifies basic database access and a supported schema version. Full world validation should remain a separate diagnostic because it may be more expensive and represents a different condition.

Eventually distinguish:

```text
application operational
world valid
agent reachable
```

These are separate conditions.

---

# 24. Security Boundaries

The infrastructure agent may retain broad development permissions.

The narration/world agent should eventually operate through narrower tools.

The narration agent should not require unrestricted shell access for ordinary play.

Treat generated content and player input as untrusted data.

Do not allow narrative text to become executable code merely because it appears in world state.

Keep secrets outside:

```text
Git
world data
prompts
event history
frontend bundles
```

Bind application services to localhost-facing Docker ports during local development unless wider network access is deliberately requested.

---

# 25. Avoid Premature Systems

Do not initially add:

```text
PostgreSQL
Redis
message queues
microservices
Kubernetes
ECS frameworks
complex plugin architectures
generic scripting languages
multiplayer synchronization
procedural generation frameworks
vector databases
embeddings
WebSockets
full-text search systems
large frontend frameworks
```

Any of these may eventually become justified.

None should be introduced because a hypothetical future version might need them.

Prefer the smallest architecture that supports persistent causality correctly.

---

# 26. First Implementation Milestones

Work toward these milestones in order.

### Milestone A — Authoritative Persistent State

A versioned SQLite database contains a deterministic example ward with six occupied beds. The live database resides in the dedicated deployment state directory rather than the Git repository.

One tested application service performs an invariant-preserving, transactional treatment-and-discharge operation. It recovers and relocates the character without deleting them, clears the bed, records an event, and increments the world revision.

The operation is idempotent when retried with the same operation ID and rejects stale expected revisions. Closing all connections and recreating the application preserves five occupied beds and passes world validation.

### Milestone B — Visualization

The browser renders six occupied beds from API data.

Changing the database through the supported application operation causes the browser to render five.

### Milestone C — Agent Tools

Hermes can inspect the ward and perform the same mutation using a controlled Mutable Realms tool.

### Milestone D — Narrated Turn

A player tells Hermes:

```text
I treat the patient in the first bed and help arrange her discharge.
```

Hermes retrieves state, resolves the action, mutates the world, and narrates a result consistent with the stored state.

### Milestone E — Persistent Return

The player leaves the ward, performs another interaction, and returns.

The ward still contains five current patients, and the discharged character still exists elsewhere in the world.

### Milestone F — Social Consequences

The recovered patient exists elsewhere and remembers being helped.

### Milestone G — Quest Consequences

A persistent quest can be accepted and completed, after which it disappears from the quest board.

### Milestone H — Location Transformation

Repeated player actions can cause a location's persistent identity or condition to change, and future narration reflects the new state.

At Milestone H, the core Mutable Realms concept has been demonstrated.

---

# 27. Definition of the First Successful Prototype

The prototype is successful when Mutable Realms demonstrates all of the following without manually editing world files during play:

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

The important demonstration is not graphical quality.

It is not the number of locations.

It is not the amount of generated text.

It is this:

> The player changes something through narrative interaction, the world actually changes, and the system continues reasoning from that changed reality later.

Once this works reliably, expand the world and mechanics gradually rather than increasing scope before the persistent-causality loop is proven.

