from __future__ import annotations

from pathlib import Path
from typing import Any

from ..pi_goal_mode import extension_source as pi_extension_source
from ..pi_goal_mode import runtime_source as pi_runtime_source
from .managed_files import _retire_status, _target_status


def _pi_extension_path(project_root: Path) -> Path:
    return project_root / ".pi" / "extensions" / "loopx-goal.ts"


def _pi_runtime_path(project_root: Path) -> Path:
    return project_root / ".pi" / "extensions" / "pi-goal-loop-runtime.mjs"


def install_pi(
    *,
    installed: list[dict[str, Any]],
    project_root: Path,
    execute: bool,
    uninstall: bool,
) -> None:
    extension_path = _pi_extension_path(project_root)
    runtime_path = _pi_runtime_path(project_root)
    extension_content = pi_extension_source()
    runtime_content = pi_runtime_source()
    if uninstall:
        for mechanism, path in (
            ("pi_goal_extension", extension_path),
            ("pi_goal_extension_runtime", runtime_path),
        ):
            installed.append(
                {
                    "surface": "pi",
                    "host_surfaces": ["pi"],
                    "mechanism": mechanism,
                    "command": "/loopx",
                    "path": str(path),
                    "status": _retire_status(path, execute=execute),
                    "invoke_as": ["/loopx", "loopx_goal_activate"],
                }
            )
    else:
        # The adapter and its loop runtime are one atomic delivery unit:
        # preflight both targets and fail closed with zero writes when any
        # target is a user-owned file, so a newly created managed adapter
        # can never import an unmanaged runtime that may lack the exports
        # it needs.
        user_owned_pi_paths = [
            str(path)
            for path, content in (
                (extension_path, extension_content),
                (runtime_path, runtime_content),
            )
            if _target_status(path, content, execute=False) == "skipped_user_file"
        ]
        if user_owned_pi_paths:
            installed.append(
                {
                    "surface": "pi",
                    "host_surfaces": ["pi"],
                    "mechanism": "pi_goal_extension",
                    "command": "/loopx",
                    "path": str(extension_path),
                    "status": "blocked_user_owned_pi_file",
                    "invoke_as": ["/loopx", "loopx_goal_activate"],
                    "reason": (
                        "Move or rename the listed user-owned Pi files before "
                        "installing LoopX so the adapter and its loop runtime "
                        "are installed as one atomic unit; no Pi file was written."
                    ),
                    "conflicts": user_owned_pi_paths,
                }
            )
        else:
            for mechanism, path, content in (
                ("pi_goal_extension", extension_path, extension_content),
                ("pi_goal_extension_runtime", runtime_path, runtime_content),
            ):
                installed.append(
                    {
                        "surface": "pi",
                        "host_surfaces": ["pi"],
                        "mechanism": mechanism,
                        "command": "/loopx",
                        "path": str(path),
                        "status": _target_status(path, content, execute=execute),
                        "invoke_as": ["/loopx", "loopx_goal_activate"],
                    }
                )
