# Mutable Realms

Mutable Realms is an experimental AI-driven persistent world in which an AI agent narrates a story while also changing the world in which that story takes place.

The project explores an alternative to conventional AI storytelling. Instead of relying primarily on conversation history and memories to represent what has happened, Mutable Realms maintains an explicit world state that the AI can inspect and modify. The narrated story and visual representation of the world are grounded in that persistent state.

The goal is to create open-ended experiences where actions can leave lasting, visible consequences.

## The Idea

In a conventional AI storytelling game, a player might enter a hospital ward, find six patients, and heal one of them. The story can remember that the patient was healed, but the underlying concept of the ward may remain unchanged. Returning later can cause the AI to generate more patients simply because it still understands the location as a hospital ward.

Mutable Realms instead represents relevant facts as persistent world state.

After healing one patient:

* the ward contains five patients rather than six;
* the healed character can leave or move elsewhere;
* that character can remember the player's actions;
* related quests can change or disappear;
* the visual representation of the ward can reflect the newly empty bed.

The AI does not have to reconstruct these consequences from narrative memory. It can inspect what is currently true about the world.

## A Mutable World

Persistence applies to more than individual objects.

A poor district could gradually improve until it is no longer considered a slum. An abandoned waterfront could become a trading port. A temporary medical ward could eventually become unnecessary or develop into a permanent clinic.

The world should be able to change its identity as a consequence of what happens within it.

Mutable Realms therefore treats the world as something that can be altered rather than as a static backdrop for generated stories.

## Player Interaction

The primary interaction can remain as flexible as a text adventure.

A player describes an action:

> I spend the afternoon treating the woman with a fever in the first bed.

The AI interprets the action using the current scene, relevant world state, character information, and recent events. It narrates what happens and applies the resulting changes to the persistent world.

The world state then becomes the starting point for future interactions.

This keeps much of the freedom of open-ended AI storytelling without requiring every possible player action to be implemented as a traditional game mechanic.

## Persistent Causality

Mutable Realms distinguishes between three related concepts:

1. **World state** — what is currently true.
2. **Narration** — how events and actions are described.
3. **Visualization** — how the current world is presented to the player.

World state is authoritative.

Narration and visualization should reflect that state rather than independently defining it.

This is intended to reduce common problems in generative storytelling such as forgotten changes, resurrected quests, duplicated characters, replenished problems, and locations that repeatedly return to their original description.

## World Visualization

The world can be represented visually without requiring a conventional game engine or detailed graphics.

A location might be displayed using simple web technologies, markup, shapes, icons, sprites, or other lightweight representations. A street could consist of roads, buildings, characters, and labels. A hospital could show beds and their occupants. A quest board could display the quests that currently exist.

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

## Agents and Tools

AI agents act as both storytellers and operators of the world.

Rather than requiring the language model to perform every operation through prose, agents can use deterministic tools and scripts for repeated or precise work such as:

* querying locations and characters;
* moving entities;
* transferring items;
* updating quests;
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

