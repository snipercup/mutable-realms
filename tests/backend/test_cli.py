from __future__ import annotations

import pytest

from backend.cli import main


@pytest.mark.parametrize("command", ["migrate", "seed", "validate"])
def test_reserved_world_command_exits_with_clear_message(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([command])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == (
        f"mutable-realms: '{command}' is reserved for the authoritative persistence slice "
        "and is not implemented yet.\n"
    )
