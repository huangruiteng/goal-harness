from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..slash_commands import build_slash_command_catalog
from .claude_code import install_claude_code
from .codex import install_codex
from .command_content import _command_prompt_specs
from .opencode import install_opencode
from .pi import _pi_extension_path, _pi_runtime_path, install_pi

SCHEMA_VERSION = "loopx_slash_command_install_v0"


def _codex_home(value: str | None = None) -> Path:
    raw = value or os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(raw).expanduser()


def _claude_home(value: str | None = None) -> Path:
    raw = value or os.environ.get("CLAUDE_HOME") or str(Path.home() / ".claude")
    return Path(raw).expanduser()


def _opencode_home(value: str | None = None) -> Path:
    raw = value or os.environ.get("OPENCODE_CONFIG_DIR")
    if not raw:
        config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        raw = str(Path(config_home) / "opencode")
    return Path(raw).expanduser()


def _normalize_surfaces(surfaces: list[str] | None) -> list[str]:
    requested = surfaces or ["all"]
    normalized: list[str] = []
    for surface in requested:
        if surface == "all":
            candidates = ["codex", "claude-code", "opencode"]
        elif surface == "codex":
            candidates = ["codex"]
        elif surface in {
            "codex-app",
            "codex-app-ssh",
            "codex-ide-plugin",
            "codex-ide",
            "codex-cli",
        }:
            candidates = ["codex"]
        else:
            candidates = [surface]
        for candidate in candidates:
            if candidate not in normalized:
                normalized.append(candidate)
    return normalized


