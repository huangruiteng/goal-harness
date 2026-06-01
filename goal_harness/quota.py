from __future__ import annotations

from typing import Any


DEFAULT_COMPUTE_QUOTA = 1.0
DEFAULT_WINDOW_HOURS = 24
QUOTA_STATE_ORDER = (
    "blocked_health",
    "operator_gate",
    "eligible",
    "waiting",
    "throttled",
    "paused",
)


def _number(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _int_number(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def _clamp_compute(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 2)


def goal_quota_config(goal: dict[str, Any] | None) -> dict[str, Any]:
    raw = goal.get("quota") if goal and isinstance(goal.get("quota"), dict) else {}
    if goal and "compute_quota" in goal and "compute" not in raw:
        raw = {**raw, "compute": goal.get("compute_quota")}
    compute = _clamp_compute(_number(raw.get("compute"), default=DEFAULT_COMPUTE_QUOTA))
    window_hours = max(1, _int_number(raw.get("window_hours"), default=DEFAULT_WINDOW_HOURS))
    spent_slots = max(0, _int_number(raw.get("spent_slots"), default=0))
    allowed_slots = max(0, _int_number(raw.get("allowed_slots"), default=round(window_hours * compute)))
    payload: dict[str, Any] = {
        "compute": compute,
        "window_hours": window_hours,
        "allowed_slots": allowed_slots,
        "spent_slots": spent_slots,
    }
    if raw.get("next_eligible_at"):
        payload["next_eligible_at"] = str(raw.get("next_eligible_at"))
    return payload


def quota_status(
    goal: dict[str, Any] | None,
    *,
    waiting_on: str | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    payload = goal_quota_config(goal)
    compute = float(payload["compute"])
    spent_slots = int(payload["spent_slots"])
    allowed_slots = int(payload["allowed_slots"])

    if compute <= 0:
        state = "paused"
        reason = "compute quota is 0; automatic agent turns are paused"
    elif severity == "high":
        state = "blocked_health"
        reason = "health or contract blocker must clear before compute is spent"
    elif waiting_on in {"user_or_controller", "controller"}:
        state = "operator_gate"
        reason = "human or target-controller gate must clear before spending compute"
    elif waiting_on == "external_evidence":
        state = "waiting"
        reason = "external evidence is still pending; do not spend delivery compute yet"
    elif waiting_on == "codex":
        if allowed_slots > 0 and spent_slots >= allowed_slots:
            state = "throttled"
            reason = f"{compute:g} compute quota spent {spent_slots}/{allowed_slots} slots in this window"
        else:
            state = "eligible"
            reason = f"{compute:g} compute quota; eligible for the next automatic agent turn"
    else:
        state = "waiting"
        reason = "no active Codex-ready work is currently selected"

    payload["state"] = state
    payload["reason"] = reason
    return payload


def _latest_run(goal: dict[str, Any]) -> dict[str, Any]:
    latest_runs = goal.get("latest_runs") if isinstance(goal.get("latest_runs"), list) else []
    if latest_runs and isinstance(latest_runs[0], dict):
        return latest_runs[0]
    return {}


def _quota_sort_key(item: dict[str, Any]) -> tuple[int, float, int, str]:
    quota = item.get("quota") if isinstance(item.get("quota"), dict) else {}
    state = str(quota.get("state") or "waiting")
    state_index = QUOTA_STATE_ORDER.index(state) if state in QUOTA_STATE_ORDER else len(QUOTA_STATE_ORDER)
    compute = _number(quota.get("compute"), default=DEFAULT_COMPUTE_QUOTA)
    spent_slots = _int_number(quota.get("spent_slots"), default=0)
    return (state_index, -compute, spent_slots, str(item.get("goal_id") or ""))


def build_quota_plan(status_payload: dict[str, Any], *, mode: str = "status") -> dict[str, Any]:
    queue = status_payload.get("attention_queue") if isinstance(status_payload.get("attention_queue"), dict) else {}
    queue_items = queue.get("items") if isinstance(queue.get("items"), list) else []
    queue_by_goal = {
        str(item.get("goal_id")): item
        for item in queue_items
        if isinstance(item, dict) and item.get("goal_id")
    }
    health_items = [
        item
        for item in queue_items
        if isinstance(item, dict) and not isinstance(item.get("quota"), dict)
    ]

    run_history = (
        status_payload.get("run_history")
        if isinstance(status_payload.get("run_history"), dict)
        else {}
    )
    run_goals = run_history.get("goals") if isinstance(run_history.get("goals"), list) else []
    groups: dict[str, list[dict[str, Any]]] = {state: [] for state in QUOTA_STATE_ORDER}
    groups["unknown"] = []

    for goal in run_goals:
        if not isinstance(goal, dict) or not goal.get("registry_member"):
            continue
        goal_id = str(goal.get("id") or "")
        attention = queue_by_goal.get(goal_id, {})
        latest = _latest_run(goal)
        quota = attention.get("quota") if isinstance(attention.get("quota"), dict) else goal.get("quota")
        quota = quota if isinstance(quota, dict) else quota_status(goal)
        state = str(quota.get("state") or "waiting")
        item: dict[str, Any] = {
            "goal_id": goal_id,
            "status": attention.get("status") or goal.get("status"),
            "lifecycle_phase": attention.get("lifecycle_phase") or goal.get("lifecycle_phase"),
            "waiting_on": attention.get("waiting_on") or "none",
            "severity": attention.get("severity") or "info",
            "source": attention.get("source") or "run_history",
            "recommended_action": attention.get("recommended_action") or latest.get("recommended_action"),
            "adapter_kind": goal.get("adapter_kind"),
            "adapter_status": goal.get("adapter_status"),
            "latest_run_generated_at": latest.get("generated_at"),
            "quota": quota,
        }
        for optional_field in (
            "operator_question",
            "agent_command",
            "controller_stage",
            "missing_gates",
            "next_handoff_condition",
        ):
            if optional_field in attention:
                item[optional_field] = attention[optional_field]
        groups.setdefault(state, []).append(item)

    for state_items in groups.values():
        state_items.sort(key=_quota_sort_key)

    ordered_items = [
        item
        for state in QUOTA_STATE_ORDER
        for item in groups.get(state, [])
    ] + groups.get("unknown", [])
    next_automatic_turn = (groups.get("eligible") or [None])[0]
    summary = {
        "registered_goals": len(ordered_items),
        "health_blockers": len(health_items),
        "next_automatic_turn": next_automatic_turn.get("goal_id") if next_automatic_turn else None,
        "states": {state: len(groups.get(state, [])) for state in QUOTA_STATE_ORDER},
    }
    if groups.get("unknown"):
        summary["states"]["unknown"] = len(groups["unknown"])

    return {
        "ok": status_payload.get("ok"),
        "mode": mode,
        "registry": status_payload.get("registry"),
        "runtime_root": status_payload.get("runtime_root"),
        "goal_count": status_payload.get("goal_count"),
        "run_count": status_payload.get("run_count"),
        "summary": summary,
        "next_automatic_turn": next_automatic_turn,
        "groups": groups,
        "health_items": health_items,
    }


def _quota_plan_items(plan: dict[str, Any]) -> list[dict[str, Any]]:
    groups = plan.get("groups") if isinstance(plan.get("groups"), dict) else {}
    items: list[dict[str, Any]] = []
    for state_items in groups.values():
        if not isinstance(state_items, list):
            continue
        items.extend(item for item in state_items if isinstance(item, dict))
    return items


def build_quota_should_run(status_payload: dict[str, Any], *, goal_id: str) -> dict[str, Any]:
    safe_goal_id = str(goal_id or "").strip()
    plan = build_quota_plan(status_payload, mode="should-run")
    item = next((candidate for candidate in _quota_plan_items(plan) if candidate.get("goal_id") == safe_goal_id), None)
    health_items = plan.get("health_items") if isinstance(plan.get("health_items"), list) else []
    health_item = next(
        (
            candidate
            for candidate in health_items
            if isinstance(candidate, dict) and candidate.get("goal_id") == safe_goal_id
        ),
        None,
    )

    if item:
        quota = item.get("quota") if isinstance(item.get("quota"), dict) else {}
        state = str(quota.get("state") or "unknown")
        should_run = bool(plan.get("ok")) and state == "eligible"
        reason = str(quota.get("reason") or "quota state is not eligible")
        if not plan.get("ok"):
            reason = "status or contract health is not ok; skip automatic compute"
        return {
            "ok": bool(plan.get("ok")),
            "mode": "should-run",
            "goal_id": safe_goal_id,
            "decision": "run" if should_run else "skip",
            "should_run": should_run,
            "reason": reason,
            "quota": quota,
            "state": state,
            "waiting_on": item.get("waiting_on"),
            "status": item.get("status"),
            "source": item.get("source"),
            "recommended_action": item.get("recommended_action"),
            "next_handoff_condition": item.get("next_handoff_condition"),
            "agent_command": item.get("agent_command"),
            "plan_summary": plan.get("summary"),
        }

    if health_item:
        return {
            "ok": False,
            "mode": "should-run",
            "goal_id": safe_goal_id,
            "decision": "skip",
            "should_run": False,
            "reason": str(health_item.get("recommended_action") or "health item blocks automatic compute"),
            "state": "blocked_health",
            "waiting_on": health_item.get("waiting_on"),
            "status": health_item.get("status"),
            "source": health_item.get("source"),
            "recommended_action": health_item.get("recommended_action"),
            "plan_summary": plan.get("summary"),
        }

    return {
        "ok": False,
        "mode": "should-run",
        "goal_id": safe_goal_id,
        "decision": "skip",
        "should_run": False,
        "reason": "goal is not present in the registered quota plan",
        "state": "unknown",
        "waiting_on": None,
        "status": "goal_not_found",
        "source": "quota",
        "recommended_action": "run `goal-harness registry` and connect or sync the goal before spending compute",
        "plan_summary": plan.get("summary"),
    }


def render_quota_markdown(payload: dict[str, Any]) -> str:
    title = "Quota Plan" if payload.get("mode") == "plan" else "Quota Status"
    lines = [
        f"# Goal Harness {title}",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- registry: `{payload.get('registry')}`",
        f"- runtime_root: `{payload.get('runtime_root')}`",
        f"- goals: `{payload.get('goal_count')}`",
        f"- runs: `{payload.get('run_count')}`",
    ]
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    states = summary.get("states") if isinstance(summary.get("states"), dict) else {}
    state_text = ", ".join(f"{state}={states.get(state, 0)}" for state in QUOTA_STATE_ORDER)
    lines.append(
        "- summary: "
        f"registered_goals={summary.get('registered_goals')}, "
        f"health_blockers={summary.get('health_blockers')}, "
        f"next_automatic_turn={summary.get('next_automatic_turn') or 'none'}"
    )
    lines.append(f"- states: {state_text}")

    next_turn = payload.get("next_automatic_turn") if isinstance(payload.get("next_automatic_turn"), dict) else {}
    lines.extend(["", "## Next Automatic Turn"])
    if next_turn:
        quota = next_turn.get("quota") if isinstance(next_turn.get("quota"), dict) else {}
        lines.append(
            "- "
            f"`{next_turn.get('goal_id')}` "
            f"compute={quota.get('compute')} "
            f"slots={quota.get('spent_slots')}/{quota.get('allowed_slots')} "
            f"action={next_turn.get('recommended_action') or 'inspect latest run'}"
        )
    else:
        lines.append("- none")

    health_items = payload.get("health_items") if isinstance(payload.get("health_items"), list) else []
    if health_items:
        lines.extend(["", "## Health Items"])
        for item in health_items:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- "
                f"`{item.get('goal_id')}` "
                f"severity={item.get('severity')} "
                f"waiting_on={item.get('waiting_on')} "
                f"action={item.get('recommended_action')}"
            )

    groups = payload.get("groups") if isinstance(payload.get("groups"), dict) else {}
    lines.extend(["", "## Groups"])
    render_states = list(QUOTA_STATE_ORDER)
    if groups.get("unknown"):
        render_states.append("unknown")
    for state in render_states:
        items = groups.get(state) if isinstance(groups.get(state), list) else []
        if payload.get("mode") == "plan" and not items:
            continue
        lines.extend(["", f"### {state}"])
        if not items:
            lines.append("- none")
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            quota = item.get("quota") if isinstance(item.get("quota"), dict) else {}
            action = str(item.get("recommended_action") or "").replace("|", "\\|")
            lines.append(
                "- "
                f"`{item.get('goal_id')}`: "
                f"compute={quota.get('compute')} "
                f"slots={quota.get('spent_slots')}/{quota.get('allowed_slots')} "
                f"waiting_on={item.get('waiting_on')} "
                f"status={item.get('status')} "
                f"phase={item.get('lifecycle_phase')}"
            )
            reason = quota.get("reason")
            if reason:
                lines.append(f"  - reason: {reason}")
            if action:
                lines.append(f"  - action: {action}")
            if item.get("agent_command"):
                lines.append(f"  - agent_command: `{item.get('agent_command')}`")
            if item.get("next_handoff_condition"):
                lines.append(f"  - next_handoff_condition: {item.get('next_handoff_condition')}")
    return "\n".join(lines)


def render_quota_should_run_markdown(payload: dict[str, Any]) -> str:
    quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
    lines = [
        "# Goal Harness Quota Should Run",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- should_run: `{payload.get('should_run')}`",
        f"- state: `{payload.get('state')}`",
        f"- waiting_on: `{payload.get('waiting_on')}`",
        f"- status: `{payload.get('status')}`",
    ]
    if quota:
        lines.append(
            "- quota: "
            f"compute={quota.get('compute')} "
            f"slots={quota.get('spent_slots')}/{quota.get('allowed_slots')}"
        )
    if payload.get("reason"):
        lines.append(f"- reason: {payload.get('reason')}")
    if payload.get("recommended_action"):
        lines.append(f"- recommended_action: {payload.get('recommended_action')}")
    if payload.get("agent_command"):
        lines.append(f"- agent_command: `{payload.get('agent_command')}`")
    if payload.get("next_handoff_condition"):
        lines.append(f"- next_handoff_condition: {payload.get('next_handoff_condition')}")
    summary = payload.get("plan_summary") if isinstance(payload.get("plan_summary"), dict) else {}
    states = summary.get("states") if isinstance(summary.get("states"), dict) else {}
    if summary:
        state_text = ", ".join(f"{state}={states.get(state, 0)}" for state in QUOTA_STATE_ORDER)
        lines.append(
            "- plan_summary: "
            f"next_automatic_turn={summary.get('next_automatic_turn') or 'none'} "
            f"{state_text}"
        )
    return "\n".join(lines)
