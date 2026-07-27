#!/usr/bin/env python3
"""Compare one synthetic case under plain strong-model and planner-worker routes."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.planner_worker import (
    DEFAULT_PLANNER_MODEL,
    DEFAULT_WORKER_MODEL,
    normalize_planner_worker_plan,
    project_planner_worker_cost,
)


def main() -> int:
    objective = "Implement planner-worker mode for LoopX."
    task_instruction = (
        "Add a planner model route that emits file-level steps, then let a cheaper "
        "worker model execute those steps while preserving existing default worker behavior."
    )
    plan = normalize_planner_worker_plan(
        {
            "plan_id": "planner-worker-economics-case",
            "objective": objective,
            "steps": [
                {
                    "step_id": "orchestration",
                    "target_files": ["loopx/orchestration.py"],
                    "instruction": "Register planner_worker as an explicit orchestration mode.",
                },
                {
                    "step_id": "contract",
                    "target_files": ["loopx/planner_worker.py", "loopx/codex_goal_baseline.py"],
                    "instruction": "Add plan packet helpers and app-server planner-worker contract.",
                    "depends_on": ["orchestration"],
                },
                {
                    "step_id": "config",
                    "target_files": ["loopx/configure_goal.py", "loopx/cli_commands/registry_admin.py"],
                    "instruction": "Expose planner and worker model routes in per-goal config.",
                    "depends_on": ["contract"],
                },
                {
                    "step_id": "smoke",
                    "target_files": ["examples/planner-worker-cost-projection-smoke.py"],
                    "instruction": "Add a deterministic economics projection for this same case.",
                    "depends_on": ["config"],
                    "verification": "Run planner-worker focused smokes.",
                },
            ],
        }
    )
    projection = project_planner_worker_cost(
        objective=objective,
        task_instruction=task_instruction,
        plan=plan,
        baseline_model=DEFAULT_PLANNER_MODEL,
        planner_model=DEFAULT_PLANNER_MODEL,
        worker_model=DEFAULT_WORKER_MODEL,
        baseline_worker_turns=4,
        worker_turns=4,
    )
    assert projection["schema_version"] == "planner_worker_cost_projection_v0"
    baseline = projection["baseline"]
    planner_worker = projection["planner_worker"]
    comparison = projection["comparison"]
    assert baseline["model"] == DEFAULT_PLANNER_MODEL, projection
    assert planner_worker["planner_model"] == DEFAULT_PLANNER_MODEL, projection
    assert planner_worker["worker_model"] == DEFAULT_WORKER_MODEL, projection
    assert baseline["total_tokens"] > 0, projection
    assert planner_worker["total_tokens"] > 0, projection
    assert baseline["estimated_cost"] > 0, projection
    assert planner_worker["estimated_cost"] > 0, projection
    assert isinstance(comparison["estimated_savings"], float), projection
    assert isinstance(comparison["estimated_savings_ratio"], float), projection
    print(
        "planner_worker_cost_projection "
        f"baseline_tokens={baseline['total_tokens']} "
        f"planner_worker_tokens={planner_worker['total_tokens']} "
        f"baseline_cost={baseline['estimated_cost']} "
        f"planner_worker_cost={planner_worker['estimated_cost']} "
        f"savings={comparison['estimated_savings']} "
        f"savings_ratio={comparison['estimated_savings_ratio']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
