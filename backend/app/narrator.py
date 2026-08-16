"""Narrator relay for the direct player interface.

The narration agent is a separate Hermes profile bound to one world and one
player via MCP environment variables (``MUTABLE_REALMS_DB_PATH``,
``MUTABLE_REALMS_WORLD_ID``, ``MUTABLE_REALMS_PLAYER_ID``). The turn
endpoint relays the player's free-form action to that agent and returns its
narration; the agent itself performs at most one supported mutation through
its bound MCP tools, so world changes commit through the same deterministic
machinery as every other narrated turn.

Tests inject a fake narrator instead of invoking the CLI, so the relay
itself is fully deterministic; only the default production narrator shells
out to ``hermes``.

The Hermes CLI is invoked in quiet mode (``-Q``) so banner, spinner, and
tool previews are suppressed, but the rendered reasoning box and the
model's own meta-commentary still need deterministic cleanup so the page
receives only player-facing narration.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from typing import Any

# (world_id, player_id, player_action, context) -> player-facing narration text.
# ``context`` is the selected world's authoritative WorldContext dict (or None
# when the world has no player yet).
Narrator = Callable[[str, str, str, dict[str, Any] | None], str]

DEFAULT_PROFILE = os.environ.get(
    "MUTABLE_REALMS_NARRATOR_PROFILE", "mutable-realms-narration"
)
NARRATOR_TIMEOUT_SECONDS = float(os.environ.get("MUTABLE_REALMS_NARRATOR_TIMEOUT", "120"))

# The CLI renders the model's reasoning inside a box drawn with box-drawing
# characters (CRLF line endings); the reply itself uses plain line endings.
_REASONING_BOX_RE = re.compile(r"(?ms)^┌.*?┘\s*")

# Model meta-commentary that is not player-facing narration. These are
# stripped deterministically as a safety net; the relay prompt asks the
# agent not to produce them at all.
_LEADING_META_RE = re.compile(r"^(?:Decision[:\- ]).*?(?=\n\n|\Z)", re.DOTALL)
_TRAILING_META_RE = re.compile(
    r"(?:\n\n|\A)(?:No change was persisted|Refresh the page|World revision).*?\Z",
    re.DOTALL,
)


class NarratorError(RuntimeError):
    """Raised when the narration agent cannot produce a reply."""


def _format_context_block(context: dict[str, Any]) -> str:
    """Render a compact, bounded context snapshot for the narration prompt.

    The snapshot is derived from the selected world's authoritative
    WorldContext so the agent narrates the world the page chose, not whatever
    world its profile happens to be bound to.
    """
    lines: list[str] = []
    world = context.get("world", {})
    lines.append(
        f"World: {world.get('id', '?')} — {world.get('name', '?')} "
        f"(revision {world.get('revision', '?')})"
    )
    description = world.get("description")
    if description:
        lines.append(f"World description: {description}")
    player = context.get("player", {})
    location = context.get("current_location", {})
    lines.append(f"Player: {player.get('name', '?')} ({player.get('id', '?')})")
    if location:
        location_name = location.get("name", "?")
        location_description = location.get("description")
        if location_description:
            lines.append(f"You are at: {location_name} — {location_description}")
        else:
            lines.append(f"You are at: {location_name}")
        entities = location.get("entities", [])
        if entities:
            here = ", ".join(
                f"{entity.get('name', '?')} ({entity.get('id', '?')})"
                for entity in entities
            )
            lines.append(f"Here: {here}")
    elements = context.get("world_elements", [])
    if elements:
        lines.append("Story elements:")
        for element in elements:
            lines.append(
                f"  {element.get('element_type', '?')}: {element.get('content', '')}"
            )
    events = context.get("recent_events", [])
    if events:
        lines.append("Recent events:")
        for event in events[:5]:
            lines.append(f"  - {event.get('event_type', '?')}: {event.get('summary', '')}")
    return "\n".join(lines)


def build_narration_prompt(
    world_id: str,
    player_id: str,
    player_action: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Compose the player-turn prompt for the bound narration agent.

    When ``context`` is provided it is embedded as an authoritative snapshot of
    the selected world, so the agent narrates that world even if its profile is
    configured for another one.
    """
    prompt = (
        "You are the Mutable Realms narration agent, reached through the direct "
        "player interface.\n"
        f"World: {world_id}\n"
        f"Player: {player_id}\n\n"
    )
    if context is not None:
        prompt += "Current world state (authoritative snapshot for this turn):\n"
        prompt += _format_context_block(context)
        prompt += "\n\n"
    prompt += (
        "The player's action is:\n"
        f"{player_action}\n\n"
        "Follow your narration contract exactly: read the world state first "
        "(world_status and world_context), perform at most one supported "
        "operation if the action warrants one.\n\n"
        "World tools accept world_id and player_id. Always pass "
        f"world_id={world_id} and use the player entity id {player_id} for "
        "actor_entity_id when calling them — ignore any world binding in your "
        "profile configuration; this world is authoritative for this turn.\n\n"
        "Your entire reply must be the player-facing narration itself, written "
        "directly to the player in the second person and present tense. Do not "
        "include decision summaries, tool reports, status lines, or any text "
        "outside the narration. Never mention persistence, page refreshes, "
        "world revisions, or whether the world changed. If nothing changed, "
        "still narrate the moment in-world."
    )
    return prompt


def clean_narration(output: str) -> str:
    """Reduce raw CLI output to player-facing narration.

    Removes the rendered reasoning box and leading/trailing model
    meta-commentary (decision summaries, persistence status lines). Text that
    is already clean narration passes through unchanged.
    """
    text = _REASONING_BOX_RE.sub("", output)
    text = _LEADING_META_RE.sub("", text)
    text = _TRAILING_META_RE.sub("", text)
    return text.strip()


class HermesNarrator:
    """Run the bound narration agent through the Hermes CLI."""

    def __init__(
        self,
        profile: str = DEFAULT_PROFILE,
        timeout: float = NARRATOR_TIMEOUT_SECONDS,
    ) -> None:
        self.profile = profile
        self.timeout = timeout

    def __call__(
        self,
        world_id: str,
        player_id: str,
        player_action: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        prompt = build_narration_prompt(world_id, player_id, player_action, context)
        command = [
            "hermes",
            "--profile",
            self.profile,
            "chat",
            "-Q",
            "-q",
            prompt,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise NarratorError(
                f"narration agent timed out after {self.timeout:.0f}s"
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise NarratorError(f"narration agent failed: {detail[:500]}")
        narration = clean_narration(completed.stdout)
        if not narration:
            raise NarratorError("narration agent returned an empty reply")
        return narration
