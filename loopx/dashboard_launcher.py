from __future__ import annotations

import os
from pathlib import Path
import subprocess


def dashboard_release_root() -> Path:
    configured_root = os.environ.get("LOOPX_RELEASE_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def default_packaged_assets_dir() -> Path:
    return Path(__file__).resolve().parent / "web" / "chat"


def launch_dashboard(
    *,
    registry_path: Path | None = None,
    runtime_root_override: Path | None = None,
    scan_roots: list[Path] | None = None,
    limit: int = 20,
    host: str = "127.0.0.1",
    port: int = 8767,
    goal_id: str | None = None,
    codex_bin: str = "codex",
    claude_bin: str = "claude",
    lark_cli_bin: str | None = None,
    assets_dir: Path | None = None,
    verbose: bool = False,
    open_browser: bool = True,
    prefer_dev: bool = False,
) -> int:
    release_root = dashboard_release_root()
    dev_launcher = release_root / "scripts" / "dashboard-dev.sh"
    if (prefer_dev or os.environ.get("LOOPX_DASHBOARD_DEV") == "1") and dev_launcher.is_file():
        return subprocess.call(["bash", str(dev_launcher)], cwd=release_root)

    from .chat_server import serve_chat

    resolved_assets = assets_dir or default_packaged_assets_dir()
    if not (resolved_assets / "index.html").is_file():
        raise RuntimeError(
            f"LoopX dashboard web bundle is missing: {resolved_assets}. "
            "Please ensure the package is properly installed with package-data or run npm run build."
        )

    serve_chat(
        registry_path=registry_path,
        runtime_root_override=runtime_root_override,
        scan_roots=scan_roots,
        limit=limit,
        host=host,
        port=port,
        goal_id=goal_id,
        codex_bin=codex_bin,
        claude_bin=claude_bin,
        lark_cli_bin=lark_cli_bin,
        assets_dir=resolved_assets,
        verbose=verbose,
        open_browser=open_browser,
    )
    return 0
