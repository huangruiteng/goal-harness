from __future__ import annotations

from pathlib import Path
from typing import Any

from .command_content import _skill_body
from .managed_files import _retire_status, _target_status


def install_claude_code(
    *,
    installed: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    root: Path,
    execute: bool,
    uninstall: bool,
) -> None:
    skills_dir = root / "skills"
    for spec in specs:
        path = skills_dir / str(spec["name"]) / "SKILL.md"
        if uninstall:
            status = _retire_status(path, execute=execute)
            installed.append(
                {
                    "surface": "claude-code",
                    "mechanism": "claude_code_skills",
                    "command": spec["command"],
                    "path": str(path),
                    "status": status,
                    "invoke_as": [str(spec["command"])],
                }
            )
            continue
        content = _skill_body(
            command=str(spec["command"]),
            title=f"LoopX {spec['command']}",
            description=str(spec["description"]),
            argument_hint=str(spec["argument_hint"]),
            instructions=list(spec["instructions"]),
            surface="claude-skills",
            front_matter_name=str(spec["name"]),
        )
        status = _target_status(path, content, execute=execute)
        installed.append(
            {
                "surface": "claude-code",
                "mechanism": "claude_code_skills",
                "command": spec["command"],
                "path": str(path),
                "status": status,
                "invoke_as": [str(spec["command"])],
            }
        )
