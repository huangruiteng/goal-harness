from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .planner_worker import (
    AdapterTurn,
    PLANNER_WORKER_RECEIPT_SCHEMA_VERSION,
    ValidationResult,
    build_planner_prompt,
    build_worker_step_prompt,
    parse_planner_worker_plan_text,
    resolve_planner_worker_executor,
    select_next_executable_step,
)


class PlannerAdapter(Protocol):
    def plan(
        self,
        *,
        prompt: str,
        model_route: dict[str, str],
        cwd: Path,
    ) -> AdapterTurn: ...


class WorkerAdapter(Protocol):
    def execute(
        self,
        *,
        prompt: str,
        model_route: dict[str, str],
        cwd: Path,
    ) -> AdapterTurn: ...


ValidationRunner = Callable[[str, Path], ValidationResult]


def _usage_receipt(
    planner_turn: AdapterTurn,
    worker_turn: AdapterTurn | None,
) -> dict[str, int | bool]:
    turns = [planner_turn]
    if worker_turn is not None:
        turns.append(worker_turn)
    input_tokens = sum(int(turn.usage.get("input_tokens", 0)) for turn in turns)
    output_tokens = sum(int(turn.usage.get("output_tokens", 0)) for turn in turns)
    return {
        "complete": all(turn.usage_complete for turn in turns),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _incomplete_cost_receipt() -> dict[str, str | float | bool | None]:
    return {
        "complete": False,
        "amount": None,
        "currency": None,
        "reason": "model pricing was not supplied",
    }


def _receipt(
    *,
    status: str,
    plan_id: str,
    step_id: str | None,
    reason: str | None,
    executor: str | None,
    model_route: dict[str, str] | None,
    validation: list[ValidationResult],
    planner_turn: AdapterTurn,
    worker_turn: AdapterTurn | None,
) -> dict:
    return {
        "schema_version": PLANNER_WORKER_RECEIPT_SCHEMA_VERSION,
        "status": status,
        "plan_id": plan_id,
        "step_id": step_id,
        "reason": reason,
        "executor": executor,
        "model_route": model_route,
        "validation": [
            {
                "command": result.command,
                "passed": result.passed,
                "exit_code": result.exit_code,
            }
            for result in validation
        ],
        "usage": _usage_receipt(planner_turn, worker_turn),
        "cost": _incomplete_cost_receipt(),
    }


def run_planner_worker_once(
    *,
    objective: str,
    task_instruction: str,
    cwd: Path | str,
    planner: PlannerAdapter,
    worker: WorkerAdapter,
    validation_runner: ValidationRunner,
    model_routes: dict[str, dict[str, str]],
    completed_step_ids: list[str] | tuple[str, ...] | set[str] = (),
) -> dict:
    """Run one strict experimental Planner -> Worker -> validation slice."""

    workdir = Path(cwd).resolve()
    planner_route = model_routes.get("planner")
    if not isinstance(planner_route, dict):
        raise ValueError("missing model route for planner")
    planner_prompt = build_planner_prompt(
        objective=objective,
        task_instruction=task_instruction,
    )
    planner_turn = planner.plan(
        prompt=planner_prompt,
        model_route=planner_route,
        cwd=workdir,
    )
    plan = parse_planner_worker_plan_text(planner_turn.output_text)
    selection = select_next_executable_step(
        plan,
        completed_step_ids=completed_step_ids,
    )
    step = selection.get("step")
    if selection["status"] != "selected":
        return _receipt(
            status=str(selection["status"]),
            plan_id=str(plan["plan_id"]),
            step_id=str(step["step_id"]) if isinstance(step, dict) else None,
            reason=str(selection.get("reason") or ""),
            executor=None,
            model_route=None,
            validation=[],
            planner_turn=planner_turn,
            worker_turn=None,
        )

    assert isinstance(step, dict)
    resolved = resolve_planner_worker_executor(step, model_routes=model_routes)
    worker_route = {
        "model": resolved["model"],
        "effort": resolved["effort"],
    }
    worker_turn = worker.execute(
        prompt=build_worker_step_prompt(plan=plan, step=step),
        model_route=worker_route,
        cwd=workdir,
    )
    validation = [
        validation_runner(command, workdir)
        for command in step["validation_commands"]
    ]
    validation_passed = bool(validation) and all(result.passed for result in validation)
    return _receipt(
        status="completed" if validation_passed else "failed",
        plan_id=str(plan["plan_id"]),
        step_id=str(step["step_id"]),
        reason=None if validation_passed else "one or more validation commands failed",
        executor=resolved["executor"],
        model_route=worker_route,
        validation=validation,
        planner_turn=planner_turn,
        worker_turn=worker_turn,
    )