def install_slash_commands(
    *,
    execute: bool,
    uninstall: bool = False,
    with_goal_bridge: bool = False,
    surfaces: list[str] | None = None,
    cli_bin: str = "loopx",
    include_legacy_aliases: bool = True,
    codex_home: str | None = None,
    claude_home: str | None = None,
    opencode_home: str | None = None,
    pi_project: str | None = None,
) -> dict[str, Any]:
    specs = _command_prompt_specs(
        cli_bin=cli_bin, include_legacy_aliases=include_legacy_aliases
    )
    effective_surfaces = _normalize_surfaces(surfaces)
    codex_root = _codex_home(codex_home)
    claude_root = _claude_home(claude_home)
    opencode_root = _opencode_home(opencode_home)
    pi_project_root = Path(pi_project or ".").expanduser().resolve()
    installed: list[dict[str, Any]] = []
    if with_goal_bridge and "opencode" not in effective_surfaces:
        installed.append(
            {
                "surface": "opencode",
                "host_surfaces": ["opencode"],
                "mechanism": "opencode_goal_bridge",
                "command": "/goal",
                "path": None,
                "status": "blocked_goal_bridge_requires_opencode_surface",
                "invoke_as": [],
                "reason": "Select --surface opencode when using --with-goal-bridge.",
            }
        )
    if "codex" in effective_surfaces:
        install_codex(
            installed=installed,
            specs=specs,
            root=codex_root,
            execute=execute,
            uninstall=uninstall,
        )
    if "claude-code" in effective_surfaces:
        install_claude_code(
            installed=installed,
            specs=specs,
            root=claude_root,
            execute=execute,
            uninstall=uninstall,
        )
    if "opencode" in effective_surfaces:
        install_opencode(
            installed=installed,
            specs=specs,
            root=opencode_root,
            execute=execute,
            uninstall=uninstall,
            with_goal_bridge=with_goal_bridge,
        )
    if "pi" in effective_surfaces:
        install_pi(
            installed=installed,
            project_root=pi_project_root,
            execute=execute,
            uninstall=uninstall,
        )

    status_counts: dict[str, int] = {}
    for item in installed:
        status = str(item["status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "ok": not any(status.startswith("blocked_") for status in status_counts),
        "schema_version": SCHEMA_VERSION,
        "operation": "uninstall" if uninstall else "install",
        "execute": execute,
        "with_goal_bridge": with_goal_bridge,
        "requested_surfaces": surfaces or ["all"],
        "effective_surfaces": effective_surfaces,
        "catalog_schema_version": build_slash_command_catalog(
            cli_bin=cli_bin,
            include_legacy_aliases=include_legacy_aliases,
        )["schema_version"],
        "summary": {
            "codex_prompt_dir": None,
            "codex_skill_dir": str(codex_root / "skills")
            if "codex" in effective_surfaces
            else None,
            "claude_skill_dir": str(claude_root / "skills")
            if "claude-code" in effective_surfaces
            else None,
            "opencode_command_dir": str(opencode_root / "commands")
            if "opencode" in effective_surfaces
            else None,
            "opencode_plugin_path": str(opencode_root / "plugins" / "loopx-goal.js")
            if "opencode" in effective_surfaces and with_goal_bridge
            else None,
            "opencode_package_path": str(opencode_root / "package.json")
            if "opencode" in effective_surfaces and with_goal_bridge
            else None,
            "pi_extension_path": str(_pi_extension_path(pi_project_root))
            if "pi" in effective_surfaces
            else None,
            "pi_runtime_path": str(_pi_runtime_path(pi_project_root))
            if "pi" in effective_surfaces
            else None,
            "status_counts": status_counts,
            "skip_policy": (
                "Uninstall removes only LoopX-managed files; user files without a LoopX managed marker are preserved"
                if uninstall
                else "LoopX-managed files are upgraded; same-name user files without a LoopX managed marker or legacy signature are never overwritten"
            ),
        },
        "installed": installed,
        "notes": [
            "Codex does not currently support user-defined native top-level slash commands; use explicit skill invocation through `$loopx` or `/skills`.",
            "Explicit LoopX command-facade skills use agents/openai.yaml policy allow_implicit_invocation=false and remain distinct from richer workflow skills such as loopx-project.",
            "Claude Code discovers user skills from CLAUDE_HOME/skills and exposes each skill name as a slash command.",
            "The default all surface installs only OpenCode's static command facade; the executable goal bridge requires --with-goal-bridge.",
            "The Pi surface is opt-in and installs the self-contained goal extension and its loop runtime into the project's .pi/extensions/; it is not part of the default all surface.",
            "The OpenCode goal bridge uses Bun-managed config-directory dependencies and must replace any direct goal-plugin registration.",
            "OpenCode bridge uninstall preserves package.json dependencies because they may be shared by user-owned local plugins.",
            "Uninstall is fail-closed: it retires only files carrying the LoopX managed marker and leaves user-owned files in place.",
        ],
    }


def render_slash_command_install_markdown(payload: dict[str, Any]) -> str:
    operation = str(payload.get("operation") or "install")
    lines = [
        "# LoopX Slash Command Uninstall"
        if operation == "uninstall"
        else "# LoopX Slash Command Install",
        "",
        f"- operation: `{operation}`",
        f"- execute: `{payload.get('execute')}`",
        f"- surfaces: `{','.join(payload.get('effective_surfaces') or [])}`",
        f"- skip policy: `{payload.get('summary', {}).get('skip_policy')}`",
    ]
    codex_prompt_dir = payload.get("summary", {}).get("codex_prompt_dir")
    codex_skill_dir = payload.get("summary", {}).get("codex_skill_dir")
    claude_skill_dir = payload.get("summary", {}).get("claude_skill_dir")
    opencode_command_dir = payload.get("summary", {}).get("opencode_command_dir")
    opencode_plugin_path = payload.get("summary", {}).get("opencode_plugin_path")
    if codex_prompt_dir:
        lines.append(f"- codex prompts: `{codex_prompt_dir}`")
    if codex_skill_dir:
        lines.append(f"- codex skills: `{codex_skill_dir}`")
    if claude_skill_dir:
        lines.append(f"- claude skills: `{claude_skill_dir}`")
    if opencode_command_dir:
        lines.append(f"- opencode commands: `{opencode_command_dir}`")
    if opencode_plugin_path:
        lines.append(f"- opencode bridge: `{opencode_plugin_path}`")
    pi_extension_path = payload.get("summary", {}).get("pi_extension_path")
    if pi_extension_path:
        lines.append(f"- pi extension: `{pi_extension_path}`")
    pi_runtime_path = payload.get("summary", {}).get("pi_runtime_path")
    if pi_runtime_path:
        lines.append(f"- pi loop runtime: `{pi_runtime_path}`")
    counts = payload.get("summary", {}).get("status_counts") or {}
    if isinstance(counts, dict) and counts:
        count_text = ", ".join(
            f"{key}={value}" for key, value in sorted(counts.items())
        )
        lines.append(f"- statuses: `{count_text}`")
    skipped = [
        item
        for item in payload.get("installed") or []
        if isinstance(item, dict) and item.get("status") == "skipped_user_file"
    ]
    if skipped:
        lines.append("")
        lines.append("Skipped user-owned files:")
        for item in skipped:
            lines.append(f"- `{item.get('command')}` at `{item.get('path')}`")
    notes = [note for note in payload.get("notes") or [] if isinstance(note, str)]
    if notes:
        lines.append("")
        lines.append("Notes:")
        for note in notes:
            lines.append(f"- {note}")
    lines.append("")
    lines.append("Restart the host if its slash-command menu was already open.")
    return "\n".join(lines)
