"""Resolution cache for git rerere conflict resolutions."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from .constants import G2_DIR, RESOLUTIONS_DIR, SHIPPED_RESOLUTIONS_DIR
from .state import compute_file_hash
from .types import FileInputHashes, ResolutionMeta


class PreimagePair(BaseModel):
    """A preimage/resolution pair found in the resolution cache."""

    rel_path: str
    preimage: Path
    resolution: Path


def _resolution_key(skills: list[str]) -> str:
    """Build the resolution directory key from skill identifiers.

    Skills are sorted alphabetically and joined with "+".
    """
    return "+".join(sorted(skills))


def find_resolution_dir(
    skills: list[str],
    project_root: Path,
) -> Path | None:
    """Find the resolution directory for a given skill combination.

    Returns absolute path if it exists, None otherwise.
    """
    key = _resolution_key(skills)

    # Check shipped resolutions (.claude/resolutions/) first, then project-level
    for base_dir in [SHIPPED_RESOLUTIONS_DIR, RESOLUTIONS_DIR]:
        dir_path = project_root / base_dir / key
        if dir_path.exists():
            return dir_path

    return None


def _find_preimage_pairs(dir_path: Path, base_dir: Path) -> list[PreimagePair]:
    """Recursively find preimage/resolution pairs in a directory."""
    pairs: list[PreimagePair] = []

    for entry in dir_path.iterdir():
        if entry.is_dir():
            pairs.extend(_find_preimage_pairs(entry, base_dir))
        elif entry.name.endswith(".preimage") and not entry.name.endswith(".preimage.hash"):
            resolution_path = entry.with_name(entry.name.removesuffix(".preimage") + ".resolution")
            if resolution_path.exists():
                rel_path = str(entry.relative_to(base_dir)).removesuffix(".preimage")
                pairs.append(
                    PreimagePair(
                        rel_path=rel_path,
                        preimage=entry,
                        resolution=resolution_path,
                    )
                )

    return pairs


def _find_rerere_hash(rr_cache_dir: Path, preimage_content: str) -> str | None:
    """Find the rerere hash for a given preimage by scanning rr-cache entries.

    Returns the directory name (hash) whose preimage matches the given content.
    """
    if not rr_cache_dir.exists():
        return None

    for entry in rr_cache_dir.iterdir():
        if not entry.is_dir():
            continue
        preimage_path = entry / "preimage"
        if preimage_path.exists():
            content = preimage_path.read_text(encoding="utf-8")
            if content == preimage_content:
                return entry.name

    return None


def load_resolutions(
    skills: list[str],
    project_root: Path,
    skill_dir: Path | None,
) -> bool:
    """Load cached resolutions into the local git rerere cache.

    Verifies file_hashes from meta.yaml match before loading each pair.
    Returns True if loaded successfully, False if not found or no pairs loaded.
    """
    res_dir = find_resolution_dir(skills, project_root)
    if res_dir is None:
        return False

    meta_path = res_dir / "meta.yaml"
    if not meta_path.exists():
        return False

    try:
        raw = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        meta = ResolutionMeta(**raw)
    except Exception:
        return False

    if meta.input_hashes is None:
        return False

    # Find all preimage/resolution pairs
    pairs = _find_preimage_pairs(res_dir, res_dir)
    if not pairs:
        return False

    # Get the git directory
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
            cwd=project_root,
        )
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = project_root / git_dir
    except subprocess.CalledProcessError:
        return False

    rr_cache_dir = git_dir / "rr-cache"
    loaded_any = False

    for pair in pairs:
        # Verify file_hashes -- skip pair if hashes don't match
        expected = meta.file_hashes.get(pair.rel_path)
        if expected is None:
            print(f"resolution-cache: skipping {pair.rel_path} -- no file_hashes in meta")
            continue

        base_path = project_root / G2_DIR / "base" / pair.rel_path
        current_path = project_root / pair.rel_path

        if skill_dir is None:
            print(f"resolution-cache: skipping {pair.rel_path} -- no skill dir")
            continue

        skill_modify_path = skill_dir / "modify" / pair.rel_path

        if not base_path.exists() or not current_path.exists() or not skill_modify_path.exists():
            print(f"resolution-cache: skipping {pair.rel_path} -- input files not found")
            continue

        base_hash = compute_file_hash(base_path)
        if base_hash != expected.base:
            print(f"resolution-cache: skipping {pair.rel_path} -- base hash mismatch")
            continue

        current_hash = compute_file_hash(current_path)
        if current_hash != expected.current:
            print(f"resolution-cache: skipping {pair.rel_path} -- current hash mismatch")
            continue

        skill_hash = compute_file_hash(skill_modify_path)
        if skill_hash != expected.skill:
            print(f"resolution-cache: skipping {pair.rel_path} -- skill hash mismatch")
            continue

        preimage_content = pair.preimage.read_text(encoding="utf-8")
        resolution_content = pair.resolution.read_text(encoding="utf-8")

        # Git rerere uses its own internal hash format (not git hash-object).
        # We store the rerere hash in a .hash sidecar file, captured when
        # save_resolution() reads the actual rr-cache after rerere records it.
        hash_sidecar = pair.preimage.with_name(pair.preimage.name + ".hash")
        if not hash_sidecar.exists():
            # No hash recorded -- skip this pair (legacy format)
            continue
        rerere_hash = hash_sidecar.read_text(encoding="utf-8").strip()
        if not rerere_hash:
            continue

        # Create rr-cache entry
        cache_dir = rr_cache_dir / rerere_hash
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "preimage").write_text(preimage_content, encoding="utf-8")
        (cache_dir / "postimage").write_text(resolution_content, encoding="utf-8")
        loaded_any = True

    return loaded_any


class ResolutionFile(BaseModel):
    """A file to save in the resolution cache."""

    rel_path: str
    preimage: str
    resolution: str
    input_hashes: FileInputHashes


def save_resolution(
    skills: list[str],
    files: list[ResolutionFile | dict],
    meta: dict[str, object],
    project_root: Path,
) -> None:
    """Save conflict resolutions to the resolution cache."""
    key = _resolution_key(skills)
    res_dir = project_root / RESOLUTIONS_DIR / key

    # Normalize dicts to ResolutionFile objects
    normalized_files: list[ResolutionFile] = []
    for f in files:
        if isinstance(f, dict):
            # Convert input_hashes dict to FileInputHashes if needed
            ih = f.get("input_hashes", {})
            if isinstance(ih, dict) and not isinstance(ih, FileInputHashes):
                ih = FileInputHashes(**ih)
            normalized_files.append(
                ResolutionFile(
                    rel_path=f["rel_path"],
                    preimage=f["preimage"],
                    resolution=f["resolution"],
                    input_hashes=ih,
                )
            )
        else:
            normalized_files.append(f)

    # Get the git rr-cache directory to find actual rerere hashes
    rr_cache_dir: Path | None = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
            cwd=project_root,
        )
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = project_root / git_dir
        rr_cache_dir = git_dir / "rr-cache"
    except subprocess.CalledProcessError:
        # Not a git repo -- skip hash capture
        pass

    # Write preimage/resolution pairs
    for file in normalized_files:
        preimage_path = res_dir / (file.rel_path + ".preimage")
        resolution_path = res_dir / (file.rel_path + ".resolution")

        preimage_path.parent.mkdir(parents=True, exist_ok=True)
        preimage_path.write_text(file.preimage, encoding="utf-8")
        resolution_path.write_text(file.resolution, encoding="utf-8")

        # Capture the actual rerere hash by finding the rr-cache entry
        # whose preimage matches ours
        if rr_cache_dir is not None and rr_cache_dir.exists():
            rerere_hash = _find_rerere_hash(rr_cache_dir, file.preimage)
            if rerere_hash is not None:
                preimage_path.with_name(preimage_path.name + ".hash").write_text(rerere_hash, encoding="utf-8")

    # Collect file_hashes from individual files
    file_hashes: dict[str, FileInputHashes] = {}
    for file in normalized_files:
        file_hashes[file.rel_path] = file.input_hashes

    # Build full meta with defaults -- merge file_hashes from meta arg
    merged_file_hashes: dict[str, FileInputHashes] = {**file_hashes}
    meta_file_hashes = meta.get("file_hashes")
    if isinstance(meta_file_hashes, dict):
        for k, v in meta_file_hashes.items():
            if isinstance(v, FileInputHashes):
                merged_file_hashes[k] = v

    # Extract meta fields with proper defaults
    apply_order = meta.get("apply_order")
    apply_order_list: list[str] = list(apply_order) if isinstance(apply_order, list) else list(skills)
    core_version_raw = meta.get("core_version", "")
    core_version_str: str = str(core_version_raw) if core_version_raw else ""
    resolved_at_raw = meta.get("resolved_at", "")
    resolved_at_str: str = str(resolved_at_raw) if resolved_at_raw else datetime.now(UTC).isoformat()
    resolution_source_raw = meta.get("resolution_source", "user")
    resolution_source_str: str = str(resolution_source_raw) if resolution_source_raw else "user"
    input_hashes_raw = meta.get("input_hashes")
    input_hashes_dict: dict[str, str] = dict(input_hashes_raw) if isinstance(input_hashes_raw, dict) else {}
    output_hash_raw = meta.get("output_hash", "")
    output_hash_str: str = str(output_hash_raw) if output_hash_raw else ""

    full_meta = ResolutionMeta(
        skills=sorted(skills),
        apply_order=apply_order_list,
        core_version=core_version_str,
        resolved_at=resolved_at_str,
        tested=bool(meta.get("tested", False)),
        test_passed=bool(meta.get("test_passed", False)),
        resolution_source=resolution_source_str,
        input_hashes=input_hashes_dict,
        output_hash=output_hash_str,
        file_hashes=merged_file_hashes,
    )

    meta_yaml_path = res_dir / "meta.yaml"
    meta_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    meta_yaml_path.write_text(
        yaml.safe_dump(full_meta.model_dump(), sort_keys=True),
        encoding="utf-8",
    )


def clear_all_resolutions(project_root: Path) -> None:
    """Remove all resolution cache entries.

    Called after rebase since the base has changed and old resolutions are invalid.
    """
    res_dir = project_root / RESOLUTIONS_DIR
    if res_dir.exists():
        shutil.rmtree(res_dir)
        res_dir.mkdir(parents=True, exist_ok=True)
