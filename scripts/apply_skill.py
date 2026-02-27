"""Apply a skill from a skill directory."""

from __future__ import annotations

import json
import sys

from skills_engine.apply import apply_skill


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/apply_skill.py <skill-dir>", file=sys.stderr)
        sys.exit(1)

    skill_dir = sys.argv[1]

    result = apply_skill(skill_dir)
    print(json.dumps(result.model_dump(), indent=2))

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
