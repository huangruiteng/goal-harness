from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


PLANNER_WORKER_PLAN_SCHEMA_VERSION = "planner_worker_plan_v0"
PLANNER_WORKER_STEP_SCHEMA_VERSION = "planner_worker_step_v0"
PLANNER_WORKER_RECEIPT_SCHEMA_VERSION = "planner_worker_receipt_v0"
MAX_PLANNER_WORKER_STEPS = 8

PLANNER_WORKER_EXECUTORS = frozenset(
    {"cheap_worker", "strong_worker", "planner_only"}
)
PLANNER_WORKER_MODEL_TIERS = frozenset({"cheap", "strong", "none"})
PLANNER_WORKER_AUTONOMY = frozenset({"narrow", "bounded", "open"})
PLANNER_WORKER_ACTION_KINDS = frozenset(
    {"edit", "create", "delete", "validate", "research", "design", "investigate"}
)

_PLAN_FIELDS = frozenset({"schema_version", "plan_id", "objective", "steps"})
_STEP_FIELDS = frozenset(
    {
        "schema_version",
        "step_id",
        "planner_order",
        "role",
        "target_files",
        "action_kind",
        "recommended_executor",
        "worker_model_tier",
        "worker_autonomy",
        "worker_ready",
        "worker_blockers",
        "context_budget",
        "research_summary",
        "implementation_notes",
        "instruction",
        "depends_on",
        "validation_commands",
        "done_criteria",
        "escalation_policy",
        "verification",
    }
)
_CONTEXT_BUDGET_FIELDS = frozenset(
    {"max_files", "max_bytes_per_file", "allow_extra_files"}
)


@dataclass(frozen=True)
class AdapterTurn:
    output_text: str
    usage: dict[str, int]
    usage_complete: bool


@dataclass(frozen=True)
class ValidationResult:
    command: str
    passed: bool
    exit_code: int | None


