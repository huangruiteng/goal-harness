from __future__ import annotations

import os
from pathlib import Path
import subprocess


def dashboard_release_root() -> Path:
    configured_root = os.environ.get("LOOPX_RELEASE_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def launch_dashboard() -> int:
    release_root = dashboard_release_root()
    launcher = release_root / "scripts" / "dashboard-dev.sh"
    if not launcher.is_file():
        raise RuntimeError(f"LoopX dashboard launcher is missing: {launcher}")
    return subprocess.call(["bash", str(launcher)], cwd=release_root)
