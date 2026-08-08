from __future__ import annotations

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
