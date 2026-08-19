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

import json
import logging
import math
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# (world_id, player_id, player_action, context) -> player-facing narration text.
# ``context`` is the selected world's authoritative WorldContext dict (or None
# when the world has no player yet).
Narrator = Callable[[str, str, str, dict[str, Any] | None], str]


@dataclass(frozen=True)
class NarratorStartLocation:
    """One bounded authoritative location proposed for world start."""

    name: str
    description: str | None
    parent_name: str | None
    link_to_start: bool
    geography_role: str = "local"
    direction: str | None = None
    range_band: str | None = None


@dataclass(frozen=True)
class NarratorStartResult:
    """Validated information required to create a world-specific start."""

    location_name: str
    location_description: str | None
    narration: str
    locations: tuple[NarratorStartLocation, ...] = ()

    @property
    def start_location_name(self) -> str:
        return self.location_name


StartNarrator = Callable[[str, dict[str, Any], dict[str, Any]], NarratorStartResult]

_START_GEOGRAPHY_ROLES = {"local", "boundary", "route"}
_START_DIRECTIONS = {
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
}
_START_RANGE_BANDS = {"short", "mid", "long"}
_MAX_START_LOCATIONS = 16
_MIN_MAIN_STREET_CHILDREN = 10

_DEFAULT_NARRATOR_TIMEOUT_SECONDS = 120.0
_DEFAULT_START_NARRATOR_TIMEOUT_SECONDS = 240.0
_MIN_NARRATOR_TIMEOUT_SECONDS = 5.0
_MAX_NARRATOR_TIMEOUT_SECONDS = 300.0


def _bounded_timeout(environment_name: str, default: float) -> float:
    raw_value = os.environ.get(environment_name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return min(max(value, _MIN_NARRATOR_TIMEOUT_SECONDS), _MAX_NARRATOR_TIMEOUT_SECONDS)


DEFAULT_PROFILE = os.environ.get("MUTABLE_REALMS_NARRATOR_PROFILE", "mutable-realms-narration")
NARRATOR_TIMEOUT_SECONDS = _bounded_timeout(
    "MUTABLE_REALMS_NARRATOR_TIMEOUT", _DEFAULT_NARRATOR_TIMEOUT_SECONDS
)
START_NARRATOR_TIMEOUT_SECONDS = _bounded_timeout(
    "MUTABLE_REALMS_START_NARRATOR_TIMEOUT", _DEFAULT_START_NARRATOR_TIMEOUT_SECONDS
)
LOGGER = logging.getLogger(__name__)

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

    def __init__(self, message: str, *, category: str = "narrator_error") -> None:
        super().__init__(message)
        self.category = category


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
                f"{entity.get('name', '?')} ({entity.get('id', '?')})" for entity in entities
            )
            lines.append(f"Here: {here}")
    elements = context.get("world_elements", [])
    if elements:
        lines.append("Story elements:")
        for element in elements:
            lines.append(f"  {element.get('element_type', '?')}: {element.get('content', '')}")
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


def build_world_start_prompt(
    world_id: str, world: dict[str, Any], character: dict[str, Any]
) -> str:
    """Compose the strict structured prompt used before a player exists."""
    return (
        "You are starting a new Mutable Realms world. The supplied world and "
        "character data are authoritative. Infer the player's physical starting "
        "scale from the opening scene: a street-level approach for buildings, "
        "street-level for a mall or other urban opening, and a city or province "
        "scale for wilderness openings. Then choose a small, grounded set of "
        "locations that gives the player meaningful nearby choices; do not invent "
        "a kingdom-wide map. The bounded initial layout is required to contain "
        "3 to 16 locations: the selected start location, at least one child "
        "location whose parent_name is the start, and at least one sibling "
        "location with parent_name null. Siblings are nearby same-scale places "
        "such as another road, plaza, beach, or district; they are not automatic "
        "movement links. For street-level urban openings such as Main Street, "
        "include at least 10 direct child locations beneath the street so the "
        "local map represents a meaningful block of places; keep the complete "
        "layout within the 16-location bound. Other opening scales may use fewer "
        "locations when appropriate. Return ONLY valid JSON with exactly these keys: "
        "start_location_name (non-empty string), locations (array of 3 to 16 "
        "objects with exactly these fields: name, description (the location description), "
        "parent_name (null unless that parent is also listed), link_to_start, "
        "geography_role (local, boundary, or route), direction (a cardinal or "
        "intercardinal direction, or null), and range_band (short, mid, long, or "
        "null); do not use location_description inside a location "
        "object. The top-level legacy field is location_description only when locations "
        "is omitted. The top-level locations array and narration are required. "
        "link_to_start explicitly requests a local physical movement link. The "
        "location belongs to this world, not to the reusable character definition. "
        "For Aerthalon, when the opening scene places the player on the way to "
        "or in front of the Adventurer's Guild in Elaris, use Main Street as "
        "the start location and place the Adventurer's Guild beneath it.\n\n"
        f"World id: {world_id}\n"
        f"World state: {json.dumps(world, sort_keys=True)}\n"
        f"Reusable character: {json.dumps(character, sort_keys=True)}\n\n"
        "The narration should welcome the player into the chosen location, in "
        "second person and present tense. Do not mention JSON, tools, revisions, "
        "persistence, or administrative operations."
    )


