from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.planner_worker import (
    AdapterTurn,
    PLANNER_WORKER_PLAN_SCHEMA_VERSION,
    PLANNER_WORKER_STEP_SCHEMA_VERSION,
    ValidationResult,
)
from loopx.planner_worker_runtime import run_planner_worker_once


def executable_plan() -> dict:
    return {
        "schema_version": PLANNER_WORKER_PLAN_SCHEMA_VERSION,
        "plan_id": "runtime-plan",
        "objective": "Update one fixture.",
        "steps": [
            {
                "schema_version": PLANNER_WORKER_STEP_SCHEMA_VERSION,
                "step_id": "edit-fixture",
                "planner_order": 1,
                "role": "worker",
                "target_files": ["result.txt"],
                "action_kind": "edit",
                "recommended_executor": "cheap_worker",
                "worker_model_tier": "cheap",
                "worker_autonomy": "bounded",
                "worker_ready": True,
                "worker_blockers": [],
                "context_budget": {
                    "max_files": 1,
                    "max_bytes_per_file": 4096,
                    "allow_extra_files": False,
                },
                "research_summary": "The fixture contains one stale value.",
                "implementation_notes": "Replace the stale value.",
                "instruction": "Write expected to result.txt.",
                "depends_on": [],
                "validation_commands": ["python3 verify.py"],
                "done_criteria": ["verify.py exits zero"],
                "escalation_policy": "Stop if result.txt is outside the workspace.",
                "verification": "Run python3 verify.py.",
                "status": "planned",
            }
        ],
    }


class FakePlanner:
    def __init__(self, plan: dict) -> None:
        self.output_plan = plan
        self.calls = 0

    def plan(self, *, prompt: str, model_route: dict[str, str], cwd: Path) -> AdapterTurn:
        self.calls += 1
        assert model_route["model"] == "gpt-5.5"
        return AdapterTurn(
            output_text=json.dumps(self.output_plan),
            usage={"input_tokens": 100, "output_tokens": 40},
            usage_complete=True,
        )


class FixtureWorker:
    def __init__(self, *, expected_model: str = "deepseek-v4-flash") -> None:
        self.calls = 0
        self.model_routes: list[dict[str, str]] = []
        self.expected_model = expected_model

    def execute(self, *, prompt: str, model_route: dict[str, str], cwd: Path) -> AdapterTurn:
        self.calls += 1
        self.model_routes.append(model_route)
        assert model_route["model"] == self.expected_model
        assert "Do not re-plan the whole task" in prompt
        (cwd / "result.txt").write_text("expected\n", encoding="utf-8")
        return AdapterTurn(
            output_text="updated result.txt",
            usage={"input_tokens": 60, "output_tokens": 20},
            usage_complete=True,
        )


def fixture_validation(command: str, cwd: Path) -> ValidationResult:
    passed = command == "python3 verify.py" and (cwd / "result.txt").read_text(
        encoding="utf-8"
    ) == "expected\n"
    return ValidationResult(command=command, passed=passed, exit_code=0 if passed else 1)


def test_runtime_executes_selected_step_validates_and_emits_receipt(tmp_path: Path) -> None:
    planner = FakePlanner(executable_plan())
    worker = FixtureWorker()

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=planner,
        worker=worker,
        validation_runner=fixture_validation,
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert planner.calls == 1
    assert worker.calls == 1
    assert worker.model_routes == [{"model": "deepseek-v4-flash", "effort": "medium"}]
    assert receipt["schema_version"] == "planner_worker_receipt_v0"
    assert receipt["status"] == "completed"
    assert receipt["plan_id"] == "runtime-plan"
    assert receipt["step_id"] == "edit-fixture"
    assert receipt["executor"] == "cheap_worker"
    assert receipt["model_route"]["model"] == "deepseek-v4-flash"
    assert receipt["validation"] == [
        {"command": "python3 verify.py", "passed": True, "exit_code": 0}
    ]
    assert receipt["usage"] == {
        "complete": True,
        "input_tokens": 160,
        "output_tokens": 60,
        "total_tokens": 220,
    }
    assert receipt["cost"] == {
        "complete": False,
        "amount": None,
        "currency": None,
        "reason": "model pricing was not supplied",
    }


def test_runtime_validation_failure_cannot_report_delivery_success(tmp_path: Path) -> None:
    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(executable_plan()),
        worker=FixtureWorker(),
        validation_runner=lambda command, cwd: ValidationResult(
            command=command,
            passed=False,
            exit_code=1,
        ),
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "failed"
    assert receipt["validation"][0]["passed"] is False


def test_runtime_strong_step_uses_strong_model_route(tmp_path: Path) -> None:
    plan = executable_plan()
    plan["steps"][0]["recommended_executor"] = "strong_worker"
    plan["steps"][0]["worker_model_tier"] = "strong"
    worker = FixtureWorker(expected_model="gpt-5.5")

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(plan),
        worker=worker,
        validation_runner=fixture_validation,
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "completed"
    assert receipt["executor"] == "strong_worker"
    assert receipt["model_route"]["model"] == "gpt-5.5"


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("not_ready", "blocked"),
        ("blocker", "blocked"),
        ("planner_only", "planner_required"),
        ("dependency", "waiting_dependencies"),
    ],
)
def test_runtime_ineligible_step_does_not_call_worker(
    tmp_path: Path,
    case: str,
    expected_status: str,
) -> None:
    plan = executable_plan()
    if case == "not_ready":
        plan["steps"][0]["worker_ready"] = False
    elif case == "blocker":
        plan["steps"][0]["worker_ready"] = False
        plan["steps"][0]["worker_blockers"] = ["Planner needs one missing symbol."]
    elif case == "planner_only":
        plan["steps"][0]["recommended_executor"] = "planner_only"
        plan["steps"][0]["worker_model_tier"] = "none"
        plan["steps"][0]["worker_ready"] = False
    else:
        dependency = {
            **plan["steps"][0],
            "step_id": "inspect-first",
            "planner_order": 2,
            "recommended_executor": "planner_only",
            "worker_model_tier": "none",
            "worker_ready": False,
        }
        plan["steps"][0]["planner_order"] = 1
        plan["steps"][0]["depends_on"] = ["inspect-first"]
        plan["steps"].append(dependency)
    worker = FixtureWorker()

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(plan),
        worker=worker,
        validation_runner=fixture_validation,
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert worker.calls == 0
    assert receipt["status"] == expected_status
    assert receipt["step_id"] == "edit-fixture"
    assert receipt["validation"] == []
