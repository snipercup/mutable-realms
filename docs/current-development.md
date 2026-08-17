# Current Development

Mutable Realms develops one idea at a time. This document tracks the single active idea and the recently closed trail. It is not a backlog: ideas that are interesting but not being worked on belong in the [readme.md](../readme.md) *Roadmap*; finished ideas are recorded in [maintenance-guide.md](maintenance-guide.md) under *Development history*.

## Active idea

### Nested locations and scoped world maps — scoped

**Goal:** replace the assumption that every location belongs on one world-wide map with a flexible containment hierarchy and scope-specific derived maps. The common baseline is world → kingdom → province → city → district → street → enterable site/interior, while the persistence model must also support differently themed hierarchies such as a school campus without encoding fantasy geography as a schema invariant.

**Baseline experience:**
- The default play-map scope is the street containing the player. A street may expose up to roughly 100 enterable child locations such as houses, warehouses, or inns.
- Enterable sites normally have few or no children; floors or similarly useful subdivisions are allowed but not required.
- A district contains streets and street-like areas such as a harbor or palace grounds. A city normally contains no more than about ten districts.
- A province contains cities and broad natural areas such as forests or mountain ranges. Selected smaller landmarks—such as a mine, major road, or sinkhole—may also be promoted onto the province map when useful.
- Kingdom and world scopes provide the larger baseline. These names and capacities are authoring guidance, not fixed database depth or mandatory kinds.

**Recommended model:**
1. **Containment is separate from travel** — use an additive `location_containment` relation rather than rebuilding the heavily referenced `locations` table. One child has at most one parent; both must belong to the same world; self-parenting and cycles are invalid. Parentage answers “what contains this?” and never implies traversal. Treat the existing `worlds` row as the virtual top scope rather than creating a duplicate “world location”; locations absent from the containment relation are its roots.
2. **Existing links remain physical movement edges** — preserve `location_links` as explicit, undirected adjacency for ordinary movement. Entering a house requires a street↔house link; sibling houses are not connected merely because they share a street. Existing flat worlds remain valid as root locations with their current links. Reparenting does not silently add, remove, or rewrite links.
3. **Maps are scoped derived reads** — define a visible graph as the scope node plus its direct children, not merely the children. The response should include breadcrumb ancestors, links whose endpoints are both visible, external exits as a separate boundary list, the player’s exact location, the visible node containing the player when the exact location is deeper, stable child ordering, totals, and overflow metadata. Presentation remains derived from SQLite.
4. **Street is the baseline preference, not a universal rule** — use explicit map-scope metadata rather than inferring behavior from `kind`. The baseline marks streets; a school scenario can mark its grounds or building instead. Play chooses the nearest preferred self-or-ancestor and uses a deterministic root/flat-world fallback. The player may zoom out to ancestors or into child scopes without changing authoritative position.
5. **Cross-scale landmarks are explicit** — do not infer province visibility from names or kinds. Use an explicit scope-marker/promotion relation so a deeply nested mine or road can appear on a province map without acquiring a second parent or duplicating the location.
6. **Detailed travel and fast travel are different operations** — map zoom never moves the player. Detailed travel continues to follow explicit location links from the player’s exact location. Future fast travel should use explicit transit/route data and validated endpoints; it must not treat shared parents or visibility on the same province map as adjacency.
7. **Keep the hierarchy theme-neutral** — kinds such as `province`, `street`, `building`, or `floor` are descriptive values used by authoring and presentation. Core containment and map queries should not require a fixed list or fixed depth. Star-system semantics and multiple-parent containment are not baseline requirements for this slice.
8. **Design for controlled dynamic expansion** — a later capability should let the narrator propose new neighboring or child locations when play reaches an expandable boundary. The narrator must not write storage directly: it supplies structured location, containment, and connection proposals to a named, revision-aware, idempotent operation that validates world ownership, limits, cycles, duplicate identity, and physically coherent links before committing. Generated locations then become ordinary authoritative state and must not be regenerated or silently rewritten on later visits.

**First implementation slice:**
1. Add compatible location hierarchy metadata, indexes, same-world parent enforcement, and cycle validation through a new migration.
2. Add deterministic hierarchy reads: ancestors/breadcrumbs, direct children, bounded descendants, preferred-scope selection, and a scoped-map read model. Keep the current map endpoint compatible initially: absent an explicit scope, legacy flat worlds return all roots—which are all their locations—and their existing links.
3. Extend authoritative context only with the current location’s containment breadcrumb and preferred scope identity. Continue exposing exact movement neighbors; do not inject the scoped map or up to 100 street children into the narrator prompt.
4. Change the map endpoint and frontend to navigate scopes while preserving the player’s exact-location highlight and existing flat-world behavior.
5. Preserve movement semantics in the first slice. Add no inferred parent/child movement and no fast-travel mutation until route semantics are separately scoped.
6. Add administrative location hierarchy editing only through validated operations; reject cross-world parents, self-parenting, cycles, and unsafe removal/reparenting.

