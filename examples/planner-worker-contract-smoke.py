#!/usr/bin/env python3
"""Smoke-test the planner-worker public contract helpers."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.codex_goal_baseline import build_codex_app_server_goal_planner_worker_plan
from loopx.orchestration import (
    PLANNER_WORKER_ORCHESTRATION_MODE,
    VALID_ORCHESTRATION_MODES,
    orchestration_mode_from_spawn_policy,
)
from loopx.planner_worker import (
    DEFAULT_PLANNER_MODEL,
    DEFAULT_WORKER_MODEL,
    build_worker_step_prompt,
    normalize_planner_worker_plan,
)


def main() -> int:
    assert PLANNER_WORKER_ORCHESTRATION_MODE in VALID_ORCHESTRATION_MODES
    assert orchestration_mode_from_spawn_policy({"mode": "planner_worker"}) == "planner_worker"
    assert (
        orchestration_mode_from_spawn_policy({"allowed": True, "max_children": 2})
        == "multi_subagent"
    )

    plan = normalize_planner_worker_plan(
        {
            "plan_id": "case-plan",
            "objective": "Fix a small CLI bug.",
            "steps": [
                {
                    "step_id": "inspect-cli",
                    "planner_order": 1,
                    "target_files": ["loopx/cli.py"],
                    "action_kind": "edit",
                    "instruction": "Inspect the CLI command dispatch and add the missing branch.",
                    "verification": "Run the focused CLI smoke.",
                }
            ],
        }
    )
    assert plan["schema_version"] == "planner_worker_plan_v0", plan
    assert plan["steps"][0]["schema_version"] == "planner_worker_step_v0", plan
    assert plan["steps"][0]["target_files"] == ["loopx/cli.py"], plan

    worker_prompt = build_worker_step_prompt(plan=plan, step=plan["steps"][0])
    assert "Execute only the plan step below" in worker_prompt
    assert "loopx/cli.py" in worker_prompt
    assert "Do not re-plan the whole task" in worker_prompt

    app_server_plan = build_codex_app_server_goal_planner_worker_plan(
        objective="Fix a small CLI bug.",
        task_instruction="The CLI misses one command dispatch branch.",
        planner_output_plan=plan,
    )
    assert app_server_plan["schema_version"] == "codex_app_server_goal_planner_worker_v0"
    assert app_server_plan["planner_model"] == DEFAULT_PLANNER_MODEL
    assert app_server_plan["worker_model"] == DEFAULT_WORKER_MODEL
    messages = app_server_plan["messages"]
    assert messages["planner_turn_start"]["params"]["model"] == DEFAULT_PLANNER_MODEL
    assert messages["worker_turn_start_template"]["params"]["model"] == DEFAULT_WORKER_MODEL
    assert app_server_plan["claim_boundary"]["planner_output_must_be_structured_plan"] is True
    assert app_server_plan["worker_step_prompt_sha256"], app_server_plan
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