def _parse_start_result(output: str) -> NarratorStartResult:
    """Parse and validate the narrator's JSON start contract."""
    text = clean_narration(output)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise NarratorError(
            "narration agent returned invalid start JSON",
            category="invalid_start_response",
        ) from error
    if not isinstance(payload, dict):
        raise NarratorError(
            "narration agent start result must be a JSON object",
            category="invalid_start_response",
        )
    allowed = {
        "start_location_name",
        "locations",
        "location_name",
        "location_description",
        "narration",
    }
    if "location_name" in payload and "start_location_name" in payload:
        raise NarratorError(
            "narration agent start mixes legacy and structured location fields",
            category="invalid_start_response",
        )
    unexpected = set(payload) - allowed
    if unexpected:
        raise NarratorError(
            "narration agent start result has unexpected fields",
            category="invalid_start_response",
        )
    location_name = payload.get("start_location_name", payload.get("location_name"))
    narration = payload.get("narration")
    description = payload.get("location_description")
    if not isinstance(location_name, str) or not location_name.strip():
        raise NarratorError(
            "narration agent start result has no location_name",
            category="invalid_start_response",
        )
    if len(location_name.strip()) > 200:
        raise NarratorError(
            "narration agent start location_name is too long",
            category="invalid_start_response",
        )
    if not isinstance(narration, str) or not narration.strip():
        raise NarratorError(
            "narration agent start result has no narration",
            category="invalid_start_response",
        )
    if len(narration.strip()) > 20_000:
        raise NarratorError(
            "narration agent start narration is too long",
            category="invalid_start_response",
        )
    if description is not None and not isinstance(description, str):
        raise NarratorError(
            "narration agent start location_description must be a string or null",
            category="invalid_start_response",
        )
    if isinstance(description, str) and len(description.strip()) > 5_000:
        raise NarratorError(
            "narration agent start location_description is too long",
            category="invalid_start_response",
        )
    if "locations" not in payload:
        locations = (
            NarratorStartLocation(
                name=location_name.strip(),
                description=description.strip() if isinstance(description, str) else None,
                parent_name=None,
                link_to_start=False,
            ),
        )
    else:
        raw_locations = payload["locations"]
        if (
            not isinstance(raw_locations, list)
            or not 3 <= len(raw_locations) <= _MAX_START_LOCATIONS
        ):
            raise NarratorError(
                "narration agent start locations must contain between 3 and 16 items",
                category="invalid_start_response",
            )
        locations_list: list[NarratorStartLocation] = []
        seen_names: set[str] = set()
        for raw_location in raw_locations:
            if isinstance(raw_location, dict) and "location_description" in raw_location:
                if "description" in raw_location:
                    raise NarratorError(
                        "narration agent start location has duplicate description fields",
                        category="invalid_start_response",
                    )
                description_alias = raw_location["location_description"]
                raw_location = {
                    key: value
                    for key, value in raw_location.items()
                    if key != "location_description"
                }
                raw_location["description"] = description_alias
            if (
                not isinstance(raw_location, dict)
                or not {
                    "name",
                    "description",
                    "parent_name",
                    "link_to_start",
                }.issubset(raw_location)
                or set(raw_location)
                - {
                    "name",
                    "description",
                    "parent_name",
                    "link_to_start",
                    "geography_role",
                    "direction",
                    "range_band",
                }
            ):
                raise NarratorError(
                    "narration agent start location has invalid fields",
                    category="invalid_start_response",
                )
            name = raw_location["name"]
            raw_description = raw_location["description"]
            parent_name = raw_location["parent_name"]
            link_to_start = raw_location["link_to_start"]
            geography_role = raw_location.get("geography_role", "local")
            direction = raw_location.get("direction")
            range_band = raw_location.get("range_band")
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
                raise NarratorError(
                    "narration agent start location name is invalid",
                    category="invalid_start_response",
                )
            key = name.strip().casefold()
            if key in seen_names:
                raise NarratorError(
                    "narration agent start contains duplicate location names",
                    category="invalid_start_response",
                )
            if raw_description is not None and (
                not isinstance(raw_description, str) or len(raw_description.strip()) > 5_000
            ):
                raise NarratorError(
                    "narration agent start location description is invalid",
                    category="invalid_start_response",
                )
            if parent_name is not None and not isinstance(parent_name, str):
                raise NarratorError(
                    "narration agent start parent_name is invalid",
                    category="invalid_start_response",
                )
            if geography_role not in _START_GEOGRAPHY_ROLES:
                raise NarratorError(
                    "narration agent start geography_role is invalid",
                    category="invalid_start_response",
                )
            if direction is not None and direction not in _START_DIRECTIONS:
                raise NarratorError(
                    "narration agent start direction is invalid",
                    category="invalid_start_response",
                )
            if range_band is not None and range_band not in _START_RANGE_BANDS:
                raise NarratorError(
                    "narration agent start range_band is invalid",
                    category="invalid_start_response",
                )
            if link_to_start is None:
                link_to_start = False
            elif isinstance(link_to_start, str):
                if link_to_start.strip().casefold() != location_name.strip().casefold():
                    raise NarratorError(
                        "narration agent start link target must be the selected start location",
                        category="invalid_start_response",
                    )
                link_to_start = True
            elif not isinstance(link_to_start, bool):
                raise NarratorError(
                    "narration agent start link_to_start must be boolean",
                    category="invalid_start_response",
                )
            seen_names.add(key)
            locations_list.append(
                NarratorStartLocation(
                    name=name.strip(),
                    description=raw_description.strip()
                    if isinstance(raw_description, str)
                    else None,
                    parent_name=parent_name.strip() if isinstance(parent_name, str) else None,
                    link_to_start=link_to_start,
                    geography_role=geography_role,
                    direction=direction,
                    range_band=range_band,
                )
            )
        locations = tuple(locations_list)
        location_names = {location.name.casefold() for location in locations}
        if location_name.strip().casefold() not in location_names:
            raise NarratorError(
                "narration agent start location is not present in locations",
                category="invalid_start_response",
            )
        locations = tuple(
            NarratorStartLocation(
                name=location.name,
                description=location.description,
                parent_name=(
                    location.parent_name
                    if location.parent_name is not None
                    and location.parent_name.casefold() in location_names
                    else None
                ),
                link_to_start=location.link_to_start,
                geography_role=location.geography_role,
                direction=location.direction,
                range_band=location.range_band,
            )
            for location in locations
        )
        for location in locations:
            if (
                location.parent_name is not None
                and location.parent_name.casefold() == location.name.casefold()
            ):
                raise NarratorError(
                    "narration agent start location cannot contain itself",
                    category="invalid_start_response",
                )
        start_key = location_name.strip().casefold()
        start_location = next(
            location for location in locations if location.name.casefold() == start_key
        )
        has_child = any(
            location.parent_name is not None and location.parent_name.casefold() == start_key
            for location in locations
        )
        has_sibling = any(
            location.name.casefold() != start_key and location.parent_name is None
            for location in locations
        )
        if start_location.parent_name is not None or not has_child or not has_sibling:
            raise NarratorError(
                "narration agent structured start must include the start, at least one "
                "child location, and at least one sibling location",
                category="invalid_start_response",
            )
        if start_key == "main street":
            child_count = sum(
                location.parent_name is not None
                and location.parent_name.casefold() == start_key
                for location in locations
            )
            if child_count < _MIN_MAIN_STREET_CHILDREN:
                raise NarratorError(
                    "narration agent Main Street start must include at least 10 child locations",
                    category="invalid_start_response",
                )
    return NarratorStartResult(
        location_name.strip(),
        next(
            (
                location.description
                for location in locations
                if location.name.casefold() == location_name.strip().casefold()
            ),
            description.strip() if isinstance(description, str) else None,
        ),
        narration.strip(),
        locations,
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
        start_timeout: float = START_NARRATOR_TIMEOUT_SECONDS,
    ) -> None:
        self.profile = profile
        self.timeout = timeout
        self.start_timeout = start_timeout

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
                f"narration agent timed out after {self.timeout:.0f}s",
                category="narrator_timeout",
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise NarratorError(f"narration agent failed: {detail[:500]}")
        narration = clean_narration(completed.stdout)
        if not narration:
            raise NarratorError("narration agent returned an empty reply")
        return narration

    def start(
        self, world_id: str, world: dict[str, Any], character: dict[str, Any]
    ) -> NarratorStartResult:
        """Ask the agent for a structured opening before a player exists."""
        prompt = build_world_start_prompt(world_id, world, character)
        command = ["hermes", "--profile", self.profile, "chat", "-Q", "-q", prompt]
        started_at = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.start_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            elapsed = time.monotonic() - started_at
            LOGGER.warning(
                "world start narration timed out: world_id=%s "
                "timeout_seconds=%.1f elapsed_seconds=%.1f",
                world_id,
                self.start_timeout,
                elapsed,
            )
            raise NarratorError(
                f"narration agent timed out after {self.start_timeout:.0f}s",
                category="narrator_timeout",
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise NarratorError(f"narration agent failed: {detail[:500]}")
        return _parse_start_result(completed.stdout)
