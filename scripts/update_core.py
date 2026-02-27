"""Preview and apply a core update from a new core path."""

from __future__ import annotations

import json
import sys

from skills_engine.update import apply_update, preview_update


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python scripts/update_core.py <path-to-new-core>",
            file=sys.stderr,
        )
        sys.exit(1)

    new_core_path = sys.argv[1]

    # Preview
    preview = preview_update(new_core_path)
    print("=== Update Preview ===")
    print(f"Current version: {preview.current_version}")
    print(f"New version:     {preview.new_version}")
    print(f"Files changed:   {len(preview.files_changed)}")
    if len(preview.files_changed) > 0:
        for f in preview.files_changed:
            print(f"  {f}")
    if len(preview.conflict_risk) > 0:
        print(f"Conflict risk:   {', '.join(preview.conflict_risk)}")
    if len(preview.custom_patches_at_risk) > 0:
        print(f"Custom patches at risk: {', '.join(preview.custom_patches_at_risk)}")
    print("")

    # Apply
    print("Applying update...")
    result = apply_update(new_core_path)
    print(json.dumps(result.model_dump(), indent=2))

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
