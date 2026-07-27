from __future__ import annotations

from typing import Any


PLANNER_WORKER_PLAN_SCHEMA_VERSION = "planner_worker_plan_v0"
PLANNER_WORKER_STEP_SCHEMA_VERSION = "planner_worker_step_v0"
PLANNER_WORKER_COST_PROJECTION_SCHEMA_VERSION = "planner_worker_cost_projection_v0"
DEFAULT_PLANNER_MODEL = "gpt-5.5"
DEFAULT_WORKER_MODEL = "deepseek-v4-flash"
DEFAULT_PLANNER_EFFORT = "high"
DEFAULT_WORKER_EFFORT = "medium"


DEFAULT_MODEL_TOKEN_PRICES_PER_1K = {
    DEFAULT_PLANNER_MODEL: {"input": 0.02, "output": 0.08},
    DEFAULT_WORKER_MODEL: {"input": 0.0005, "output": 0.002},
    "gpt-5.4-mini": {"input": 0.002, "output": 0.008},
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    result: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in result:
            result.append(text)
    return result


def compact_planner_worker_model_routes(model_routes: Any) -> dict[str, dict[str, str]]:
    routes = model_routes if isinstance(model_routes, dict) else {}
    compact: dict[str, dict[str, str]] = {
        "planner": {"model": DEFAULT_PLANNER_MODEL, "effort": DEFAULT_PLANNER_EFFORT},
        "worker": {"model": DEFAULT_WORKER_MODEL, "effort": DEFAULT_WORKER_EFFORT},
    }
    for role in ("planner", "worker"):
        route = routes.get(role)
        if not isinstance(route, dict):
            continue
        model = _clean_text(route.get("model"))
        effort = _clean_text(route.get("effort"))
        if model:
            compact[role]["model"] = model
        if effort:
            compact[role]["effort"] = effort
    return compact


def build_planner_prompt(
    *,
    objective: str,
    task_instruction: str,
    max_steps: int = 8,
) -> str:
    objective_text = _clean_text(objective)
    task_text = _clean_text(task_instruction)
    if not objective_text:
        raise ValueError("objective must be non-empty")
    if not task_text:
        raise ValueError("task_instruction must be non-empty")
    if max_steps <= 0:
        raise ValueError("max_steps must be greater than 0")
    return "\n".join(
        [
            "You are the Planner for a planner-worker coding mode.",
            "Do the expensive investigation now so cheaper Workers can execute simple scoped steps later.",
            "Produce a compact structured plan only; do not edit files.",
            "Each step must name target_files, action_kind, research_summary, implementation_notes, concrete instruction, dependencies, and verification.",
            "Each step must also choose recommended_executor: cheap_worker, strong_worker, or planner_only.",
            "Use cheap_worker only when target files, edit shape, and verification are clear enough for a weaker model.",
            "Use strong_worker or planner_only when the step still needs broad exploration, ambiguous design, or risky cross-file reasoning.",
            "Prefer enough file-level detail that the Worker does not need broad repo search or re-planning.",
            f"Limit the plan to at most {int(max_steps)} steps.",
            "",
            "Objective:",
            objective_text,
            "",
            "Task instruction:",
            task_text,
            "",
            "Return JSON with schema_version=planner_worker_plan_v0 and a steps array.",
        ]
    )


def build_worker_step_prompt(
    *,
    plan: dict[str, Any],
    step: dict[str, Any],
) -> str:
    normalized = normalize_planner_worker_plan(plan)
    step_id = _clean_text(step.get("step_id"))
    if not step_id:
        raise ValueError("step_id must be non-empty")
    known_step = next(
        (item for item in normalized["steps"] if item.get("step_id") == step_id),
        None,
    )
    if known_step is None:
        raise ValueError(f"step_id not found in plan: {step_id}")
    return "\n".join(
        [
            "You are the Worker for a planner-worker coding mode.",
            "Execute only the plan step below. Do not re-plan the whole task.",
            "Do not repeat broad investigation. Trust the Planner research unless direct execution proves it stale.",
            "Keep reads and edits scoped to target_files unless verification proves another file is required.",
            "If context is insufficient, report the smallest missing fact instead of scanning unrelated files.",
            "",
            f"Plan id: {normalized['plan_id']}",
            f"Step id: {known_step['step_id']}",
            f"Target files: {', '.join(known_step['target_files']) or '<none>'}",
            f"Action kind: {known_step['action_kind']}",
            f"Recommended executor: {known_step['recommended_executor']}",
            f"Worker model tier: {known_step['worker_model_tier']}",
            f"Worker ready: {known_step['worker_ready']}",
            f"Worker blockers: {', '.join(known_step['worker_blockers']) or '<none>'}",
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
            "Verification:",
            known_step["verification"],
        ]
    )


def _recommended_executor_for_step(item: dict[str, Any]) -> str:
    blockers = _clean_list(item.get("worker_blockers"))
    target_files = _clean_list(item.get("target_files"))
    action_kind = _clean_text(item.get("action_kind"))
    if blockers:
        return "strong_worker"
    if target_files and action_kind not in {"research", "design", "investigate", "planner_only"}:
        return "cheap_worker"
    return "planner_only"


def _worker_model_tier_for_step(item: dict[str, Any]) -> str:
    executor = _clean_text(item.get("recommended_executor")) or _recommended_executor_for_step(item)
    if executor == "cheap_worker":
        return "cheap"
    if executor == "strong_worker":
        return "strong"
    return "none"


def normalize_planner_worker_plan(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("planner-worker plan must be a dict")
    plan_id = _clean_text(raw.get("plan_id")) or "planner-worker-plan"
    objective = _clean_text(raw.get("objective"))
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ValueError("planner-worker plan must include non-empty steps")
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(steps_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError("planner-worker steps must be dicts")
        instruction = _clean_text(item.get("instruction"))
        if not instruction:
            raise ValueError("planner-worker step instruction must be non-empty")
        step = {
            "schema_version": PLANNER_WORKER_STEP_SCHEMA_VERSION,
            "step_id": _clean_text(item.get("step_id")) or f"step-{index}",
            "planner_order": int(item.get("planner_order") or index),
            "role": _clean_text(item.get("role")) or "worker",
            "target_files": _clean_list(item.get("target_files")),
            "action_kind": _clean_text(item.get("action_kind")) or "edit",
            "recommended_executor": _clean_text(item.get("recommended_executor"))
            or _recommended_executor_for_step(item),
            "worker_model_tier": _clean_text(item.get("worker_model_tier"))
            or _worker_model_tier_for_step(item),
            "worker_ready": bool(
                item.get("worker_ready")
                if "worker_ready" in item
                else _recommended_executor_for_step(item) == "cheap_worker"
            ),
            "worker_blockers": _clean_list(item.get("worker_blockers")),
            "research_summary": _clean_text(item.get("research_summary"))
            or "Planner did not provide a separate research summary.",
            "implementation_notes": _clean_text(item.get("implementation_notes"))
            or "Follow the step instruction and keep execution scoped.",
            "instruction": instruction,
            "depends_on": _clean_list(item.get("depends_on")),
            "verification": _clean_text(item.get("verification")) or "Run the relevant focused checks.",
            "status": _clean_text(item.get("status")) or "planned",
        }
        steps.append(step)
    steps.sort(key=lambda value: (int(value.get("planner_order") or 0), str(value.get("step_id") or "")))
    return {
        "schema_version": PLANNER_WORKER_PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "objective": objective,
        "steps": steps,
    }


def estimate_text_tokens(text: str) -> int:
    clean = _clean_text(text)
    if not clean:
        return 0
    return max(1, (len(clean) + 3) // 4)


def _price_for_model(model: str, prices: dict[str, dict[str, float]]) -> dict[str, float]:
    return prices.get(model) or {"input": 0.0, "output": 0.0}


def project_planner_worker_cost(
    *,
    objective: str,
    task_instruction: str,
    plan: dict[str, Any],
    baseline_model: str = DEFAULT_PLANNER_MODEL,
    planner_model: str = DEFAULT_PLANNER_MODEL,
    worker_model: str = DEFAULT_WORKER_MODEL,
    baseline_worker_turns: int | None = None,
    worker_turns: int | None = None,
    model_token_prices_per_1k: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    normalized = normalize_planner_worker_plan(plan)
    task_tokens = estimate_text_tokens(objective) + estimate_text_tokens(task_instruction)
    plan_tokens = estimate_text_tokens(str(normalized))
    step_tokens = sum(estimate_text_tokens(str(step)) for step in normalized["steps"])
    step_count = len(normalized["steps"])
    baseline_turn_count = max(1, int(baseline_worker_turns or step_count))
    planner_worker_turn_count = max(1, int(worker_turns or step_count))
    baseline_input_tokens = baseline_turn_count * (task_tokens + plan_tokens)
    baseline_output_tokens = max(1, baseline_input_tokens // 3)
    planner_input_tokens = task_tokens
    planner_output_tokens = max(1, plan_tokens)
    worker_input_tokens = step_tokens + planner_worker_turn_count * max(1, task_tokens // 5)
    worker_output_tokens = max(1, worker_input_tokens // 3)
    prices = model_token_prices_per_1k or DEFAULT_MODEL_TOKEN_PRICES_PER_1K
    baseline_price = _price_for_model(baseline_model, prices)
    planner_price = _price_for_model(planner_model, prices)
    worker_price = _price_for_model(worker_model, prices)
    baseline_cost = (
        baseline_input_tokens * baseline_price["input"]
        + baseline_output_tokens * baseline_price["output"]
    ) / 1000
    planner_worker_cost = (
        planner_input_tokens * planner_price["input"]
        + planner_output_tokens * planner_price["output"]
        + worker_input_tokens * worker_price["input"]
        + worker_output_tokens * worker_price["output"]
    ) / 1000
    savings = baseline_cost - planner_worker_cost
    return {
        "schema_version": PLANNER_WORKER_COST_PROJECTION_SCHEMA_VERSION,
        "mode": "deterministic_projection",
        "baseline": {
            "model": baseline_model,
            "turns": baseline_turn_count,
            "input_tokens": baseline_input_tokens,
            "output_tokens": baseline_output_tokens,
            "total_tokens": baseline_input_tokens + baseline_output_tokens,
            "estimated_cost": round(baseline_cost, 6),
        },
        "planner_worker": {
            "planner_model": planner_model,
            "worker_model": worker_model,
            "worker_turns": planner_worker_turn_count,
            "planner_input_tokens": planner_input_tokens,
            "planner_output_tokens": planner_output_tokens,
            "worker_input_tokens": worker_input_tokens,
            "worker_output_tokens": worker_output_tokens,
            "total_tokens": (
                planner_input_tokens
                + planner_output_tokens
                + worker_input_tokens
                + worker_output_tokens
            ),
            "estimated_cost": round(planner_worker_cost, 6),
        },
        "comparison": {
            "estimated_savings": round(savings, 6),
            "estimated_savings_ratio": round(savings / baseline_cost, 6) if baseline_cost else 0.0,
        },
        "pricing": {
            "unit": "usd_per_1k_tokens",
            "model_token_prices_per_1k": prices,
        },
    }
