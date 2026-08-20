import json
import logging
import subprocess

import pytest

from backend.app.narrator import (
    HermesNarrator,
    NarratorError,
    build_narration_prompt,
    build_world_start_prompt,
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
        f"{CLEAN_NARRATION}\n\nNo change was persisted. Refresh the page to see the world as it is."
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

    prompt = build_narration_prompt("world-of-earthalon", "fate", "Enter the guild hall.", context)

    assert "Current world state" in prompt
    assert "world of Aerthalon" in prompt
    assert "A kingdom of sunlit plains and ancient groves." in prompt
    assert "You arrive at the gates of the guild city." in prompt
    assert "Fate is a wandering diplomat." in prompt
    assert "Player: fate (world-of-earthalon-player)" in prompt
    assert "You are at: Settlement — The first camp." in prompt
    assert "world_id=world-of-earthalon" in prompt


def test_build_world_start_prompt_requires_structured_location_and_narration() -> None:
    prompt = build_world_start_prompt(
        "world-a",
        {"id": "world-a", "elements": [{"element_type": "opening_scene", "content": "At Elaris."}]},
        {"id": "fate", "name": "Fate", "basic_info": "Diplomat"},
    )
    assert "Return ONLY valid JSON" in prompt
    assert "location_name" in prompt
    assert "location_description" in prompt
    assert "At Elaris." in prompt
    assert "Diplomat" in prompt


def test_build_world_start_prompt_requires_bounded_contextual_layout() -> None:
    prompt = build_world_start_prompt(
        "world-of-aerthalon",
        {
            "id": "world-of-aerthalon",
            "elements": [
                {
                    "element_type": "opening_scene",
                    "content": "You are on the street in front of the Adventurer's Guild.",
                }
            ],
        },
        {"id": "fate", "name": "Fate"},
    )
    assert "street-level" in prompt
    assert "city or province" in prompt
    assert "locations" in prompt
    assert "start_location_name" in prompt
    assert "Main Street" in prompt
    assert "at least one child location" in prompt
    assert "at least one sibling location" in prompt
    assert "map_form" in prompt
    assert "mine" in prompt
    assert "3 to 16 locations" in prompt
    assert "at least 10 direct child locations" in prompt


def test_hermes_narrator_start_parses_allowlisted_map_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"start_location_name":"Elaris Street","locations":['
            '{"name":"Elaris Street","description":"Street.","parent_name":null,'
            '"link_to_start":false,"map_form":"street"},'
            '{"name":"Guild","description":"Guild.","parent_name":"Elaris Street",'
            '"link_to_start":false,"map_form":"building"},'
            '{"name":"North Road","description":"Road.","parent_name":null,'
            '"link_to_start":false,"map_form":"forest"}],'
            '"narration":"You arrive."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert [location.map_form for location in result.locations] == [
        "street",
        "building",
        "forest",
    ]


def test_hermes_narrator_start_accepts_json_code_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            "```json\n"
            '{"start_location_name":"Elaris Street","locations":['
            '{"name":"Elaris Street","description":"Street.",'
            '"parent_name":null,"link_to_start":false},'
            '{"name":"Guild","description":"Guild.",'
            '"parent_name":"Elaris Street","link_to_start":false},'
            '{"name":"North Road","description":"Road.","parent_name":null,"link_to_start":false}],'
            '"narration":"You arrive."}\n'
            "```"
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert result.start_location_name == "Elaris Street"


def test_hermes_narrator_start_normalizes_semantic_geography_role_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"start_location_name":"Elaris Street","locations":['
            '{"name":"Elaris Street","description":"Street.",'
            '"parent_name":null,"link_to_start":false},'
            '{"name":"Guild","description":"Guild.",'
            '"parent_name":"Elaris Street","link_to_start":false,'
            '"geography_role":"landmark"},'
            '{"name":"River","description":"Water.","parent_name":null,"link_to_start":false,"geography_role":"water"}],'
            '"narration":"You arrive."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert [location.geography_role for location in result.locations] == [
        "local",
        "local",
        "local",
    ]


def test_hermes_narrator_start_accepts_ten_main_street_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locations = [
        {
            "name": "Main Street",
            "description": "The street.",
            "parent_name": None,
            "link_to_start": False,
        }
    ]
    locations.extend(
        {
            "name": f"Main Street Child {index}",
            "description": "A nearby place.",
            "parent_name": "Main Street",
            "link_to_start": False,
        }
        for index in range(1, 11)
    )
    locations.append(
        {
            "name": "North Road",
            "description": "A neighboring road.",
            "parent_name": None,
            "link_to_start": False,
        }
    )

    class _Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "start_location_name": "Main Street",
                "locations": locations,
                "narration": "You arrive on Main Street.",
            }
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})

    assert len(result.locations) == 12
    assert sum(location.parent_name == "Main Street" for location in result.locations) == 10


