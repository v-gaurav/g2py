"""Uninstall a previously applied skill."""

from __future__ import annotations

import sys

from skills_engine.uninstall import uninstall_skill


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python scripts/uninstall_skill.py <skill-name>",
            file=sys.stderr,
        )
        sys.exit(1)

    skill_name = sys.argv[1]

    print(f"Uninstalling skill: {skill_name}")
    result = uninstall_skill(skill_name)

    if result.custom_patch_warning:
        print(f"\nWarning: {result.custom_patch_warning}", file=sys.stderr)
        print(
            "To proceed, remove the custom_patch from state.yaml and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not result.success:
        print(f"\nFailed: {result.error}", file=sys.stderr)
        sys.exit(1)

    print(f"\nSuccessfully uninstalled: {skill_name}")
    if result.replay_results:
        print("Replay test results:")
        for name, passed in result.replay_results.items():
            print(f"  {name}: {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(err, file=sys.stderr)
        sys.exit(1)
