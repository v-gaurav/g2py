"""Run CI tests for overlapping skill combinations.

For each overlapping pair of skills, copies the project to a temp directory,
applies the skills in sequence, and runs the skill test suite.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from generate_ci_matrix import MatrixEntry, generate_matrix


@dataclass
class TestResult:
    entry: MatrixEntry
    passed: bool
    error: str | None = None


EXCLUDE_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "data",
    "store",
    "logs",
    ".g2",
}


def copy_dir_recursive(
    src: Path,
    dest: Path,
    exclude: set[str] | None = None,
) -> None:
    if exclude is None:
        exclude = set()
    dest.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name in exclude:
            continue
        dest_path = dest / entry.name
        if entry.is_dir():
            copy_dir_recursive(entry, dest_path, exclude)
        else:
            shutil.copy2(entry, dest_path)


def run_matrix_entry(project_root: Path, entry: MatrixEntry) -> TestResult:
    tmp_dir = Path(tempfile.mkdtemp(prefix="g2-ci-"))

    try:
        # Copy project to temp dir (exclude heavy/irrelevant dirs)
        copy_dir_recursive(project_root, tmp_dir, EXCLUDE_DIRS)

        # Install dependencies
        subprocess.run(
            ["uv", "sync"],
            cwd=tmp_dir,
            capture_output=True,
            timeout=120,
            check=True,
        )

        # Initialize g2 dir
        subprocess.run(
            ["uv", "run", "python", "-c", "from skills_engine.init import init_g2_dir; init_g2_dir()"],
            cwd=tmp_dir,
            capture_output=True,
            timeout=30,
            check=True,
        )

        # Apply each skill in sequence
        for skill_name in entry.skills:
            skill_dir = tmp_dir / ".claude" / "skills" / skill_name
            if not skill_dir.exists():
                return TestResult(
                    entry=entry,
                    passed=False,
                    error=f"Skill directory not found: {skill_name}",
                )

            result = subprocess.run(
                ["uv", "run", "python", "scripts/apply_skill.py", str(skill_dir)],
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return TestResult(
                    entry=entry,
                    passed=False,
                    error=f"Failed to apply skill {skill_name}: {result.stdout}",
                )

        # Run all skill tests
        subprocess.run(
            ["uv", "run", "pytest", "--config-file=pytest.skills.ini"],
            cwd=tmp_dir,
            capture_output=True,
            timeout=300,
            check=True,
        )

        return TestResult(entry=entry, passed=True)
    except subprocess.CalledProcessError as err:
        return TestResult(
            entry=entry,
            passed=False,
            error=str(err),
        )
    except subprocess.TimeoutExpired as err:
        return TestResult(
            entry=entry,
            passed=False,
            error=f"Timeout: {err}",
        )
    except Exception as err:
        return TestResult(
            entry=entry,
            passed=False,
            error=str(err),
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    project_root = Path.cwd()
    skills_dir = project_root / ".claude" / "skills"
    matrix = generate_matrix(skills_dir)

    if not matrix:
        print("No overlapping skills found. Nothing to test.")
        sys.exit(0)

    print(f"Found {len(matrix)} overlapping skill combination(s):\n")
    for entry in matrix:
        print(f"  [{', '.join(entry.skills)}] -- {entry.reason}")
    print("")

    results: list[TestResult] = []
    for entry in matrix:
        print(f"Testing: [{', '.join(entry.skills)}]...")
        result = run_matrix_entry(project_root, entry)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        suffix = f" -- {result.error}" if result.error else ""
        print(f"  {status}{suffix}")

    print("\n--- Summary ---")
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    print(f"{passed} passed, {failed} failed out of {len(results)} combination(s)")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"Fatal error: {err}", file=sys.stderr)
        sys.exit(1)