def test_hermes_narrator_start_repairs_raw_newlines_inside_narration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"start_location_name":"Elaris Street","locations":['
            '{"name":"Elaris Street","description":"Street.",'
            '"parent_name":null,"link_to_start":false},'
            '{"name":"Guild","description":"Guild.",'
            '"parent_name":"Elaris Street","link_to_start":false},'
            '{"name":"North Road","description":"Road.",'
            '"parent_name":null,"link_to_start":false}],'
            '"narration":"You arrive.\n\nIt is midday and the street is busy."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert result.start_location_name == "Elaris Street"
    assert "\n\n" in result.narration


def test_hermes_narrator_start_ignores_tool_render_noise_before_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            "  ✓ review diff\n"
            "a//tmp/validate_start.py b//tmp/validate_start.py\n"
            "@@ -0,0 +1,40 @@\n"
            "+import json, sys\n"
            "total_locations=13\n"
            '{"start_location_name":"Elaris Street","locations":['
            '{"name":"Elaris Street","description":"Street.",'
            '"parent_name":null,"link_to_start":false},'
            '{"name":"Guild","description":"Guild.",'
            '"parent_name":"Elaris Street","link_to_start":false},'
            '{"name":"North Road","description":"Road.",'
            '"parent_name":null,"link_to_start":false}],'
            '"narration":"You arrive."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert result.start_location_name == "Elaris Street"
    assert len(result.locations) == 3


def test_hermes_narrator_start_rejects_undersized_main_street_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = json.dumps(
            {
                "start_location_name": "Main Street",
                "locations": [
                    {
                        "name": "Main Street",
                        "description": "The street.",
                        "parent_name": None,
                        "link_to_start": False,
                    },
                    {
                        "name": "Guild",
                        "description": "A guild.",
                        "parent_name": "Main Street",
                        "link_to_start": False,
                    },
                    {
                        "name": "North Road",
                        "description": "A sibling.",
                        "parent_name": None,
                        "link_to_start": False,
                    },
                ],
                "narration": "You arrive.",
            }
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    with pytest.raises(NarratorError, match="at least 10 child locations"):
        HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})


