"""Rebase the current skills state, optionally with a new base."""

from __future__ import annotations

import json
import sys

from skills_engine.rebase import rebase


def main() -> None:
    new_base_path = sys.argv[1] if len(sys.argv) > 1 else None

    if new_base_path:
        print(f"Rebasing with new base from: {new_base_path}")
    else:
        print("Rebasing current state...")

    result = rebase(new_base_path)
    print(json.dumps(result.model_dump(), indent=2))

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
