from __future__ import annotations

import json
from pathlib import Path

from loopx.bootstrap import bootstrap_project, derive_public_goal_display_name
from loopx.bootstrap_command_pack import build_start_goal_guided_packet


def test_derive_public_goal_display_name_prefers_explicit_override() -> None:
    assert derive_public_goal_display_name(
        "Fix scheduler state path override problem",
        explicit="Fix scheduler override",
    ) == "Fix scheduler override"


def test_derive_public_goal_display_name_rejects_local_paths() -> None:
    assert (
        derive_public_goal_display_name(
            "Repair /Users/example/project/.loopx/registry drift"
        )
        is None
    )


def test_bootstrap_project_persists_display_name_from_objective(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry_path = project / ".loopx" / "registry.json"
    objective = "Fix guided start goal title for dashboard projection"

    result = bootstrap_project(
        project=project,
        registry_path=registry_path,
        runtime_root=tmp_path / "runtime",
        goal_id="display-name-goal",
        objective=objective,
        domain="project-goal-control-plane",
        role="controller",
        parent_goal_id=None,
        state_file=None,
        goal_doc=None,
        adapter_kind="generic_project_goal_v0",
        adapter_status="connected",
        next_probe=None,
        spawn_allowed=False,
        max_children=0,
        allowed_domains=[],
        write_scope=[],
        onboarding_scan_enabled=False,
        force=False,
        dry_run=False,
        sync_global=False,
    )

    assert result["ok"] is True
    assert result["display_name"] == objective
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    goal = next(item for item in registry["goals"] if item["id"] == "display-name-goal")
    assert goal["display_name"] == objective


def test_guided_start_connect_command_includes_display_name(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state_file = project / ".codex" / "goals" / "guided-goal" / "ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("# Active Goal State\n", encoding="utf-8")
    registry = project / ".loopx" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": "guided-goal",
                        "status": "active",
                        "repo": str(project),
                        "state_file": ".codex/goals/guided-goal/ACTIVE_GOAL_STATE.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    goal_text = "Repair dashboard goal title fallback"
    payload = build_start_goal_guided_packet(
        project=project,
        goal_id="guided-goal",
        agent_id="cursor-display-name-agent",
        cli_bin="loopx",
        host_surface="cursor-agent",
        goal_text=goal_text,
    )
    connect_command = payload["guided_transaction"]["ordered_steps"][1]["command"]
    assert "--display-name" in connect_command
    assert goal_text in connect_command
