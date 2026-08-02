from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

from .contract import (
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


WorkspaceFileType = Literal[
    "regular",
    "symlink",
    "directory",
    "special",
    "deleted",
]


class WorkspaceChange(TypedDict):
    size: int | None
    file_type: WorkspaceFileType


class WorkspaceObserver(Protocol):
    def assert_clean(self, cwd: Path) -> None: ...

    def changed_files(self, cwd: Path) -> dict[str, WorkspaceChange]: ...


ValidationRunner = Callable[[str, Path], ValidationResult]


def _is_within_workspace(path: Path, workspace: Path) -> bool:
    try:
        path.relative_to(workspace)
    except ValueError:
        return False
    return True


def _target_path_violations(
    *,
    workdir: Path,
    step: dict[str, Any],
    after_worker: bool,
) -> list[str]:
    violations: list[str] = []
    action_kind = str(step["action_kind"])
    for relative in step["target_files"]:
        target = workdir / relative
        try:
            resolved = target.resolve(strict=False)
        except (OSError, RuntimeError):
            violations.append(f"{relative}:path_resolution_failed")
            continue
        if not _is_within_workspace(resolved, workdir):
            violations.append(f"{relative}:resolved_outside_workspace")
            continue

        target_exists = target.exists() or target.is_symlink()
        if not target_exists:
            if after_worker and action_kind != "delete":
                violations.append(f"{relative}:target_missing_after_worker")
            continue
        try:
            mode = resolved.stat().st_mode
        except OSError:
            violations.append(f"{relative}:path_resolution_failed")
            continue
        if not stat.S_ISREG(mode):
            violations.append(f"{relative}:unsupported_file_type")
    return violations


def _write_scope_for_step(
    *,
    workdir: Path,
    step: dict[str, Any],
    changed_files: dict[str, WorkspaceChange],
) -> dict[str, Any]:
    target_files = set(step["target_files"])
    action_kind = str(step["action_kind"])
    allow_extra_files = bool(step["context_budget"]["allow_extra_files"])
    violations = [] if allow_extra_files else sorted(set(changed_files) - target_files)
    unsupported_paths: list[str] = []
    for path, change in changed_files.items():
        file_type = change["file_type"]
        planned_deletion = (
            file_type == "deleted" and action_kind == "delete" and path in target_files
        )
        if file_type != "regular" and not planned_deletion:
            unsupported_paths.append(path)
            violations.append(f"{path}:unsupported_file_type:{file_type}")
    if len(changed_files) > int(step["context_budget"]["max_files"]):
        violations.append("context_budget.max_files")
    oversized = sorted(
        path
        for path, change in changed_files.items()
        if change["file_type"] == "regular"
        and change["size"] is not None
        and change["size"] > int(step["context_budget"]["max_bytes_per_file"])
    )
    violations.extend(f"{path}:max_bytes_per_file" for path in oversized)
    violations.extend(
        _target_path_violations(
            workdir=workdir,
            step=step,
            after_worker=True,
        )
    )
    violations = sorted(set(violations))
    return {
        "passed": not violations,
        "changed_files": changed_files,
        "unsupported_paths": sorted(unsupported_paths),
        "violations": violations,
    }


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
    write_scope: dict[str, Any],
    planner_turn: AdapterTurn,
    worker_turn: AdapterTurn | None,
) -> dict[str, Any]:
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
        "write_scope": write_scope,
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
    workspace_observer: WorkspaceObserver,
    approved_validation_commands: set[str] | frozenset[str],
    model_routes: dict[str, dict[str, str]],
    completed_step_ids: list[str] | tuple[str, ...] | set[str] = (),
) -> dict[str, Any]:
    """Run one strict experimental Planner -> Worker -> validation slice."""

    workdir = Path(cwd).resolve()
    workspace_observer.assert_clean(workdir)
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
    planner_changes = workspace_observer.changed_files(workdir)
    if planner_changes:
        return _receipt(
            status="failed",
            plan_id=str(plan["plan_id"]),
            step_id=None,
            reason="Planner modified the workspace",
            executor=None,
            model_route=None,
            validation=[],
            write_scope={
                "passed": False,
                "changed_files": planner_changes,
                "violations": sorted(planner_changes),
            },
            planner_turn=planner_turn,
            worker_turn=None,
        )
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
            write_scope={
                "passed": True,
                "changed_files": {},
                "violations": [],
            },
            planner_turn=planner_turn,
            worker_turn=None,
        )

    assert isinstance(step, dict)
    unapproved_commands = [
        command
        for command in step["validation_commands"]
        if command not in approved_validation_commands
    ]
    if unapproved_commands:
        return _receipt(
            status="failed",
            plan_id=str(plan["plan_id"]),
            step_id=str(step["step_id"]),
            reason="Planner requested validation commands that the caller did not approve",
            executor=None,
            model_route=None,
            validation=[],
            write_scope={
                "passed": True,
                "changed_files": {},
                "violations": [],
            },
            planner_turn=planner_turn,
            worker_turn=None,
        )
    target_path_violations = _target_path_violations(
        workdir=workdir,
        step=step,
        after_worker=False,
    )
    if target_path_violations:
        return _receipt(
            status="failed",
            plan_id=str(plan["plan_id"]),
            step_id=str(step["step_id"]),
            reason="Planner target paths are not safe workspace files",
            executor=None,
            model_route=None,
            validation=[],
            write_scope={
                "passed": False,
                "changed_files": {},
                "unsupported_paths": [],
                "violations": target_path_violations,
            },
            planner_turn=planner_turn,
            worker_turn=None,
        )
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
    changed_files = workspace_observer.changed_files(workdir)
    write_scope = _write_scope_for_step(
        workdir=workdir,
        step=step,
        changed_files=changed_files,
    )
    if not write_scope["passed"]:
        return _receipt(
            status="failed",
            plan_id=str(plan["plan_id"]),
            step_id=str(step["step_id"]),
            reason="Worker changed files outside the Planner contract",
            executor=resolved["executor"],
            model_route=worker_route,
            validation=[],
            write_scope=write_scope,
            planner_turn=planner_turn,
            worker_turn=worker_turn,
        )
    validation = [
        validation_runner(command, workdir)
        for command in step["validation_commands"]
    ]
    write_scope = _write_scope_for_step(
        workdir=workdir,
        step=step,
        changed_files=workspace_observer.changed_files(workdir),
    )
    if not write_scope["passed"]:
        return _receipt(
            status="failed",
            plan_id=str(plan["plan_id"]),
            step_id=str(step["step_id"]),
            reason="Validation left the workspace outside the Planner contract",
            executor=resolved["executor"],
            model_route=worker_route,
            validation=validation,
            write_scope=write_scope,
            planner_turn=planner_turn,
            worker_turn=worker_turn,
        )
    validation_passed = bool(validation) and all(result.passed for result in validation)
    return _receipt(
        status="completed" if validation_passed else "failed",
        plan_id=str(plan["plan_id"]),
        step_id=str(step["step_id"]),
        reason=None if validation_passed else "one or more validation commands failed",
        executor=resolved["executor"],
        model_route=worker_route,
        validation=validation,
        write_scope=write_scope,
        planner_turn=planner_turn,
        worker_turn=worker_turn,
    )
