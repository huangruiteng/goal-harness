from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote
import webbrowser


CHAT_CAPABILITIES_PATH = "/api/chat/capabilities"
DASHBOARD_CHAT_PATH = "/chat/"
EXPECTED_CHAT_SCHEMA_VERSION = "loopx_chat_capabilities_v1"
CHAT_PROBE_TIMEOUT_SECONDS = 0.75
MAX_PROBE_RESPONSE_BYTES = 1024 * 1024


def dashboard_release_root() -> Path:
    configured_root = os.environ.get("LOOPX_RELEASE_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def default_packaged_assets_dir() -> Path:
    return Path(__file__).resolve().parent / "web" / "chat"


def _probe_existing_chat(host: str, port: int) -> str:
    """Return whether the target port already serves LoopX Chat.

    The result is one of ``matching`` (a LoopX Chat v1 service is running),
    ``foreign`` (some other process owns the port), or ``unavailable`` (the
    port is free). Only the exact top-level capability fingerprint is
    accepted so a mismatched frontend/backend pair is never silently reused.
    """
    try:
        connection = http.client.HTTPConnection(
            host,
            port,
            timeout=CHAT_PROBE_TIMEOUT_SECONDS,
        )
        try:
            connection.request(
                "GET",
                CHAT_CAPABILITIES_PATH,
                headers={"Connection": "close"},
            )
            response = connection.getresponse()
            payload = response.read(MAX_PROBE_RESPONSE_BYTES)
            status = response.status
        finally:
            connection.close()
    except ConnectionRefusedError:
        return "unavailable"
    except (OSError, http.client.HTTPException):
        return "foreign"
    if status != 200:
        return "foreign"
    try:
        capabilities = json.loads(payload)
    except (UnicodeDecodeError, ValueError):
        return "foreign"
    if not isinstance(capabilities, dict):
        return "foreign"
    if (
        capabilities.get("ok") is not True
        or capabilities.get("schema_version") != EXPECTED_CHAT_SCHEMA_VERSION
    ):
        return "foreign"
    return "matching"


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

    existing_chat = _probe_existing_chat(host, port)
    if existing_chat == "matching":
        url = f"http://{host}:{port}{DASHBOARD_CHAT_PATH}"
        if goal_id:
            url = f"{url}?goalId={quote(goal_id, safe='')}"
        print(f"Reusing existing LoopX Chat service at {url}", flush=True)
        if open_browser:
            webbrowser.open(url)
        return 0
    if existing_chat == "foreign":
        raise RuntimeError(
            f"port {port} is already used by a service that is not LoopX Chat; "
            "stop that service or start LoopX on another port with --port."
        )

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
