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
