from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

_RESERVED_COMMANDS = ("migrate", "seed", "validate")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mutable-realms")
    parser.add_argument("command", choices=_RESERVED_COMMANDS)
    args = parser.parse_args(argv)

    print(
        f"mutable-realms: '{args.command}' is reserved for the authoritative persistence "
        "slice and is not implemented yet.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