def test_hermes_narrator_uses_separate_start_timeout_and_logs_timeout(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[dict[str, object]] = []

    def run(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(cmd="hermes", timeout=240)

    monkeypatch.setattr("backend.app.narrator.subprocess.run", run)
    with caplog.at_level(logging.WARNING, logger="backend.app.narrator"):
        with pytest.raises(NarratorError, match="240s") as error:
            HermesNarrator(timeout=11, start_timeout=240).start(
                "world-a", {"id": "world-a"}, {"id": "fate"}
            )

    assert error.value.category == "narrator_timeout"
    assert calls == [{"capture_output": True, "text": True, "timeout": 240, "check": False}]
    assert "world_id=world-a" in caplog.text
    assert "timeout_seconds=240.0" in caplog.text
    assert "elapsed_seconds=" in caplog.text


def test_hermes_narrator_bounds_timeout_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.narrator import _bounded_timeout

    monkeypatch.setenv("LOW_TIMEOUT", "1")
    monkeypatch.setenv("HIGH_TIMEOUT", "999")
    monkeypatch.setenv("INVALID_TIMEOUT", "not-a-number")
    monkeypatch.setenv("NAN_TIMEOUT", "nan")
    assert _bounded_timeout("MISSING_TIMEOUT", 240) == 240
    assert _bounded_timeout("LOW_TIMEOUT", 240) == 5
    assert _bounded_timeout("HIGH_TIMEOUT", 240) == 300
    assert _bounded_timeout("INVALID_TIMEOUT", 240) == 240
    assert _bounded_timeout("NAN_TIMEOUT", 240) == 240


def test_hermes_narrator_start_parses_contextual_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"start_location_name":"Elaris Street",'
            '"locations":[{"name":"Elaris Street",'
            '"description":"A broad street.","parent_name":null,"link_to_start":false},'
            '{"name":"Adventurer\\u0027s Guild","description":"Guild doors.",'
            '"parent_name":"Elaris Street","link_to_start":true},'
            '{"name":"North Road","description":"A road north.",'
            '"parent_name":null,"link_to_start":false,'
            '"geography_role":"boundary","direction":"north","range_band":"mid"}],'
            '"narration":"You stand before the guild doors."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert result.start_location_name == "Elaris Street"
    assert [location.name for location in result.locations] == [
        "Elaris Street",
        "Adventurer's Guild",
        "North Road",
    ]
    assert result.locations[1].parent_name == "Elaris Street"
    assert result.locations[1].link_to_start is True
    assert result.locations[2].parent_name is None
    assert result.locations[2].geography_role == "boundary"
    assert result.locations[2].direction == "north"
    assert result.locations[2].range_band == "mid"


def test_hermes_narrator_start_rejects_structured_layout_without_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"start_location_name":"Main Street","locations":['
            '{"name":"Main Street","description":"Street.",'
            '"parent_name":null,"link_to_start":false},'
            '{"name":"Guild","description":"Guild.",'
            '"parent_name":"Main Street","link_to_start":true},'
            '{"name":"Market","description":"Market.",'
            '"parent_name":"Main Street","link_to_start":false}],'
            '"narration":"Welcome."}'
        )
        stderr = ""

    monkeypatch.setattr("backend.app.narrator.subprocess.run", lambda *args, **kwargs: _Completed())
    with pytest.raises(NarratorError, match="sibling"):
        HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})


def test_hermes_narrator_start_parses_structured_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"location_name":"Elaris","location_description":"Guild square.",'
            '"narration":"You enter Elaris."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert result.location_name == "Elaris"
    assert result.location_description == "Guild square."
    assert result.narration == "You enter Elaris."


def test_hermes_narrator_start_rejects_unexpected_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"location_name":"Elaris","location_description":null,'
            '"narration":"Welcome.","tool":"bad"}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    with pytest.raises(NarratorError, match="unexpected fields") as error:
        HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert error.value.category == "invalid_start_response"


def test_hermes_narrator_start_rejects_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    with pytest.raises(NarratorError, match="invalid start JSON"):
        HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})


def test_hermes_narrator_start_rejects_mixed_location_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"location_name":"Old", "start_location_name":"New",'
            '"location_description":null,"narration":"Welcome."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    with pytest.raises(NarratorError, match="mixes legacy"):
        HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})


def test_hermes_narrator_start_normalizes_model_layout_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"start_location_name":"Copperlane Street","locations":['
            '{"name":"Copperlane Street","description":"Street.",'
            '"parent_name":"Eliris","link_to_start":null},'
            '{"name":"Adventurer\\u0027s Guildhall","description":"Guild.",'
            '"parent_name":"Copperlane Street","link_to_start":"Copperlane Street"},'
            '{"name":"North Road","description":"Road.",'
            '"parent_name":null,"link_to_start":false}],'
            '"narration":"You stand outside."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )
    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})
    assert result.locations[0].parent_name is None
    assert result.locations[0].link_to_start is False
    assert result.locations[1].parent_name == "Copperlane Street"
    assert result.locations[1].link_to_start is True


def test_hermes_narrator_start_accepts_nested_location_description_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Completed:
        returncode = 0
        stdout = (
            '{"start_location_name":"Elaris Street","locations":['
                '{"name":"Elaris Street","location_description":"Street.",'
                '"parent_name":null,"link_to_start":true},'
                '{"name":"Guild","location_description":"Guild.",'
                '"parent_name":"Elaris Street","link_to_start":false},'
            '{"name":"North Road","location_description":"Road.",'
            '"parent_name":null,"link_to_start":false}],'
            '"narration":"You arrive."}'
        )
        stderr = ""

    monkeypatch.setattr(
        "backend.app.narrator.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )

    result = HermesNarrator().start("world-a", {"id": "world-a"}, {"id": "fate"})

    assert result.locations[0].description == "Street."


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
