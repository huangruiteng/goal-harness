from __future__ import annotations

import json
import os
import subprocess
from argparse import Namespace
from pathlib import Path

from loopx.bootstrap_command_pack import build_start_goal_guided_packet
from loopx.cli_commands.start_goal import _resolve_start_goal_input
from loopx.configure_goal import configure_goal
from loopx.control_plane.goals.goal_frontier import (
    derive_goal_frontier_replan_obligation_from_summaries,
)
from loopx.control_plane.goals.goal_frontier.outcome_continuity import (
    acceptance_gaps_from_todo_completion_checkpoint,
)
from loopx.control_plane.heartbeat.builder import (
    FINE_GRAINED_TURN_RULE,
    build_heartbeat_prompt,
)
from loopx.execution_profile import (
    build_execution_profile,
    compact_execution_profile,
    execution_profile_is_fine_grained,
)
from loopx.long_task_cadence import build_long_task_cadence_hint

GOAL_ID = "fine-grained-fixture"
AGENT_ID = "codex-fine-agent"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _start_args(**overrides: object) -> Namespace:
    values: dict[str, object] = {
        "goal_text": None,
        "slash_command_arguments": None,
        "capability_route": None,
        "fine_grained": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_leading_fine_grained_switch_is_lossless_and_composes_with_route() -> None:
    assert _resolve_start_goal_input(
        _start_args(goal_text="Direct fine goal.", fine_grained=True)
    ) == ("Direct fine goal.", None, True)

    goal_text, route, fine_grained = _resolve_start_goal_input(
        _start_args(
            slash_command_arguments=(
                "--fine-grained --capability-route issue-fix "
                "Investigate  two branches without recomposing this text."
            )
        )
    )

    assert fine_grained is True
    assert route == "issue-fix"
    assert goal_text == "Investigate  two branches without recomposing this text."

    reverse = _resolve_start_goal_input(
        _start_args(
            slash_command_arguments=(
                "--capability-route=issue-fix --fine-grained Keep exact goal text."
            )
        )
    )
    assert reverse == ("Keep exact goal text.", "issue-fix", True)


def test_public_cli_accepts_direct_fine_start_and_bootstrap_flags(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = tmp_path / "registry.json"
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    started = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "loopx"),
            "--format",
            "json",
            "--registry",
            str(registry),
            "start-goal",
            "--guided",
            "--project",
            str(project),
            "--goal-id",
            GOAL_ID,
            "--host-surface",
            "ark-managed-agent",
            "--fine-grained",
            "--goal-text",
            "Deliver one checkpoint.",
        ],
        cwd=REPO_ROOT,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )
    start_payload = json.loads(started.stdout)
    assert start_payload["command_pack"]["goal_start_contract"]["turn_mode"] == (
        "fine_grained"
    )

    bootstrapped = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "loopx"),
            "--format",
            "json",
            "--registry",
            str(registry),
            "bootstrap",
            "--project",
            str(project),
            "--goal-id",
            GOAL_ID,
            "--objective",
            "Deliver one checkpoint.",
            "--fine-grained",
            "--dry-run",
            "--no-global-sync",
        ],
        cwd=REPO_ROOT,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    )
    bootstrap_payload = json.loads(bootstrapped.stdout)
    assert bootstrap_payload["execution_profile"]["turn_granularity"] == "fine"
    assert bootstrap_payload["execution_profile"]["minimum_scale"] == "single_surface"


def test_fine_profile_expects_small_checkpoints_without_widening() -> None:
    standard = build_execution_profile()
    fine = build_execution_profile(turn_granularity="fine")

    assert "turn_granularity" not in standard
    assert execution_profile_is_fine_grained(standard) is False
    assert execution_profile_is_fine_grained(compact_execution_profile(fine)) is True
    assert fine["minimum_scale"] == "single_surface"
    assert fine["degradation_policy"] == {
        "small_scale_streak_threshold": 1,
        "on_degradation": "replan_after_checkpoint",
    }
    cadence = build_long_task_cadence_hint(
        execution_profile=fine,
        latest_runs=[
            {
                "delivery_batch_scale": "single_surface",
                "delivery_outcome": "validated_progress",
            }
        ],
    )
    assert cadence["recommendation"] == "replan"
    assert cadence["reason_codes"] == ["fine_checkpoint_complete"]


