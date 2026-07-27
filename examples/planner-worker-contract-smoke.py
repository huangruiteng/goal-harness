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
    build_planner_prompt,
    build_worker_step_prompt,
    normalize_planner_worker_plan,
    parse_planner_worker_plan_text,
    planner_worker_plan_json_skeleton,
)


def main() -> int:
    assert PLANNER_WORKER_ORCHESTRATION_MODE not in VALID_ORCHESTRATION_MODES
    assert orchestration_mode_from_spawn_policy({"mode": "planner_worker"}) == "default"
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
                    "research_summary": "The dispatch table is the only relevant surface.",
                    "implementation_notes": "Add one branch and keep command registration unchanged.",
                    "recommended_executor": "cheap_worker",
                    "worker_model_tier": "cheap",
                    "worker_autonomy": "bounded",
                    "worker_ready": True,
                    "context_budget": {
                        "max_files": 2,
                        "max_bytes_per_file": 12000,
                        "allow_extra_files": False,
                    },
                    "instruction": "Inspect the CLI command dispatch and add the missing branch.",
                    "validation_commands": ["python examples/cli-registry-admin-command-modularization-smoke.py"],
                    "done_criteria": ["CLI command dispatch branch is covered by the focused smoke."],
                    "escalation_policy": "If the dispatch table is not in target_files, stop and ask Planner for one extra file.",
                    "verification": "Run the focused CLI smoke.",
                }
            ],
        }
    )
    assert plan["schema_version"] == "planner_worker_plan_v0", plan
    assert plan["steps"][0]["schema_version"] == "planner_worker_step_v0", plan
    assert plan["steps"][0]["target_files"] == ["loopx/cli.py"], plan
    assert plan["steps"][0]["recommended_executor"] == "cheap_worker", plan
    assert plan["steps"][0]["worker_model_tier"] == "cheap", plan
    assert plan["steps"][0]["worker_autonomy"] == "bounded", plan
    assert plan["steps"][0]["worker_ready"] is True, plan
    assert plan["steps"][0]["context_budget"]["max_files"] == 2, plan
    assert plan["steps"][0]["validation_commands"], plan
    assert plan["steps"][0]["done_criteria"], plan

    planner_prompt = build_planner_prompt(
        objective="Fix a small CLI bug.",
        task_instruction="The CLI misses one command dispatch branch.",
    )
    assert "worker-ready plan with bounded context" in planner_prompt
    assert "Return only a single JSON object" in planner_prompt
    assert "Do not use markdown fences" in planner_prompt
    assert '"context_budget"' in planner_prompt
    assert '"validation_commands"' in planner_prompt
    assert "expensive investigation" not in planner_prompt
    skeleton = planner_worker_plan_json_skeleton(max_steps=3)
    assert skeleton["schema_version"] == "planner_worker_plan_v0", skeleton
    assert skeleton["steps"][0]["recommended_executor"] == "cheap_worker", skeleton

    worker_prompt = build_worker_step_prompt(plan=plan, step=plan["steps"][0])
    assert "Execute only the plan step below" in worker_prompt
    assert "loopx/cli.py" in worker_prompt
    assert "Do not re-plan the whole task" in worker_prompt
    assert "Do not repeat broad investigation" in worker_prompt
    assert "Planner research summary" in worker_prompt
    assert "Recommended executor: cheap_worker" in worker_prompt
    assert "Worker autonomy: bounded" in worker_prompt
    assert "Validation commands:" in worker_prompt
    assert "Escalation policy:" in worker_prompt

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
    assert app_server_plan["claim_boundary"]["planner_must_choose_step_executor"] is True
    assert app_server_plan["claim_boundary"]["cheap_worker_requires_planner_compressed_context"] is True
    assert app_server_plan["claim_boundary"]["planner_must_define_validation_commands"] is True
    assert app_server_plan["claim_boundary"]["planner_must_define_worker_escalation_policy"] is True
    assert app_server_plan["worker_step_prompt_sha256"], app_server_plan

    parsed = parse_planner_worker_plan_text(
        """```json
{
  "schema_version": "planner_worker_plan_v0",
  "plan_id": "parsed-plan",
  "objective": "Fix parser bug.",
  "steps": [
    {
      "step_id": "fix-parser",
      "planner_order": 1,
      "role": "worker",
      "target_files": ["parser.py", "test_parser.py"],
      "action_kind": "edit",
      "recommended_executor": "cheap_worker",
      "worker_model_tier": "cheap",
      "worker_autonomy": "bounded",
      "worker_ready": true,
      "worker_blockers": [],
      "context_budget": {
        "max_files": 2,
        "max_bytes_per_file": 12000,
        "allow_extra_files": false
      },
      "research_summary": "parse_line handles request id extraction.",
      "implementation_notes": "Skip one optional bracket prefix before request id.",
      "instruction": "Patch parser.py and keep the regression.",
      "depends_on": [],
      "validation_commands": ["python -m unittest test_parser.py"],
      "done_criteria": ["unittest passes"],
      "escalation_policy": "Stop if parse_line is absent.",
      "verification": "Run python -m unittest test_parser.py.",
      "status": "planned"
    }
  ]
}
```"""
    )
    assert parsed["plan_id"] == "parsed-plan", parsed
    assert parsed["steps"][0]["validation_commands"] == ["python -m unittest test_parser.py"], parsed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
