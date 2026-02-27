"""Structured merge operations for npm dependencies, env files, and docker-compose."""

from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path


def _compare_version_parts(a: list[str], b: list[str]) -> int:
    """Compare two split version part lists numerically."""
    length = max(len(a), len(b))
    for i in range(length):
        a_num = int(a[i]) if i < len(a) else 0
        b_num = int(b[i]) if i < len(b) else 0
        if a_num != b_num:
            return a_num - b_num
    return 0


def are_ranges_compatible(
    existing: str,
    requested: str,
) -> dict[str, bool | str]:
    """Check if two npm version ranges are compatible.

    Returns a dict with 'compatible' (bool) and 'resolved' (str).
    """
    if existing == requested:
        return {"compatible": True, "resolved": existing}

    # Both start with ^
    if existing.startswith("^") and requested.startswith("^"):
        e_parts = existing[1:].split(".")
        r_parts = requested[1:].split(".")
        if e_parts[0] != r_parts[0]:
            return {"compatible": False, "resolved": existing}
        # Same major -- take the higher version
        resolved = existing if _compare_version_parts(e_parts, r_parts) >= 0 else requested
        return {"compatible": True, "resolved": resolved}

    # Both start with ~
    if existing.startswith("~") and requested.startswith("~"):
        e_parts = existing[1:].split(".")
        r_parts = requested[1:].split(".")
        if e_parts[0] != r_parts[0] or (len(e_parts) > 1 and len(r_parts) > 1 and e_parts[1] != r_parts[1]):
            return {"compatible": False, "resolved": existing}
        # Same major.minor -- take higher patch
        resolved = existing if _compare_version_parts(e_parts, r_parts) >= 0 else requested
        return {"compatible": True, "resolved": resolved}

    # Mismatched prefixes or anything else (exact, >=, *, etc.)
    return {"compatible": False, "resolved": existing}


def merge_npm_dependencies(
    package_json_path: Path,
    new_deps: dict[str, str],
) -> None:
    """Merge new npm dependencies into an existing package.json."""
    content = package_json_path.read_text()
    pkg = json.loads(content)

    dependencies: dict[str, str] = pkg.get("dependencies") or {}
    pkg["dependencies"] = dependencies

    dev_dependencies: dict[str, str] | None = pkg.get("devDependencies")

    for name, version in new_deps.items():
        # Check both dependencies and devDependencies to avoid duplicates
        existing = dependencies.get(name)
        if existing is None and dev_dependencies is not None:
            existing = dev_dependencies.get(name)
        if existing and existing != version:
            result = are_ranges_compatible(existing, version)
            if not result["compatible"]:
                raise ValueError(f"Dependency conflict: {name} is already at {existing}, skill wants {version}")
            dependencies[name] = str(result["resolved"])
        else:
            dependencies[name] = version

    # Sort dependencies for deterministic output
    pkg["dependencies"] = dict(sorted(dependencies.items()))

    if dev_dependencies is not None:
        pkg["devDependencies"] = dict(sorted(dev_dependencies.items()))

    package_json_path.write_text(json.dumps(pkg, indent=2) + "\n")


def merge_env_additions(
    env_example_path: Path,
    additions: list[str],
) -> None:
    """Merge new environment variable declarations into an .env.example file."""
    content = ""
    if env_example_path.exists():
        content = env_example_path.read_text()

    existing_vars: set[str] = set()
    for line in content.split("\n"):
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        if match:
            existing_vars.add(match.group(1))

    new_vars = [v for v in additions if v not in existing_vars]
    if not new_vars:
        return

    if content and not content.endswith("\n"):
        content += "\n"
    content += "\n# Added by skill\n"
    for v in new_vars:
        content += f"{v}=\n"

    env_example_path.write_text(content)


def _extract_host_port(port_mapping: str) -> str | None:
    """Extract the host port from a docker-compose port mapping string."""
    parts = str(port_mapping).split(":")
    if len(parts) >= 2:
        return parts[0]
    return None


def merge_docker_compose_services(
    compose_path: Path,
    services: dict[str, object],
) -> None:
    """Merge new services into a docker-compose file, checking for port collisions."""
    if compose_path.exists():
        content = compose_path.read_text()
        compose: dict[str, object] = yaml.safe_load(content) or {}
    else:
        compose = {"version": "3"}

    existing_services: dict[str, object] = compose.get("services") or {}
    compose["services"] = existing_services

    # Collect host ports from existing services
    used_ports: set[str] = set()
    for svc in existing_services.values():
        service = svc if isinstance(svc, dict) else {}
        ports = service.get("ports")
        if isinstance(ports, list):
            for p in ports:
                host = _extract_host_port(str(p))
                if host:
                    used_ports.add(host)

    # Add new services, checking for port collisions
    for name, definition in services.items():
        if name in existing_services:
            continue  # skip existing

        svc = definition if isinstance(definition, dict) else {}
        ports = svc.get("ports")
        if isinstance(ports, list):
            for p in ports:
                host = _extract_host_port(str(p))
                if host and host in used_ports:
                    raise ValueError(f'Port collision: host port {host} from service "{name}" is already in use')
                if host:
                    used_ports.add(host)

        existing_services[name] = definition

    compose_path.write_text(yaml.dump(compose, default_flow_style=False))


def run_npm_install() -> None:
    """Run npm install with legacy peer deps in the current working directory."""
    subprocess.run(
        ["npm", "install", "--legacy-peer-deps"],
        check=True,
    )
