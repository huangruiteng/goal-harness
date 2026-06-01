from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any


def user_local_bin() -> Path:
    return Path.home() / ".local" / "bin"


def collect_doctor() -> dict[str, Any]:
    command_path_text = shutil.which("goal-harness")
    command_path = Path(command_path_text).expanduser() if command_path_text else None
    command_realpath = command_path.resolve() if command_path else None
    module_path = Path(__file__).resolve()
    package_dir = module_path.parent
    repo_root = package_dir.parent
    install_script = repo_root / "scripts" / "install-local.sh"
    wrapper_script = repo_root / "scripts" / "goal-harness"
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    local_bin = user_local_bin()
    checks = [
        {
            "id": "command_on_path",
            "required": True,
            "ok": command_path is not None,
            "detail": str(command_path) if command_path else "goal-harness was not found on PATH",
        },
        {
            "id": "command_resolves",
            "required": True,
            "ok": bool(command_realpath and command_realpath.exists()),
            "detail": str(command_realpath) if command_realpath else "no command realpath",
        },
        {
            "id": "module_importable",
            "required": True,
            "ok": module_path.exists(),
            "detail": str(module_path),
        },
        {
            "id": "install_script_exists",
            "required": False,
            "ok": install_script.exists(),
            "detail": str(install_script),
        },
        {
            "id": "wrapper_script_exists",
            "required": False,
            "ok": wrapper_script.exists(),
            "detail": str(wrapper_script),
        },
        {
            "id": "local_bin_on_path",
            "required": False,
            "ok": str(local_bin) in path_entries,
            "detail": str(local_bin),
        },
    ]
    return {
        "ok": all(check["ok"] for check in checks if check["required"]),
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "path": {
            "goal_harness": str(command_path) if command_path else None,
            "goal_harness_realpath": str(command_realpath) if command_realpath else None,
            "user_local_bin": str(local_bin),
            "user_local_bin_on_path": str(local_bin) in path_entries,
        },
        "package": {
            "module_path": str(module_path),
            "repo_root": str(repo_root),
            "install_script": str(install_script),
            "wrapper_script": str(wrapper_script),
        },
        "checks": checks,
        "fix": f"Run `{repo_root / 'scripts' / 'install-local.sh'}` and start a new shell, or export PATH=\"{local_bin}:$PATH\".",
    }


def render_doctor_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Goal Harness Doctor",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- goal_harness: `{(payload.get('path') or {}).get('goal_harness')}`",
        f"- realpath: `{(payload.get('path') or {}).get('goal_harness_realpath')}`",
        f"- user_local_bin_on_path: `{(payload.get('path') or {}).get('user_local_bin_on_path')}`",
        f"- python: `{(payload.get('python') or {}).get('executable')}`",
        "",
        "## Checks",
    ]
    for check in payload.get("checks") or []:
        required = "required" if check.get("required") else "optional"
        lines.append(f"- {check.get('id')} ({required}): `{check.get('ok')}` - {check.get('detail')}")
    if not payload.get("ok"):
        lines.extend(["", "## Fix", str(payload.get("fix"))])
    return "\n".join(lines)
