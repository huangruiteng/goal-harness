from __future__ import annotations

import json
from pathlib import Path

from loopx.bootstrap_command_pack import build_start_goal_guided_packet
from loopx.control_plane.effect_program import effect_program_from_ordered_steps


def test_ordered_steps_map_to_effect_program() -> None:
    steps = [
        {
            "id": "select_host_surface",
            "kind": "host_surface_selection_gate",
            "purpose": "select the current host before mutation",
        },
        {
            "id": "bootstrap_goal",
            "kind": "bootstrap",
            "command": "loopx start-goal --guided",
            "purpose": "connect the goal before planning",
        },
        {
            "id": "add_todo",
            "kind": "todo_add",
            "command_template": "loopx todo add --goal-id loopx-meta",
            "purpose": "record the first bounded business todo",
        },
    ]

    program = effect_program_from_ordered_steps(
        steps,
        execution_mode="serial",
    )

    assert program.execution_mode == "serial"
    assert len(program.steps) == 3
    assert program.steps[0].step_id == "select_host_surface"
    assert program.steps[0].kind == "host_surface_selection_gate"
    assert program.steps[1].command == "loopx start-goal --guided"
    assert program.steps[2].command == "loopx todo add --goal-id loopx-meta"
    assert program.steps[2].purpose == "record the first bounded business todo"


def test_ordered_steps_ignore_non_mapping_entries() -> None:
    program = effect_program_from_ordered_steps(
        [
            "not-a-step",
            {"id": "step-a", "kind": "bootstrap"},
        ]
    )

    assert len(program.steps) == 1
    assert program.steps[0].step_id == "step-a"
    assert program.steps[0].command is None


def test_real_bootstrap_ordered_steps_map_to_effect_program(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    state_file = (
        project / ".codex" / "goals" / "guided-program-goal" / "ACTIVE_GOAL_STATE.md"
    )
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
                        "id": "guided-program-goal",
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state_file.relative_to(project)),
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": ["codex-guided-program"],
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = build_start_goal_guided_packet(
        project=project,
        goal_id="guided-program-goal",
        agent_id="codex-guided-program",
        cli_bin="loopx",
        host_surface="codex-app",
        goal_text="Ship a bounded public issue triage workflow.",
        available_capabilities=["network"],
        include_command_pack_detail=False,
    )
    transaction = payload["guided_transaction"]
    program = effect_program_from_ordered_steps(
        transaction["ordered_steps"],
        execution_mode="serial",
    )

    assert program.execution_mode == "serial"
    assert program.steps
    assert program.steps[0].step_id == "inspect_connection"
    assert program.steps[0].kind == "read_only"
