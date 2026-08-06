from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from loopx.agent_onboarding import (
    _project_skill_surface,
    _start_instruction,
    build_agent_onboarding_packet,
)


def _run_cli(
    *args: str,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loopx.cli", "--format", "json", *args],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=True,
    )


def _connected_project(root: Path, goal_id: str = "pi-host-goal") -> tuple[Path, Path]:
    project = root / "project"
    registry_path = project / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": goal_id,
                        "domain": "test",
                        "status": "active",
                        "repo": str(project),
                        "adapter": {
                            "kind": "generic_project_goal_v0",
                            "status": "connected",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return project, registry_path


def test_pi_onboarding_install_command_executes_from_another_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("LOOPX_SKILLS_DIR", raising=False)
    project, _ = _connected_project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    onboard = _run_cli(
        "agent-onboard",
        "--agent-type",
        "pi",
        "--project",
        str(project),
        "--goal-id",
        "pi-host-goal",
        cwd=outside,
    )
    assert onboard.returncode == 0, onboard.stderr
    payload = json.loads(onboard.stdout)
    facade = payload["commands"]["install_command_facade"]
    assert facade is not None
    assert "--surface pi" in facade
    assert f"--pi-project {shlex.quote(str(project.resolve()))}" in facade
    assert "--project" not in facade.split()

    # Execute the exact setup command returned by agent-onboard, still from a
    # cwd that is not the target project: it must parse and land in the
    # project's .pi/extensions/, never in the caller's cwd.
    tokens = shlex.split(facade)
    assert tokens[0] == "loopx"
    install = _run_cli(*tokens[1:], cwd=outside)
    assert install.returncode == 0, install.stderr
    result = json.loads(install.stdout)
    assert result["ok"] is True
    assert (project / ".pi" / "extensions" / "loopx-goal.ts").is_file()
    assert (project / ".pi" / "extensions" / "pi-goal-loop-runtime.mjs").is_file()
    assert not (outside / ".pi" / "extensions" / "loopx-goal.ts").exists()


def test_pi_project_skill_surface_is_surface_managed(monkeypatch) -> None:
    monkeypatch.delenv("LOOPX_SKILLS_DIR", raising=False)
    assert _project_skill_surface("pi") == "pi"
    instruction = _start_instruction("pi")
    assert "`/loopx <task>`" in instruction
    assert "loopx_goal_activate" in instruction
    assert "heartbeat task body" in instruction


def test_pi_onboarding_renders_project_skill_commands_with_change_quality(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("LOOPX_SKILLS_DIR", raising=False)
    project, registry_path = _connected_project(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["goals"][0]["control_plane"] = {
        "change_quality_qualification": {
            "enabled": True,
            "safe_fix": True,
            "strict_receipt": True,
        }
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    payload = build_agent_onboarding_packet(
        project=project,
        agent_type="pi",
        goal_id="pi-host-goal",
        cli_bin="loopx",
    )

    delivery = payload["skill_delivery"]
    assert delivery["mode"] == "surface_managed"
    assert "loopx-change-quality" in delivery["active_project_skill_ids"]
    commands = delivery["project_skill_commands"]
    assert commands, delivery
    assert all(item["surface"] == "pi" for item in commands), commands
