from __future__ import annotations

import pytest

from backend.app.narrator import (
    HermesNarrator,
    NarratorError,
    build_narration_prompt,
    clean_narration,
)

CLEAN_NARRATION = (
    "You stand quietly on the rope-slick planks of the Harbor Docks, letting the salt "
    "wind sweep away what lingers from your travels."
)


def test_clean_narration_passes_clean_prose_through() -> None:
    assert clean_narration(CLEAN_NARRATION) == CLEAN_NARRATION


def test_clean_narration_strips_leading_decision_line() -> None:
    raw = (
        "Decision: narrate_without_mutation. No mutation — the action is passive rest "
        "with no state change needed.\n\n"
        f"{CLEAN_NARRATION}"
    )
    assert clean_narration(raw) == CLEAN_NARRATION


def test_clean_narration_strips_trailing_persistence_meta() -> None:
    raw = (
        f"{CLEAN_NARRATION}\n\n"
        "No change was persisted. Refresh the page to see the world as it is."
    )
    assert clean_narration(raw) == CLEAN_NARRATION


def test_clean_narration_strips_rendered_reasoning_box() -> None:
    box = (
        "\n┌─ Reasoning ──────────────────────────────────────────────┐\n"
        "The player is performing a passive action.\n"
        "└───────────────────────────────────────────────────────────┘\n"
        f"{CLEAN_NARRATION}\n"
    )
    assert clean_narration(box) == CLEAN_NARRATION


def test_clean_narration_returns_empty_for_empty_input() -> None:
    assert clean_narration("") == ""
    assert clean_narration("   \n  ") == ""


def test_build_narration_prompt_requires_narration_only_reply() -> None:
    prompt = build_narration_prompt("town-world", "sailor", "I move to the docks.")
    assert "town-world" in prompt
    assert "sailor" in prompt
    assert "I move to the docks." in prompt
    assert "entire reply must be the player-facing narration" in prompt
    assert "Do not include decision summaries" in prompt
    assert "Never mention persistence" in prompt
    assert "Current world state" not in prompt


def test_build_narration_prompt_embeds_selected_world_context() -> None:
    context = {
        "world": {
            "id": "world-of-earthalon",
            "name": "world of Aerthalon",
            "revision": 2,
            "description": "A kingdom of sunlit plains and ancient groves.",
        },
        "player": {"id": "world-of-earthalon-player", "name": "fate"},
        "current_location": {
            "id": "world-of-earthalon-start",
            "name": "Settlement",
            "description": "The first camp.",
            "entities": [],
        },
        "world_elements": [
            {
                "element_type": "opening_scene",
                "content": "You arrive at the gates of the guild city.",
            },
            {"element_type": "author_note", "content": "Fate is a wandering diplomat."},
        ],
        "recent_events": [],
    }

    prompt = build_narration_prompt(
        "world-of-earthalon", "fate", "Enter the guild hall.", context
    )

    assert "Current world state" in prompt
    assert "world of Aerthalon" in prompt
    assert "A kingdom of sunlit plains and ancient groves." in prompt
    assert "You arrive at the gates of the guild city." in prompt
    assert "Fate is a wandering diplomat." in prompt
    assert "Player: fate (world-of-earthalon-player)" in prompt
    assert "You are at: Settlement — The first camp." in prompt
    assert "world_id=world-of-earthalon" in prompt


def test_hermes_narrator_raises_on_empty_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = "┌─ Reasoning ──┐\n└─────────────┘\n"
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    narrator = HermesNarrator()
    with pytest.raises(NarratorError, match="empty reply"):
        narrator("town-world", "sailor", "I wait.")
