from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Mapping, Sequence


def resolve_command_path(
    name: str,
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path | None:
    """Resolve executables plus PowerShell scripts discoverable by PowerShell 7."""

    source_env = os.environ if env is None else env
    explicit = source_env.get("LOOPX_COMMAND_PATH") if name == "loopx" else None
    if os.name == "nt" and explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.is_file():
            return explicit_path
    if os.name != "nt":
        resolved = shutil.which(name, path=source_env.get("PATH"))
        return Path(resolved).expanduser() if resolved else None

    # Preserve PATH directory precedence across native executables and .ps1
    # launchers. A single global ``which`` would find a later loopx.exe before
    # considering an earlier loopx.ps1, unlike PowerShell command discovery.
    for entry in source_env.get("PATH", "").split(os.pathsep):
        normalized = entry.strip().strip('"')
        if not normalized:
            continue
        directory = Path(normalized).expanduser()
        resolved = shutil.which(name, path=str(directory))
        if resolved:
            return Path(resolved).expanduser()
        powershell_script = directory / f"{name}.ps1"
        if powershell_script.is_file():
            return powershell_script

    fallback = (home or Path.home()) / ".local" / "bin" / f"{name}.ps1"
    return fallback if fallback.is_file() else None


def command_argv(
    command_path: Path,
    args: Sequence[str],
    *,
    pwsh: str | None = None,
) -> list[str]:
    """Build a subprocess argv for native executables or PowerShell scripts."""

    if command_path.suffix.lower() != ".ps1":
        return [str(command_path), *args]
    powershell = pwsh or shutil.which("pwsh")
    if not powershell:
        raise FileNotFoundError("PowerShell 7 executable `pwsh` was not found on PATH")
    return [
        powershell,
        "-NoLogo",
        "-NoProfile",
        "-File",
        str(command_path),
        *args,
    ]
