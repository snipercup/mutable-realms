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

## Features

* **Authoritative world state** — a versioned SQLite database holds worlds, locations, entities, placement, operations, and events; every meaningful change is an atomic, idempotent, revision-checked operation.
* **AI narration with real consequences** — a Hermes narration agent reads the world, interprets free-form player actions, applies at most one supported operation per turn, and narrates only what actually committed.
* **Direct player interface** — the web page shows the world map, current location, entities, and persistent events, with a "What do you do?" input that relays actions to the narration agent.
* **Open-ended scenarios** — the core is scenario-neutral; the ward, harbor town, or a future starship are optional capabilities, not built-in game types.
* **Growing capabilities** — when play demands something the world cannot yet persist, infrastructure can evolve one deliberate slice at a time instead of predicting every mechanic in advance.

## Requirements

* **Hermes Agent** — drives the narration agent as a dedicated profile bound to one world and one player (see [Interfaces and Tools](docs/interfaces-and-tools.md) for setup). Reading the world in the browser does not require Hermes.
* **Python 3.12+ with `uv`** — backend and tests.
* **Node.js 22 with npm** — frontend build and project command entry points.
* **SQLite** — bundled with Python; the `sqlite3` CLI is convenient but optional.

## Quick Start

```sh
uv sync --frozen
npm ci
npm run migrate      # apply schema migrations
npm run seed         # create the deterministic ward and town worlds
npm run frontend-build
npm run serve        # http://localhost:8790/
```

Open the page, select a world, and type an action in the "What do you do?" input. The narration agent reads the authoritative state, performs at most one supported operation if the action warrants one, and narrates the result; the map, entities, and events refresh from the committed revision.

## Project Layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI application, world services, migrations, MCP server, CLI. |
| `frontend/` | TypeScript/Vite browser interface (source in `frontend/src/`). |
| `tests/` | Backend test suite. |
| `docs/` | Guides below. |

## Documentation

* [docs/current-development.md](docs/current-development.md) — the active development idea and its state.
* [docs/maintenance-guide.md](docs/maintenance-guide.md) — durable development guidance: design rules, how to add a capability, operations, deferred work.
* [docs/interfaces-and-tools.md](docs/interfaces-and-tools.md) — commands, HTTP API, MCP tools, environment variables, Hermes narration setup.
* [docs/narration-agent-contract.md](docs/narration-agent-contract.md) — the narration agent's behavioral contract.

## Project Goals

Mutable Realms explores whether modern AI agents can support a world that is:

* open-ended without being purely ephemeral;
* persistent without requiring every interaction to be predefined;
* visually understandable without requiring complex graphics;
* capable of remembering consequences through state rather than narration alone;
* extensible as new scenarios require new capabilities;
* and simple enough for both humans and AI agents to understand and modify.

The project is experimental. Its purpose is not to generate an infinite quantity of interchangeable content, but to investigate whether AI can help maintain a world where player actions meaningfully change what exists and what can happen next.
