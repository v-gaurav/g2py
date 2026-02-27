"""Skills engine domain types."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FileOperation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["rename", "delete", "move"]
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    path: str | None = None


class SkillManifest(BaseModel):
    skill: str
    version: str
    description: str = ""
    core_version: str
    adds: list[str]
    modifies: list[str]
    structured: dict[str, Any] | None = None
    file_ops: list[FileOperation] | None = None
    conflicts: list[str]
    depends: list[str]
    test: str | None = None
    author: str | None = None
    license: str | None = None
    min_skills_system_version: str | None = None
    tested_with: list[str] | None = None
    post_apply: list[str] | None = None


class AppliedSkill(BaseModel):
    name: str
    version: str
    applied_at: str
    file_hashes: dict[str, str]
    structured_outcomes: dict[str, Any] | None = None
    custom_patch: str | None = None
    custom_patch_description: str | None = None


class CustomModification(BaseModel):
    description: str
    applied_at: str
    files_modified: list[str]
    patch_file: str


class SkillState(BaseModel):
    skills_system_version: str
    core_version: str
    applied_skills: list[AppliedSkill]
    custom_modifications: list[CustomModification] | None = None
    path_remap: dict[str, str] | None = None
    rebased_at: str | None = None


class ApplyResult(BaseModel):
    success: bool
    skill: str
    version: str
    merge_conflicts: list[str] | None = None
    backup_pending: bool | None = None
    untracked_changes: list[str] | None = None
    error: str | None = None


class MergeResult(BaseModel):
    clean: bool
    exit_code: int


class FileOpsResult(BaseModel):
    success: bool
    executed: list[FileOperation]
    warnings: list[str]
    errors: list[str]


class FileInputHashes(BaseModel):
    base: str
    current: str
    skill: str


class ResolutionMeta(BaseModel):
    skills: list[str]
    apply_order: list[str]
    core_version: str
    resolved_at: str
    tested: bool
    test_passed: bool
    resolution_source: Literal["maintainer", "user", "claude"]
    input_hashes: dict[str, str]
    output_hash: str
    file_hashes: dict[str, FileInputHashes]


class UpdatePreview(BaseModel):
    current_version: str
    new_version: str
    files_changed: list[str]
    files_deleted: list[str]
    conflict_risk: list[str]
    custom_patches_at_risk: list[str]


class UpdateResult(BaseModel):
    success: bool
    previous_version: str
    new_version: str
    merge_conflicts: list[str] | None = None
    backup_pending: bool | None = None
    custom_patch_failures: list[str] | None = None
    skill_reapply_results: dict[str, bool] | None = None
    error: str | None = None


class UninstallResult(BaseModel):
    success: bool
    skill: str
    custom_patch_warning: str | None = None
    replay_results: dict[str, bool] | None = None
    error: str | None = None


class RebaseResult(BaseModel):
    success: bool
    patch_file: str | None = None
    files_in_patch: int
    rebased_at: str | None = None
    merge_conflicts: list[str] | None = None
    backup_pending: bool | None = None
    error: str | None = None
