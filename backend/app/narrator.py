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
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

# (world_id, player_id, player_action) -> player-facing narration text.
Narrator = Callable[[str, str, str], str]

DEFAULT_PROFILE = os.environ.get(
    "MUTABLE_REALMS_NARRATOR_PROFILE", "mutable-realms-narration"
)
NARRATOR_TIMEOUT_SECONDS = float(os.environ.get("MUTABLE_REALMS_NARRATOR_TIMEOUT", "120"))


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
        "operation if the action warrants one, and reply with the player-facing "
        "narration only. Never claim a change that did not commit."
    )


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
        command = ["hermes", "--profile", self.profile, "chat", "-q", prompt]
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
        narration = completed.stdout.strip()
        if not narration:
            raise NarratorError("narration agent returned an empty reply")
        return narration
