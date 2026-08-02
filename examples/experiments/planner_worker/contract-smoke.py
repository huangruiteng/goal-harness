#!/usr/bin/env python3
"""Smoke-test the durable planner-worker contract boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from loopx.experiments.planner_worker.contract import (  # noqa: E402
    build_planner_prompt,
    build_worker_step_prompt,
    parse_planner_worker_plan_text,
    planner_worker_plan_json_skeleton,
    resolve_planner_worker_executor,
    select_next_executable_step,
)


def main() -> int:
    plan = planner_worker_plan_json_skeleton()
    plan["plan_id"] = "contract-smoke"
    plan["objective"] = "Update one fixture."
    step = plan["steps"][0]
    step["step_id"] = "update-fixture"
    step["target_files"] = ["fixture.txt"]
    step["instruction"] = "Write expected to fixture.txt."

    parsed = parse_planner_worker_plan_text(json.dumps(plan))
    selection = select_next_executable_step(parsed, completed_step_ids=[])
    assert selection["status"] == "selected", selection
    assert selection["step"]["step_id"] == "update-fixture", selection
    route = resolve_planner_worker_executor(
        selection["step"],
        model_routes={
            "cheap_worker": {
                "model": "deepseek-v4-flash",
                "effort": "medium",
            }
        },
    )
    assert route["model"] == "deepseek-v4-flash", route

    planner_prompt = build_planner_prompt(
        objective=plan["objective"],
        task_instruction="Return a bounded file-level plan.",
    )
    assert "Return one worker-ready plan as strict JSON" in planner_prompt
    worker_prompt = build_worker_step_prompt(plan=parsed, step=selection["step"])
    assert "Do not re-plan the whole task" in worker_prompt
    assert "fixture.txt" in worker_prompt

    try:
        parse_planner_worker_plan_text(f"```json\n{json.dumps(plan)}\n```")
    except ValueError as exc:
        assert "single JSON object" in str(exc), exc
    else:
        raise AssertionError("fenced Planner output must be rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
