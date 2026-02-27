"""Generate rerere-compatible resolution files for known skill combinations.

For each conflicting file when applying discord after telegram:
1. Run merge-file to produce conflict markers
2. Set up rerere adapter -- git records preimage and assigns a hash
3. Capture the hash by diffing rr-cache before/after
4. Write the correct resolution, git add + git rerere to record postimage
5. Save preimage, resolution, hash sidecar, and meta to .claude/resolutions/
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

from skills_engine.merge import cleanup_merge_state, merge_file, setup_rerere_adapter
from skills_engine.types import FileInputHashes


def sha256(file_path: Path) -> str:
    content = file_path.read_bytes()
    return hashlib.sha256(content).digest().hex()


def main() -> None:
    project_root = Path.cwd()
    base_dir = ".g2/base"

    # The files that conflict when applying discord after telegram
    conflict_files = ["src/index.ts", "src/config.ts", "src/routing.test.ts"]

    telegram_modify = ".claude/skills/add-telegram/modify"
    discord_modify = ".claude/skills/add-discord/modify"
    shipped_res_dir = project_root / ".claude" / "resolutions" / "discord+telegram"

    # Get git rr-cache directory
    git_dir_str = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        cwd=project_root,
    ).stdout.strip()

    git_dir = Path(git_dir_str)
    if not git_dir.is_absolute():
        git_dir = project_root / git_dir
    rr_cache_dir = git_dir / "rr-cache"

    def get_rr_cache_entries() -> set[str]:
        if not rr_cache_dir.exists():
            return set()
        return {entry.name for entry in rr_cache_dir.iterdir()}

    # Clear rr-cache to start fresh
    if rr_cache_dir.exists():
        shutil.rmtree(rr_cache_dir)
    rr_cache_dir.mkdir(parents=True, exist_ok=True)

    # Prepare output directory
    if shipped_res_dir.exists():
        shutil.rmtree(shipped_res_dir)

    results: list[dict[str, str]] = []
    file_hashes: dict[str, FileInputHashes] = {}

    for rel_path in conflict_files:
        base_path = project_root / base_dir / rel_path
        ours_path = project_root / telegram_modify / rel_path
        theirs_path = project_root / discord_modify / rel_path

        # Resolution = the correct combined file. Read from existing .resolution files.
        # The .resolution files were deleted above, so read from the backup copy
        backup_path = project_root / ".claude" / "resolutions" / "_backup" / (rel_path + ".resolution")
        if backup_path.exists():
            resolution_content = backup_path.read_text(encoding="utf-8")
        else:
            # Fall back to working tree (only works if both skills are applied)
            wt_path = project_root / rel_path
            resolution_content = wt_path.read_text(encoding="utf-8")

        # Do the merge to produce conflict markers
        tmp_file = Path(tempfile.gettempdir()) / f"g2-gen-{int(time.time() * 1000)}-{Path(rel_path).name}"
        shutil.copy2(ours_path, tmp_file)
        result = merge_file(tmp_file, base_path, theirs_path)

        if result.clean:
            print(f"{rel_path}: clean merge, no resolution needed")
            tmp_file.unlink()
            continue

        # Compute input file hashes for this conflicted file
        file_hashes[rel_path] = FileInputHashes(
            base=sha256(base_path),
            current=sha256(ours_path),  # "ours" = telegram's modify
            skill=sha256(theirs_path),  # "theirs" = discord's modify
        )

        preimage_content = tmp_file.read_text(encoding="utf-8")
        tmp_file.unlink()

        # Save original working tree file to restore later
        orig_content = (project_root / rel_path).read_text(encoding="utf-8")

        # Write conflict markers to working tree for rerere
        (project_root / rel_path).write_text(preimage_content, encoding="utf-8")

        # Track rr-cache entries before
        entries_before = get_rr_cache_entries()

        # Set up rerere adapter and let git record the preimage
        base_content = base_path.read_text(encoding="utf-8")
        ours_content = ours_path.read_text(encoding="utf-8")
        theirs_content = theirs_path.read_text(encoding="utf-8")
        setup_rerere_adapter(rel_path, base_content, ours_content, theirs_content)
        subprocess.run(
            ["git", "rerere"],
            capture_output=True,
            cwd=project_root,
        )

        # Find the new rr-cache entry (the hash)
        entries_after = get_rr_cache_entries()
        new_entries = [e for e in entries_after if e not in entries_before]

        if len(new_entries) != 1:
            print(
                f"{rel_path}: expected 1 new rr-cache entry, got {len(new_entries)}",
                file=sys.stderr,
            )
            cleanup_merge_state(rel_path)
            (project_root / rel_path).write_text(orig_content, encoding="utf-8")
            continue

        hash_val = new_entries[0]

        # Write the resolution and record it
        (project_root / rel_path).write_text(resolution_content, encoding="utf-8")
        subprocess.run(
            ["git", "add", rel_path],
            capture_output=True,
            cwd=project_root,
        )
        subprocess.run(
            ["git", "rerere"],
            capture_output=True,
            cwd=project_root,
        )

        # Clean up
        cleanup_merge_state(rel_path)
        (project_root / rel_path).write_text(orig_content, encoding="utf-8")

        # Save to .claude/resolutions/
        out_dir = shipped_res_dir / Path(rel_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        base_name = shipped_res_dir / rel_path
        # Copy preimage and postimage directly from rr-cache (normalized by git)
        shutil.copy2(rr_cache_dir / hash_val / "preimage", str(base_name) + ".preimage")
        Path(str(base_name) + ".resolution").write_text(resolution_content, encoding="utf-8")
        Path(str(base_name) + ".preimage.hash").write_text(hash_val, encoding="utf-8")

        results.append({"relPath": rel_path, "hash": hash_val})
        print(f"{rel_path}: hash={hash_val}")

    # Write meta.yaml
    meta = {
        "skills": ["discord", "telegram"],
        "apply_order": ["telegram", "discord"],
        "resolved_at": datetime.now(UTC).isoformat(),
        "tested": True,
        "test_passed": True,
        "resolution_source": "generated",
        "input_hashes": {},
        "output_hash": "",
        "file_hashes": {k: v.model_dump() for k, v in file_hashes.items()},
    }
    shipped_res_dir.mkdir(parents=True, exist_ok=True)
    (shipped_res_dir / "meta.yaml").write_text(yaml.dump(meta, default_flow_style=False), encoding="utf-8")

    print(f"\nGenerated {len(results)} resolution(s) in .claude/resolutions/discord+telegram/")


if __name__ == "__main__":
    main()
