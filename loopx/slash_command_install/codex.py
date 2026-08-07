from __future__ import annotations

from pathlib import Path
from typing import Any

from .command_content import _command_skill_content, _openai_skill_metadata
from .managed_files import _retire_managed_file, _retire_status, _target_status


def install_codex(
    *,
    installed: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    root: Path,
    execute: bool,
    uninstall: bool,
) -> None:
    prompt_dir = root / "prompts"
    for spec in specs:
        prompt_path = prompt_dir / f"{spec['name']}.md"
        if uninstall:
            retire_status = _retire_status(prompt_path, execute=execute)
            installed.append(
                {
                    "surface": "codex",
                    "host_surfaces": [
                        "codex-cli",
                        "codex-ide-plugin",
                        "codex-app",
                        "codex-app-ssh",
                    ],
                    "mechanism": "retired_codex_custom_prompt",
                    "command": spec["command"],
                    "path": str(prompt_path),
                    "status": retire_status,
                    "invoke_as": [],
                }
            )
            continue
        retire_status = _retire_managed_file(prompt_path, execute=execute)
        if retire_status:
            installed.append(
                {
                    "surface": "codex",
                    "host_surfaces": [
                        "codex-cli",
                        "codex-ide-plugin",
                        "codex-app",
                        "codex-app-ssh",
                    ],
                    "mechanism": "retired_codex_custom_prompt",
                    "command": spec["command"],
                    "path": str(prompt_path),
                    "status": retire_status,
                    "invoke_as": [],
                }
            )

    skill_dir = root / "skills"
    for spec in specs:
        skill_path = skill_dir / str(spec["name"]) / "SKILL.md"
        metadata_path = skill_path.parent / "agents" / "openai.yaml"
        if uninstall:
            skill_status = _retire_status(skill_path, execute=execute)
            installed.append(
                {
                    "surface": "codex",
                    "host_surfaces": [
                        "codex-cli",
                        "codex-ide-plugin",
                        "codex-app",
                        "codex-app-ssh",
                    ],
                    "mechanism": "codex_explicit_skills",
                    "command": spec["command"],
                    "path": str(skill_path),
                    "status": skill_status,
                    "invoke_as": [f"${spec['name']}", "/skills"],
                }
            )
            metadata_status = _retire_status(metadata_path, execute=execute)
            installed.append(
                {
                    "surface": "codex",
                    "host_surfaces": [
                        "codex-cli",
                        "codex-ide-plugin",
                        "codex-app",
                        "codex-app-ssh",
                    ],
                    "mechanism": "codex_skill_openai_metadata",
                    "command": spec["command"],
                    "path": str(metadata_path),
                    "status": metadata_status,
                    "invoke_as": [f"${spec['name']}", "/skills"],
                }
            )
            continue
        skill_content = _command_skill_content(spec, surface="codex-skills")
        skill_status = _target_status(skill_path, skill_content, execute=execute)
        installed.append(
            {
                "surface": "codex",
                "host_surfaces": [
                    "codex-cli",
                    "codex-ide-plugin",
                    "codex-app",
                    "codex-app-ssh",
                ],
                "mechanism": "codex_explicit_skills",
                "command": spec["command"],
                "path": str(skill_path),
                "status": skill_status,
                "invoke_as": [f"${spec['name']}", "/skills"],
            }
        )
        if skill_status not in {"skipped_user_file", "preserved_existing_loopx_skill"}:
            display_name = (
                "LoopX" if spec["command"] == "/loopx" else f"LoopX {spec['command']}"
            )
            metadata = _openai_skill_metadata(
                command=str(spec["command"]),
                display_name=display_name,
                short_description=str(spec["description"]),
            )
            metadata_status = _target_status(metadata_path, metadata, execute=execute)
            installed.append(
                {
                    "surface": "codex",
                    "host_surfaces": [
                        "codex-cli",
                        "codex-ide-plugin",
                        "codex-app",
                        "codex-app-ssh",
                    ],
                    "mechanism": "codex_skill_openai_metadata",
                    "command": spec["command"],
                    "path": str(metadata_path),
                    "status": metadata_status,
                    "invoke_as": [f"${spec['name']}", "/skills"],
                }
            )
        elif skill_status in {"skipped_user_file", "preserved_existing_loopx_skill"}:
            retire_status = _retire_managed_file(metadata_path, execute=execute)
            if retire_status:
                installed.append(
                    {
                        "surface": "codex",
                        "host_surfaces": [
                            "codex-cli",
                            "codex-ide-plugin",
                            "codex-app",
                            "codex-app-ssh",
                        ],
                        "mechanism": "retired_codex_command_metadata",
                        "command": spec["command"],
                        "path": str(metadata_path),
                        "status": retire_status,
                        "invoke_as": [],
                    }
                )
    for spec in specs:
        installed.append(
            {
                "surface": "codex",
                "host_surfaces": ["codex-cli"],
                "mechanism": "unsupported_native_slash_registry",
                "command": spec["command"],
                "path": None,
                "status": "unsupported_host_surface",
                "invoke_as": [],
                "reason": (
                    "Current Codex does not support user-defined native top-level slash "
                    "commands. Use explicit skills instead."
                ),
                "native_registry_supported": False,
                "failure_policy": "fail_closed_to_explicit_skill",
                "fallback": (
                    f"Use `${spec['name']}` or `/skills` to explicitly invoke the LoopX "
                    "command skill; for the visible TUI loop, run "
                    "`loopx codex-cli-bootstrap-message --project .`, paste the setup "
                    "message, then set `/goal <thin task_body>`."
                ),
            }
        )
