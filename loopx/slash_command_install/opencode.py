from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..opencode_goal_mode import plugin_source, runtime_source
from .command_content import _opencode_command_body
from .managed_files import _retire_status, _target_status

OPENCODE_GOAL_DEPENDENCIES = {
    "@opencode-ai/plugin": ">=1.17.15 <2",
    "opencode-goal-plugin": "0.7.0",
}


def _strip_jsonc_comments(content: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(content):
        char = content[index]
        next_char = content[index + 1] if index + 1 < len(content) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            output.extend((" ", " "))
            index += 2
            while index < len(content) and content[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if char == "/" and next_char == "*":
            output.extend((" ", " "))
            index += 2
            while index < len(content):
                if index + 1 < len(content) and content[index : index + 2] == "*/":
                    output.extend((" ", " "))
                    index += 2
                    break
                output.append("\n" if content[index] == "\n" else " ")
                index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _strip_jsonc_trailing_commas(content: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(content):
        char = content[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(content) and content[lookahead].isspace():
                lookahead += 1
            if lookahead < len(content) and content[lookahead] in "]}":
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _opencode_plugin_name(plugin: Any) -> str | None:
    if isinstance(plugin, str):
        return plugin
    if isinstance(plugin, list) and plugin and isinstance(plugin[0], str):
        return plugin[0]
    return None


def _opencode_direct_goal_plugin_conflicts(root: Path) -> tuple[list[str], list[str]]:
    conflicts: list[str] = []
    invalid: list[str] = []
    goal_plugins = {
        "opencode-goal-plugin",
        "@heimoshuiyu/opencode-goal-plugin",
        "@prevalentware/opencode-goal-plugin",
    }
    for name in ("opencode.json", "opencode.jsonc"):
        path = root / name
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
            if path.suffix == ".jsonc":
                content = _strip_jsonc_trailing_commas(_strip_jsonc_comments(content))
            payload = json.loads(content)
        except (json.JSONDecodeError, OSError):
            invalid.append(str(path))
            continue
        if not isinstance(payload, dict):
            invalid.append(str(path))
            continue
        plugins = payload.get("plugin") or []
        if isinstance(plugins, str):
            plugins = [plugins]
        if not isinstance(plugins, list):
            invalid.append(str(path))
            continue
        plugin_names = [
            name
            for plugin in plugins
            if (name := _opencode_plugin_name(plugin)) is not None
        ]
        if any(
            plugin == package or plugin.startswith(f"{package}@")
            for plugin in plugin_names
            for package in goal_plugins
        ):
            conflicts.append(str(path))
    return conflicts, invalid


def _target_package_dependencies(
    path: Path,
    dependencies: dict[str, str],
    *,
    execute: bool,
) -> str:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return "blocked_invalid_user_package_json"
        if not isinstance(payload, dict):
            return "blocked_invalid_user_package_json"
        current = payload.get("dependencies")
        if current is None:
            current = {}
        if not isinstance(current, dict):
            return "blocked_invalid_user_package_json"
        wanted = {**current, **dependencies}
        if wanted == current:
            return "unchanged"
        payload["dependencies"] = wanted
        status = "updated" if execute else "would_update"
    else:
        payload = {"private": True, "dependencies": dependencies}
        status = "created" if execute else "would_create"
    if execute:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    return status


def install_opencode(
    *,
    installed: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    root: Path,
    execute: bool,
    uninstall: bool,
    with_goal_bridge: bool,
) -> None:
    commands_dir = root / "commands"
    plugin_path = root / "plugins" / "loopx-goal.js"
    runtime_path = root / "loopx" / "goal-bridge-runtime.mjs"
    package_path = root / "package.json"
    plugin_content = plugin_source()
    runtime_content = runtime_source()

    bridge_preflight_blocked = False
    if with_goal_bridge and not uninstall:
        conflicts, invalid_configs = _opencode_direct_goal_plugin_conflicts(root)
        if invalid_configs:
            installed.append(
                {
                    "surface": "opencode",
                    "host_surfaces": ["opencode"],
                    "mechanism": "opencode_goal_bridge",
                    "command": "/goal",
                    "path": str(plugin_path),
                    "status": "blocked_invalid_opencode_config",
                    "invoke_as": [],
                    "reason": (
                        "Repair the listed OpenCode JSON/JSONC config before installing "
                        "the bridge so direct plugin conflicts can be checked safely."
                    ),
                    "invalid_configs": invalid_configs,
                }
            )
            bridge_preflight_blocked = True
        elif conflicts:
            installed.append(
                {
                    "surface": "opencode",
                    "host_surfaces": ["opencode"],
                    "mechanism": "opencode_goal_bridge",
                    "command": "/goal",
                    "path": str(plugin_path),
                    "status": "blocked_conflicting_direct_plugin",
                    "invoke_as": [],
                    "reason": (
                        "Remove direct goal-plugin registration from the listed "
                        "OpenCode config, then rerun installation. The bridge imports "
                        "the pinned plugin and both must not be loaded independently."
                    ),
                    "conflicts": conflicts,
                }
            )
            bridge_preflight_blocked = True
        else:
            user_owned_bridge_paths = [
                str(path)
                for path, content in (
                    (plugin_path, plugin_content),
                    (runtime_path, runtime_content),
                )
                if _target_status(path, content, execute=False) == "skipped_user_file"
            ]
            if user_owned_bridge_paths:
                installed.append(
                    {
                        "surface": "opencode",
                        "host_surfaces": ["opencode"],
                        "mechanism": "opencode_goal_bridge",
                        "command": "/goal",
                        "path": str(plugin_path),
                        "status": "blocked_user_owned_bridge_file",
                        "invoke_as": [],
                        "reason": (
                            "Move or rename the listed user-owned OpenCode bridge "
                            "files before installing LoopX so no partial bridge or "
                            "dependency update is applied."
                        ),
                        "conflicts": user_owned_bridge_paths,
                    }
                )
                bridge_preflight_blocked = True

        if not bridge_preflight_blocked:
            package_status = _target_package_dependencies(
                package_path,
                OPENCODE_GOAL_DEPENDENCIES,
                execute=False,
            )
            if package_status == "blocked_invalid_user_package_json":
                installed.append(
                    {
                        "surface": "opencode",
                        "host_surfaces": ["opencode"],
                        "mechanism": "opencode_goal_dependencies",
                        "command": "/goal",
                        "path": str(package_path),
                        "status": package_status,
                        "invoke_as": [],
                    }
                )
                bridge_preflight_blocked = True

    if with_goal_bridge and not bridge_preflight_blocked:
        if uninstall:
            for mechanism, path in (
                ("opencode_goal_bridge", plugin_path),
                ("opencode_goal_bridge_runtime", runtime_path),
            ):
                installed.append(
                    {
                        "surface": "opencode",
                        "host_surfaces": ["opencode"],
                        "mechanism": mechanism,
                        "command": "/goal",
                        "path": str(path),
                        "status": _retire_status(path, execute=execute),
                        "invoke_as": ["/goal", "loopx_goal_activate"],
                    }
                )
            installed.append(
                {
                    "surface": "opencode",
                    "host_surfaces": ["opencode"],
                    "mechanism": "opencode_goal_dependencies",
                    "command": "/goal",
                    "path": str(package_path),
                    "status": "preserved_shared_dependencies",
                    "invoke_as": [],
                }
            )
        else:
            package_status = _target_package_dependencies(
                package_path,
                OPENCODE_GOAL_DEPENDENCIES,
                execute=execute,
            )
            installed.append(
                {
                    "surface": "opencode",
                    "host_surfaces": ["opencode"],
                    "mechanism": "opencode_goal_dependencies",
                    "command": "/goal",
                    "path": str(package_path),
                    "status": package_status,
                    "invoke_as": [],
                }
            )
            if package_status == "blocked_invalid_user_package_json":
                bridge_preflight_blocked = True
            else:
                for mechanism, path, content in (
                    ("opencode_goal_bridge_runtime", runtime_path, runtime_content),
                    ("opencode_goal_bridge", plugin_path, plugin_content),
                ):
                    installed.append(
                        {
                            "surface": "opencode",
                            "host_surfaces": ["opencode"],
                            "mechanism": mechanism,
                            "command": "/goal",
                            "path": str(path),
                            "status": _target_status(path, content, execute=execute),
                            "invoke_as": ["/goal", "loopx_goal_activate"],
                        }
                    )

    if not bridge_preflight_blocked:
        for spec in specs:
            path = commands_dir / f"{spec['name']}.md"
            status = (
                _retire_status(path, execute=execute)
                if uninstall
                else _target_status(
                    path,
                    _opencode_command_body(spec),
                    execute=execute,
                )
            )
            installed.append(
                {
                    "surface": "opencode",
                    "host_surfaces": ["opencode"],
                    "mechanism": "opencode_commands",
                    "command": spec["command"],
                    "path": str(path),
                    "status": status,
                    "invoke_as": [str(spec["command"])],
                }
            )
