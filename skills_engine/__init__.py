"""Skills engine for applying, managing, and updating G2 skills."""

from __future__ import annotations

from .apply import apply_skill
from .backup import clear_backup, create_backup, restore_backup
from .constants import (
    BACKUP_DIR,
    BASE_DIR,
    CUSTOM_DIR,
    G2_DIR,
    LOCK_FILE,
    RESOLUTIONS_DIR,
    SHIPPED_RESOLUTIONS_DIR,
    SKILLS_SCHEMA_VERSION,
    STATE_FILE,
)
from .customize import (
    abort_customize,
    commit_customize,
    is_customize_active,
    start_customize,
)
from .file_ops import execute_file_ops
from .init import init_g2_dir
from .lock import acquire_lock, is_locked, release_lock
from .manifest import (
    check_conflicts,
    check_core_version,
    check_dependencies,
    check_system_version,
    read_manifest,
)
from .merge import (
    cleanup_merge_state,
    is_git_repo,
    merge_file,
    run_rerere,
    setup_rerere_adapter,
)
from .migrate import init_skills_system, migrate_existing
from .path_remap import load_path_remap, record_path_remap, resolve_path_remap
from .rebase import rebase
from .replay import ReplayResult, find_skill_dir, replay_skills
from .resolution_cache import (
    clear_all_resolutions,
    find_resolution_dir,
    load_resolutions,
    save_resolution,
)
from .state import (
    compare_semver,
    compute_file_hash,
    get_applied_skills,
    get_custom_modifications,
    read_state,
    record_custom_modification,
    record_skill_application,
    write_state,
)
from .structured import (
    are_ranges_compatible,
    merge_docker_compose_services,
    merge_env_additions,
    merge_npm_dependencies,
    run_npm_install,
)
from .types import (
    AppliedSkill,
    ApplyResult,
    CustomModification,
    FileInputHashes,
    FileOperation,
    FileOpsResult,
    MergeResult,
    RebaseResult,
    ResolutionMeta,
    SkillManifest,
    SkillState,
    UninstallResult,
    UpdatePreview,
    UpdateResult,
)
from .uninstall import uninstall_skill
from .update import apply_update, preview_update

__all__ = [
    # apply
    "apply_skill",
    # backup
    "clear_backup",
    "create_backup",
    "restore_backup",
    # constants
    "BACKUP_DIR",
    "BASE_DIR",
    "CUSTOM_DIR",
    "G2_DIR",
    "LOCK_FILE",
    "RESOLUTIONS_DIR",
    "SHIPPED_RESOLUTIONS_DIR",
    "SKILLS_SCHEMA_VERSION",
    "STATE_FILE",
    # customize
    "abort_customize",
    "commit_customize",
    "is_customize_active",
    "start_customize",
    # file_ops
    "execute_file_ops",
    # init
    "init_g2_dir",
    # lock
    "acquire_lock",
    "is_locked",
    "release_lock",
    # manifest
    "check_conflicts",
    "check_core_version",
    "check_dependencies",
    "check_system_version",
    "read_manifest",
    # merge
    "cleanup_merge_state",
    "is_git_repo",
    "merge_file",
    "run_rerere",
    "setup_rerere_adapter",
    # migrate
    "init_skills_system",
    "migrate_existing",
    # path_remap
    "load_path_remap",
    "record_path_remap",
    "resolve_path_remap",
    # rebase
    "rebase",
    # replay
    "ReplayResult",
    "find_skill_dir",
    "replay_skills",
    # resolution_cache
    "clear_all_resolutions",
    "find_resolution_dir",
    "load_resolutions",
    "save_resolution",
    # state
    "compare_semver",
    "compute_file_hash",
    "get_applied_skills",
    "get_custom_modifications",
    "read_state",
    "record_custom_modification",
    "record_skill_application",
    "write_state",
    # structured
    "are_ranges_compatible",
    "merge_docker_compose_services",
    "merge_env_additions",
    "merge_npm_dependencies",
    "run_npm_install",
    # types
    "AppliedSkill",
    "ApplyResult",
    "CustomModification",
    "FileInputHashes",
    "FileOperation",
    "FileOpsResult",
    "MergeResult",
    "RebaseResult",
    "ResolutionMeta",
    "SkillManifest",
    "SkillState",
    "UninstallResult",
    "UpdatePreview",
    "UpdateResult",
    # uninstall
    "uninstall_skill",
    # update
    "apply_update",
    "preview_update",
]