def _require_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_string_list(
    value: Any,
    *,
    field: str,
    allow_empty: bool = True,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result: list[str] = []
    for item in value:
        text = _require_text(item, field=f"{field} item")
        if text in result:
            raise ValueError(f"{field} must not contain duplicates")
        result.append(text)
    if not allow_empty and not result:
        raise ValueError(f"{field} must be non-empty")
    return result


def _require_exact_fields(value: dict[str, Any], *, expected: frozenset[str], field: str) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise ValueError(f"{field} is missing required fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{field} contains unknown fields: {', '.join(unknown)}")


def _require_enum(value: Any, *, field: str, allowed: frozenset[str]) -> str:
    text = _require_text(value, field=field)
    if text not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return text


def _validate_target_file(value: str, *, field: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {".", ""}:
        raise ValueError(f"{field} must be a repository-relative path")


def _validate_dependency_graph(steps: list[dict[str, Any]]) -> None:
    step_ids = [str(step["step_id"]) for step in steps]
    known = set(step_ids)
    for step in steps:
        step_id = str(step["step_id"])
        for dependency in step["depends_on"]:
            if dependency not in known:
                raise ValueError(
                    f"step {step_id} has unknown dependency: {dependency}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()
    dependencies = {
        str(step["step_id"]): list(step["depends_on"])
        for step in steps
    }

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise ValueError(f"planner-worker plan contains a dependency cycle at {step_id}")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependencies[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in step_ids:
        visit(step_id)


def validate_planner_worker_plan(raw: Any) -> dict[str, Any]:
    """Validate untrusted Planner output without repairing its shape."""

    if not isinstance(raw, dict):
        raise ValueError("planner-worker plan must be a JSON object")
    _require_exact_fields(raw, expected=_PLAN_FIELDS, field="planner-worker plan")
    if raw.get("schema_version") != PLANNER_WORKER_PLAN_SCHEMA_VERSION:
        raise ValueError(
            "planner-worker plan schema_version must equal "
            f"{PLANNER_WORKER_PLAN_SCHEMA_VERSION}"
        )
    _require_text(raw.get("plan_id"), field="plan_id")
    _require_text(raw.get("objective"), field="objective")
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("planner-worker plan steps must be a non-empty list")
    if len(steps) > MAX_PLANNER_WORKER_STEPS:
        raise ValueError(
            f"planner-worker plan must contain at most {MAX_PLANNER_WORKER_STEPS} steps"
        )

    step_ids: set[str] = set()
    planner_orders: set[int] = set()
    validated_steps: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"steps[{index}] must be a JSON object")
        _require_exact_fields(step, expected=_STEP_FIELDS, field=f"steps[{index}]")
        if step.get("schema_version") != PLANNER_WORKER_STEP_SCHEMA_VERSION:
            raise ValueError(
                f"steps[{index}].schema_version must equal "
                f"{PLANNER_WORKER_STEP_SCHEMA_VERSION}"
            )
        step_id = _require_text(step.get("step_id"), field=f"steps[{index}].step_id")
        if step_id in step_ids:
            raise ValueError(f"step_id must be unique: {step_id}")
        step_ids.add(step_id)
        planner_order = step.get("planner_order")
        if (
            not isinstance(planner_order, int)
            or isinstance(planner_order, bool)
            or planner_order <= 0
        ):
            raise ValueError(f"steps[{index}].planner_order must be a positive integer")
        if planner_order in planner_orders:
            raise ValueError("planner_order must be unique")
        planner_orders.add(planner_order)
        if step.get("role") != "worker":
            raise ValueError(f"steps[{index}].role must equal worker")

        target_files = _require_string_list(
            step.get("target_files"),
            field=f"steps[{index}].target_files",
        )
        for target_file in target_files:
            _validate_target_file(
                target_file,
                field=f"steps[{index}].target_files",
            )
        _require_enum(
            step.get("action_kind"),
            field=f"steps[{index}].action_kind",
            allowed=PLANNER_WORKER_ACTION_KINDS,
        )
        executor = _require_enum(
            step.get("recommended_executor"),
            field=f"steps[{index}].recommended_executor",
            allowed=PLANNER_WORKER_EXECUTORS,
        )
        tier = _require_enum(
            step.get("worker_model_tier"),
            field=f"steps[{index}].worker_model_tier",
            allowed=PLANNER_WORKER_MODEL_TIERS,
        )
        expected_tier = {
            "cheap_worker": "cheap",
            "strong_worker": "strong",
            "planner_only": "none",
        }[executor]
        if tier != expected_tier:
            raise ValueError(
                f"steps[{index}].worker_model_tier must equal {expected_tier} "
                f"for {executor}"
            )
        _require_enum(
            step.get("worker_autonomy"),
            field=f"steps[{index}].worker_autonomy",
            allowed=PLANNER_WORKER_AUTONOMY,
        )
        if not isinstance(step.get("worker_ready"), bool):
            raise ValueError(f"steps[{index}].worker_ready must be a boolean")
        blockers = _require_string_list(
            step.get("worker_blockers"),
            field=f"steps[{index}].worker_blockers",
        )
        if blockers and step["worker_ready"]:
            raise ValueError(
                f"steps[{index}].worker_ready must be false when worker_blockers exist"
            )
        budget = step.get("context_budget")
        if not isinstance(budget, dict):
            raise ValueError(f"steps[{index}].context_budget must be an object")
        _require_exact_fields(
            budget,
            expected=_CONTEXT_BUDGET_FIELDS,
            field=f"steps[{index}].context_budget",
        )
        for budget_field in ("max_files", "max_bytes_per_file"):
            value = budget.get(budget_field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(
                    f"steps[{index}].context_budget.{budget_field} "
                    "must be a positive integer"
                )
        if not isinstance(budget.get("allow_extra_files"), bool):
            raise ValueError(
                f"steps[{index}].context_budget.allow_extra_files must be a boolean"
            )
        _require_text(
            step.get("research_summary"),
            field=f"steps[{index}].research_summary",
        )
        _require_text(
            step.get("implementation_notes"),
            field=f"steps[{index}].implementation_notes",
        )
        _require_text(step.get("instruction"), field=f"steps[{index}].instruction")
        _require_string_list(
            step.get("depends_on"),
            field=f"steps[{index}].depends_on",
        )
        validation_commands = _require_string_list(
            step.get("validation_commands"),
            field=f"steps[{index}].validation_commands",
        )
        done_criteria = _require_string_list(
            step.get("done_criteria"),
            field=f"steps[{index}].done_criteria",
        )
        if executor != "planner_only" and step["worker_ready"]:
            if not target_files:
                raise ValueError(
                    f"steps[{index}].target_files must be non-empty for an executable step"
                )
            if not validation_commands:
                raise ValueError(
                    f"steps[{index}].validation_commands must be non-empty "
                    "for an executable step"
                )
            if not done_criteria:
                raise ValueError(
                    f"steps[{index}].done_criteria must be non-empty "
                    "for an executable step"
                )
        _require_text(
            step.get("escalation_policy"),
            field=f"steps[{index}].escalation_policy",
        )
        _require_text(
            step.get("verification"),
            field=f"steps[{index}].verification",
        )
        validated_steps.append(copy.deepcopy(step))

    _validate_dependency_graph(validated_steps)
    result = copy.deepcopy(raw)
    result["steps"] = sorted(
        validated_steps,
        key=lambda step: (int(step["planner_order"]), str(step["step_id"])),
    )
    return result


def parse_planner_worker_plan_text(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("planner output must be non-empty")
    clean = text.strip()
    try:
        raw = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "planner output must be a single JSON object without markdown or prose"
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError("planner output must be a single JSON object")
    return validate_planner_worker_plan(raw)


def planner_worker_plan_json_skeleton(*, max_steps: int = MAX_PLANNER_WORKER_STEPS) -> dict[str, Any]:
    if max_steps <= 0 or max_steps > MAX_PLANNER_WORKER_STEPS:
        raise ValueError(
            f"max_steps must be between 1 and {MAX_PLANNER_WORKER_STEPS}"
        )
    return {
        "schema_version": PLANNER_WORKER_PLAN_SCHEMA_VERSION,
        "plan_id": "short-stable-plan-id",
        "objective": "one sentence objective",
        "steps": [
            {
                "schema_version": PLANNER_WORKER_STEP_SCHEMA_VERSION,
                "step_id": "short-step-id",
                "planner_order": 1,
                "role": "worker",
                "target_files": ["relative/path.py"],
                "action_kind": "edit",
                "recommended_executor": "cheap_worker",
                "worker_model_tier": "cheap",
                "worker_autonomy": "bounded",
                "worker_ready": True,
                "worker_blockers": [],
                "context_budget": {
                    "max_files": 2,
                    "max_bytes_per_file": 12000,
                    "allow_extra_files": False,
                },
                "research_summary": "facts the Planner already established",
                "implementation_notes": "precise edit strategy for the Worker",
                "instruction": "one scoped worker instruction",
                "depends_on": [],
                "validation_commands": ["python3 -m pytest -q tests/test_target.py"],
                "done_criteria": ["focused validation passes"],
                "escalation_policy": "stop when the declared scope is insufficient",
                "verification": "run the declared validation commands",
            }
        ],
    }


def build_planner_prompt(
    *,
    objective: str,
    task_instruction: str,
    max_steps: int = MAX_PLANNER_WORKER_STEPS,
) -> str:
    objective_text = _require_text(objective, field="objective")
    task_text = _require_text(task_instruction, field="task_instruction")
    skeleton = planner_worker_plan_json_skeleton(max_steps=max_steps)
    return "\n".join(
        [
            "You are the Planner for an experimental planner-worker coding runtime.",
            "Do not edit files. Return one worker-ready plan as strict JSON.",
            "Every step must name exact target files and explain how each file changes.",
            "Choose cheap_worker only when the edit and validation are fully bounded.",
            "Choose strong_worker for ambiguous execution and planner_only when more planning is required.",
            "The runtime rejects markdown fences, prose, missing fields, illegal enums, invalid dependencies, and non-positive budgets.",
            f"Return at most {max_steps} steps using this exact schema:",
            json.dumps(skeleton, ensure_ascii=False, indent=2),
            "",
            "Objective:",
            objective_text,
            "",
            "Task instruction:",
            task_text,
        ]
    )


def build_worker_step_prompt(
    *,
    plan: dict[str, Any],
    step: dict[str, Any],
) -> str:
    validated = validate_planner_worker_plan(plan)
    step_id = _require_text(step.get("step_id"), field="step_id")
    known_step = next(
        (item for item in validated["steps"] if item["step_id"] == step_id),
        None,
    )
    if known_step is None:
        raise ValueError(f"step_id not found in plan: {step_id}")
    return "\n".join(
        [
            "You are the Worker for an experimental planner-worker coding runtime.",
            "Execute only this selected plan step. Do not re-plan the whole task.",
            "Do not repeat broad investigation or read unrelated files.",
            f"Plan id: {validated['plan_id']}",
            f"Step id: {known_step['step_id']}",
            f"Target files: {', '.join(known_step['target_files'])}",
            f"Context budget: {json.dumps(known_step['context_budget'], sort_keys=True)}",
            "",
            "Planner research summary:",
            known_step["research_summary"],
            "",
            "Planner implementation notes:",
            known_step["implementation_notes"],
            "",
            "Instruction:",
            known_step["instruction"],
            "",
            "Validation commands:",
            "\n".join(f"- {command}" for command in known_step["validation_commands"]),
            "",
            "Done criteria:",
            "\n".join(f"- {criterion}" for criterion in known_step["done_criteria"]),
            "",
            "Escalation policy:",
            known_step["escalation_policy"],
        ]
    )


def select_next_executable_step(
    plan: dict[str, Any],
    completed_step_ids: list[str] | tuple[str, ...] | set[str],
) -> dict[str, Any]:
    validated = validate_planner_worker_plan(plan)
    completed = {str(value) for value in completed_step_ids}
    known_ids = {str(step["step_id"]) for step in validated["steps"]}
    unknown_completed = sorted(completed - known_ids)
    if unknown_completed:
        raise ValueError(
            "completed_step_ids contain unknown steps: " + ", ".join(unknown_completed)
        )
    pending = [
        step
        for step in validated["steps"]
        if str(step["step_id"]) not in completed
    ]
    if not pending:
        return {"status": "completed", "step": None, "reason": "all steps completed"}

    ineligible: list[dict[str, Any]] = []
    for step in pending:
        if step["recommended_executor"] == "planner_only":
            ineligible.append(
                {
                    "status": "planner_required",
                    "step": step,
                    "reason": step["escalation_policy"],
                }
            )
            continue
        if not step["worker_ready"] or step["worker_blockers"]:
            reason = (
                "; ".join(step["worker_blockers"])
                if step["worker_blockers"]
                else step["escalation_policy"]
            )
            ineligible.append({"status": "blocked", "step": step, "reason": reason})
            continue
        unmet = [
            dependency
            for dependency in step["depends_on"]
            if dependency not in completed
        ]
        if unmet:
            ineligible.append(
                {
                    "status": "waiting_dependencies",
                    "step": step,
                    "reason": "unmet dependencies: " + ", ".join(unmet),
                }
            )
            continue
        return {"status": "selected", "step": step, "reason": None}
    return ineligible[0]


def resolve_planner_worker_executor(
    step: dict[str, Any],
    *,
    model_routes: dict[str, dict[str, str]],
) -> dict[str, str]:
    executor = _require_enum(
        step.get("recommended_executor"),
        field="recommended_executor",
        allowed=PLANNER_WORKER_EXECUTORS,
    )
    if executor == "planner_only":
        raise ValueError("planner_only does not resolve to a Worker model route")
    route = model_routes.get(executor)
    if not isinstance(route, dict):
        raise ValueError(f"missing model route for executor: {executor}")
    model = _require_text(route.get("model"), field=f"{executor}.model")
    effort = _require_text(route.get("effort"), field=f"{executor}.effort")
    return {"executor": executor, "model": model, "effort": effort}
