from __future__ import annotations

from pathlib import Path

from loopx.codex_cli_probe import classify_codex_cli_session_surface
from loopx.codex_cli_scheduler import build_codex_cli_local_scheduler_tick
from loopx.control_plane.effect_program import effect_program_from_ordered_steps

PROJECT = Path("/tmp/public-codex-cli-project")
GOAL_ID = "public-codex-cli-goal"
AGENT_ID = "codex-side-bypass"

FALLBACK_HELP_FIXTURE = {
    "root": """
Usage: codex [OPTIONS] [PROMPT]

Commands:
  exec      Run Codex non-interactively
  resume    Resume a previous conversation
""",
    "exec": "Usage: codex exec [OPTIONS] [PROMPT]",
    "resume": "Usage: codex resume [SESSION_ID]",
}


def test_scheduler_commands_round_trip_through_effect_program() -> None:
    payload = build_codex_cli_local_scheduler_tick(
        project=PROJECT,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        cli_bin="loopx",
        codex_bin="codex",
        probe_payload=classify_codex_cli_session_surface(
            command_outputs=FALLBACK_HELP_FIXTURE
        ),
    )
    commands = payload["commands"]

    assert set(commands) == {
        "visible_driver_run",
        "runtime_idle_detector",
        "runtime_idle_detector_fixture",
        "scheduler_tick",
        "candidate_codex_command",
        "blocker_writeback",
    }
    program = effect_program_from_ordered_steps(
        [
            {"id": step_id, "kind": "codex_cli_command", "command": command}
            for step_id, command in commands.items()
            if command
        ],
        execution_mode="serial",
    )
    assert program.execution_mode == "serial"
    assert {step.step_id: step.command for step in program.steps} == {
        step_id: command
        for step_id, command in commands.items()
        if command
    }
