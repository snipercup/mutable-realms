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

# (world_id, player_id, player_action) -> player-facing narration text.
Narrator = Callable[[str, str, str], str]

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


def build_narration_prompt(world_id: str, player_id: str, player_action: str) -> str:
    """Compose the player-turn prompt for the bound narration agent."""
    return (
        "You are the Mutable Realms narration agent, reached through the direct "
        "player interface.\n"
        f"World: {world_id}\n"
        f"Player: {player_id}\n\n"
        "The player's action is:\n"
        f"{player_action}\n\n"
        "Follow your narration contract exactly: read the world state first "
        "(world_status and world_context), perform at most one supported "
        "operation if the action warrants one.\n\n"
        "Your entire reply must be the player-facing narration itself, written "
        "directly to the player in the second person and present tense. Do not "
        "include decision summaries, tool reports, status lines, or any text "
        "outside the narration. Never mention persistence, page refreshes, "
        "world revisions, or whether the world changed. If nothing changed, "
        "still narrate the moment in-world."
    )


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

    def __call__(self, world_id: str, player_id: str, player_action: str) -> str:
        prompt = build_narration_prompt(world_id, player_id, player_action)
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
