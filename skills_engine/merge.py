"""Git merge operations for three-way file merging and rerere integration."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .types import MergeResult


def is_git_repo() -> bool:
    """Check if the current directory is inside a git repository."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def merge_file(
    current_path: Path,
    base_path: Path,
    skill_path: Path,
) -> MergeResult:
    """Run git merge-file to three-way merge files.

    Modifies current_path in-place.
    Returns MergeResult with clean=True, exit_code=0 on clean merge,
    clean=False, exit_code=N on conflict (N = number of conflicts).
    """
    result = subprocess.run(
        ["git", "merge-file", str(current_path), str(base_path), str(skill_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        return MergeResult(clean=True, exit_code=0)

    if result.returncode > 0:
        # Positive exit code = number of conflicts
        return MergeResult(clean=False, exit_code=result.returncode)

    # Negative exit code = error
    raise RuntimeError(f"git merge-file failed with exit code {result.returncode}: {result.stderr}")


def setup_rerere_adapter(
    file_path: str,
    base_content: str,
    ours_content: str,
    theirs_content: str,
) -> None:
    """Set up unmerged index entries for rerere adapter.

    Creates stages 1/2/3 so git rerere can record/resolve conflicts.
    """
    if not is_git_repo():
        return

    git_dir_result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    git_dir = Path(git_dir_result.stdout.strip())

    # Clean up stale MERGE_HEAD from a previous crash
    if (git_dir / "MERGE_HEAD").exists():
        cleanup_merge_state(file_path)

    # Hash objects into git object store
    base_hash = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=base_content,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    ours_hash = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=ours_content,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    theirs_hash = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=theirs_content,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Create unmerged index entries (stages 1/2/3)
    index_info = "\n".join(
        [
            f"100644 {base_hash} 1\t{file_path}",
            f"100644 {ours_hash} 2\t{file_path}",
            f"100644 {theirs_hash} 3\t{file_path}",
        ]
    )

    subprocess.run(
        ["git", "update-index", "--index-info"],
        input=index_info,
        capture_output=True,
        text=True,
        check=True,
    )

    # Set MERGE_HEAD and MERGE_MSG (required for rerere)
    head_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    (git_dir / "MERGE_HEAD").write_text(head_hash + "\n")
    (git_dir / "MERGE_MSG").write_text(f"Skill merge: {file_path}\n")


def run_rerere(file_path: str) -> bool:
    """Run git rerere to record or auto-resolve conflicts.

    When file_path is given, checks that specific file for remaining conflict markers.
    Returns True if rerere auto-resolved the conflict.
    """
    if not is_git_repo():
        return False

    try:
        subprocess.run(
            ["git", "rerere"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Check if the specific working tree file still has conflict markers.
        # rerere resolves the working tree but does NOT update the index,
        # so checking unmerged index entries would give a false negative.
        content = Path(file_path).read_text()
        return "<<<<<<<" not in content
    except (subprocess.CalledProcessError, OSError):
        return False


def cleanup_merge_state(file_path: str | None = None) -> None:
    """Clean up merge state after rerere operations.

    Pass file_path to only reset that file's index entries
    (preserving user's staged changes).
    """
    if not is_git_repo():
        return

    git_dir_result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    git_dir = Path(git_dir_result.stdout.strip())

    # Remove merge markers
    merge_head = git_dir / "MERGE_HEAD"
    merge_msg = git_dir / "MERGE_MSG"
    if merge_head.exists():
        merge_head.unlink()
    if merge_msg.exists():
        merge_msg.unlink()

    # Reset only the specific file's unmerged index entries to avoid
    # dropping the user's pre-existing staged changes
    try:
        if file_path:
            subprocess.run(
                ["git", "reset", "--", file_path],
                capture_output=True,
                text=True,
                check=True,
            )
        else:
            subprocess.run(
                ["git", "reset"],
                capture_output=True,
                text=True,
                check=True,
            )
    except subprocess.CalledProcessError:
        # May fail if nothing staged
        pass