def test_fine_packet_writes_one_checkpoint_and_persists_mode(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    fine = build_start_goal_guided_packet(
        project=project,
        goal_id=GOAL_ID,
        agent_id=None,
        cli_bin="loopx",
        host_surface="ark-managed-agent",
        goal_text="Explore a branching integration safely.",
        fine_grained=True,
        include_command_pack_detail=True,
    )
    contract = fine["command_pack"]["goal_start_contract"]
    commands = fine["command_pack"]["commands"]
    steps = fine["guided_transaction"]["ordered_steps"]

    assert contract["turn_mode"] == "fine_grained"
    assert contract["fine_grained"] == {
        "todo_granularity": "small_checkpoint",
        "turn_boundary": "one_todo_per_turn",
        "replan": "after_each_todo",
    }
    assert contract["planner"]["maximum_runnable_todos_written_ahead"] == 1
    assert "--fine-grained" in commands["goal_start_connect_if_needed"]
    assert (
        "--execution-turn-granularity fine"
        in commands["goal_start_configure_turn_granularity"]
    )
    assert any(step["id"] == "configure_fine_grained_turn_mode" for step in steps)
    assert "existing replan obligation/ACK path" in commands["goal_start_plan_prompt"]
    assert "write exactly one" in commands["goal_start_plan_prompt"]
    assert "broad goal 2-5" not in commands["goal_start_plan_prompt"]

    standard = build_start_goal_guided_packet(
        project=project,
        goal_id=GOAL_ID,
        agent_id=None,
        cli_bin="loopx",
        host_surface="ark-managed-agent",
        goal_text="Explore a branching integration safely.",
        include_command_pack_detail=True,
    )
    standard_contract = standard["command_pack"]["goal_start_contract"]
    assert "turn_mode" not in standard_contract
    assert "fine_grained" not in standard_contract
    assert "--fine-grained" not in standard["command_pack"]["canonical_cli_command"]
    assert not any(
        step["id"] == "configure_fine_grained_turn_mode"
        for step in standard["guided_transaction"]["ordered_steps"]
    )


def test_fine_heartbeat_rule_is_opt_in_only() -> None:
    standard = build_heartbeat_prompt(goal_id=GOAL_ID, thin=True)
    explicit_standard = build_heartbeat_prompt(
        goal_id=GOAL_ID,
        thin=True,
        turn_granularity="standard",
    )
    fine = build_heartbeat_prompt(
        goal_id=GOAL_ID,
        thin=True,
        turn_granularity="fine",
    )

    assert standard == explicit_standard
    assert FINE_GRAINED_TURN_RULE not in standard["task_body"]
    assert fine["turn_mode"] == "fine_grained"
    assert fine["turn_granularity"] == "fine"
    assert FINE_GRAINED_TURN_RULE in fine["task_body"]
    assert "end the turn without claiming or executing a successor" in fine["task_body"]


def test_heartbeat_cli_reads_sticky_fine_mode_from_registry(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state.parent.mkdir(parents=True)
    state.write_text("# Active Goal State\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state.relative_to(project)),
                        "execution_profile": build_execution_profile(
                            turn_granularity="fine"
                        ),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "loopx"),
            "--format",
            "json",
            "--registry",
            str(registry),
            "heartbeat-prompt",
            "--thin",
            "--goal-id",
            GOAL_ID,
        ],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["turn_mode"] == "fine_grained"
    assert FINE_GRAINED_TURN_RULE in payload["task_body"]


def test_one_fine_completion_reuses_existing_frontier_replan_path() -> None:
    vision = {
        "schema_version": "agent_vision_v0",
        "agent_id": AGENT_ID,
        "state": "active",
        "vision_patch": {
            "acceptance_summary": "Keep the next checkpoint aligned with evidence.",
            "advancement_policy": "repeat_until_closed",
        },
    }
    completed = {
        "todo_id": "todo_checkpoint_1",
        "claimed_by": AGENT_ID,
        "completed_at": "2026-08-11T09:00:00+08:00",
    }
    summary = {
        "recent_completed_advancement_items": [completed],
        "current_agent_claimed_advancement_count": 1,
        "executable_backlog_items": [
            {
                "todo_id": "todo_preplanned_successor",
                "claimed_by": AGENT_ID,
                "task_class": "advancement_task",
                "status": "open",
            }
        ],
    }

    assert (
        acceptance_gaps_from_todo_completion_checkpoint(
            vision,
            None,
            agent_todo_summary=summary,
            agent_id=AGENT_ID,
        )
        == []
    )
    gaps = acceptance_gaps_from_todo_completion_checkpoint(
        vision,
        None,
        agent_todo_summary=summary,
        agent_id=AGENT_ID,
        completed_todo_threshold=1,
    )
    assert gaps[0]["replan_cadence"] == "fine_grained_after_each_todo"

    obligation = derive_goal_frontier_replan_obligation_from_summaries(
        user_todo_summary=None,
        agent_todo_summary=summary,
        work_lane_contract=None,
        agent_id=AGENT_ID,
        existing_replan_obligation=None,
        acceptance_gaps=gaps,
    )
    assert obligation is not None
    assert obligation["required"] is True
    assert "retain_replace_or_split_successor" in obligation["guidance_actions"]
    assert "existing bounded replan path" in obligation["recommended_action"]


def test_configure_goal_persists_and_can_revert_fine_mode(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "execution_profile": build_execution_profile(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    applied = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        execution_turn_granularity="fine",
        execute=True,
    )
    assert applied["changed_fields"] == ["execution_profile"]
    persisted = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    assert persisted["execution_profile"]["turn_granularity"] == "fine"

    reverted = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        execution_turn_granularity="standard",
        execute=True,
    )
    assert reverted["changed_fields"] == ["execution_profile"]
    persisted = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    assert "turn_granularity" not in persisted["execution_profile"]