**Limits and non-goals for the first slice:**
- The numerical limits (about 100 street children and about ten city districts) are guidance and response/rendering bounds, not universal schema constraints.
- No procedural kingdom generation, automatic road generation, narrator-driven location creation, travel-time simulation, locked routes, multi-parent places, portals, orbital mechanics, or generalized star-system model. The hierarchy should make later lazy expansion possible, but generation and its mutation contract are a separate slice.
- No automatic aggregation of all descendant entities or links onto every ancestor map.
- No claim that a higher-level map selection moves the player; fast travel remains a later explicit capability.
- The existing circular SVG is not expected to remain legible at 100 nodes. The scoped UI will need bounded rendering plus search/list or clustering rather than drawing every node identically.

**Key decisions still to make:**
- Exact descriptive location metadata: keep `kind` free-form initially, avoid a generic numeric `scale` until it has a concrete invariant, and define the minimal explicit preferred/map-capable scope flags.
- Whether scope-marker promotion belongs in the first migration or follows after basic containment works.
- Scoped-map response bound, stable ordering, search/list overflow behavior, and how graph pagination avoids displaying incomplete edges for streets near 100 children.
- How authoring creates/reparents locations. Reparenting should preserve links but report surprising cross-scope edges; parent deletion should default to `RESTRICT`, while recursive subtree removal requires a separate operation with explicit entity/link handling.
- The later fast-travel contract: route entities versus enriched links, eligibility/discovery rules, time/cost, and whether one fast-travel action records intermediate traversal.
- Whether entering/leaving containers needs explicit gateway metadata beyond ordinary links after real scenarios expose a limitation.
- The later dynamic-expansion contract: which locations are expandable; whether generation is triggered by exploration, explicit player intent, or an administrative action; per-scope budgets; duplicate detection; approval policy; and whether one operation may atomically create a small connected batch rather than one location at a time.

**Opportunities:** containment makes narrator retrieval smaller and more relevant; scope maps can support breadcrumbs, local discovery, district/province overview, and future route planning; explicit landmark promotion permits useful mixed-scale maps without corrupting physical containment; compatibility allows existing flat worlds to migrate without synthetic geography. Later controlled, lazy narrator expansion can grow only the neighborhood or child scope reached by play, avoiding the cost and inconsistency risk of generating an entire kingdom in advance.

**Primary pitfalls:** conflating containment with adjacency; letting zoom or overview links bypass movement rules; failing to enforce same-world containment through composite keys or equivalent validation; relying on UI-only cycle checks; highlighting only the exact location when the player is deeper than the visible scope; loading hundreds of descendants into prompts or SVG; hard-coding one genre’s scale vocabulary; duplicating locations to show them at multiple scales; fragmenting graph edges through naive pagination; deleting/reparenting subtrees without clear link/entity consequences; and allowing narrator expansion to create duplicate, contradictory, disconnected, unlimited, or non-idempotent geography.

**Verification plan:** migrate existing flat fixtures unchanged; build a representative hierarchy with world/kingdom/province/city/district/street/building/floor plus a promoted province landmark; verify breadcrumbs, default street scope, bounded child reads, scoped links, exact player location, and flat-world compatibility; verify cross-world parents and cycles fail; verify sibling containment does not permit movement without a link; verify zooming scopes never changes player state; run the full suite, lint, frontend build, temporary HTTP/UI checks, and SQLite readback.

**Suggested sequencing:** hierarchy invariants and compatibility → hierarchy queries → scoped context/map contract → scope navigation UI → administrative hierarchy operations → separately scope landmark promotion and fast travel after the baseline is exercised → later add controlled narrator-driven lazy expansion using the stable hierarchy and link contracts.

**Commit:** documentation scope only — suggested `Register nested locations and scoped maps`.

## Recently completed

| Idea | Completed | Commit |
| --- | --- | --- |
| Scenario authoring and world management (scenario CRUD + elements, world instancing, world update/elements/remove) | 2026-08-08 | on main via `scenario-authoring` · `world-instancing` · `world-management` |
| World management interface (play ⇄ manage view, scenario/world CRUD UI, instancing, `#manage` deep link) | 2026-08-10 | on main via `world-management-interface` |
| Player provisioning (create a player + starting location so instanced worlds are playable; play view empty state) | 2026-08-10 | on main via `player-provisioning` |
| Reusable player characters and world-specific instances (character CRUD, selection, copied world instances) | 2026-08-16 | on main via `reusable-player-characters` |
| Narrator-driven world start (structured opening, atomic character/location instancing, polling/error hardening) | 2026-08-16 | `9b00c16` |

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
