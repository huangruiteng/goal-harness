from __future__ import annotations

import json
from pathlib import Path

from loopx.cli import main


def _connected_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    registry = project / ".loopx" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{}\n", encoding="utf-8")
    return project


def test_project_skill_cli_installs_multiple_host_surfaces(
    tmp_path: Path,
    capsys,
) -> None:
    project = _connected_project(tmp_path)
    common = [
        "--project",
        str(project),
        "--skill",
        "loopx-material",
        "--surface",
        "codex",
        "--surface",
        "claude-code",
        "--surface",
        "opencode",
        "--format",
        "json",
    ]

    assert main(["project-skill", "install", *common]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["mode"] == "preview"
    assert preview["changed"] is True
    assert all(item["status"] == "missing" for item in preview["surfaces"])

    assert main(["project-skill", "install", *common, "--execute"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["status"] == "current"
    assert all(item["status"] == "current" for item in applied["surfaces"])

    assert main(["project-skill", "status", *common]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["managed"] is True

    assert main(["project-skill", "uninstall", *common, "--execute"]) == 0
    removed = json.loads(capsys.readouterr().out)
    assert removed["status"] == "missing"
