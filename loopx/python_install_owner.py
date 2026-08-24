from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex


@dataclass(frozen=True)
class PythonInstallOwner:
    manager: str
    environment: str | None = None


def resolve_python_install_owner(
    *,
    default_installer: str,
    prefix: Path,
) -> PythonInstallOwner:
    """Preserve pipx ownership instead of treating its internal pip as plain pip."""

    metadata_path = prefix / "pipx_metadata.json"
    if not metadata_path.is_file():
        return PythonInstallOwner(manager=default_installer)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metadata = {}
    recorded_environment = metadata.get("environment") if isinstance(metadata, dict) else None
    environment = (
        recorded_environment
        if isinstance(recorded_environment, str) and recorded_environment
        else prefix.name
    )
    return PythonInstallOwner(manager="pipx", environment=environment)


def python_distribution_upgrade_command(
    *,
    owner: PythonInstallOwner,
    python_executable: str,
    doctor_command: str,
) -> str | None:
    if owner.manager == "pipx":
        package_command = f"pipx upgrade {shlex.quote(owner.environment or 'loopx')}"
    elif owner.manager == "pip":
        package_command = f"{shlex.quote(python_executable)} -m pip install --upgrade loopx"
    else:
        return None
    return (
        f"{package_command}\n"
        "loopx workflow-skills --install\n"
        "loopx slash-commands --install\n"
        f"{doctor_command}"
    )
