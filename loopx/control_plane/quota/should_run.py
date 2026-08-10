from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ...quota import (
    _build_quota_plan_for_goal,
)
from ..agents.agent_scope import (
    _attach_agent_identity_contracts,
)
from ..agents.identity import (
    build_quota_agent_identity,
)
from ..quota.goal_boundary import (
    registry_goal_by_id as _registry_goal_by_id,
)
from ..quota.decision_summary import (
    quota_plan_items as _quota_plan_items,
)
from ..quota.states import quota_item_is_paused as _quota_item_is_paused
from ..scheduler.automation_liveness import build_automation_liveness
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
    resolve_scheduler_execution_context,
)
from ..todos.write_hint import build_todo_write_hint
from ..work_items.interaction_contract import (
    build_interaction_contract,
    build_protocol_action_packet,
)

from .should_run_packet import (
    _build_quota_should_run_payload,
    _execution_obligation,
    _resolve_quota_should_run_route,
    _scheduler_hint,
)
from .should_run_prepare import _prepare_quota_should_run_item


QUOTA_PAUSED_MODE = "quota_paused"


def build_quota_paused_should_run_payload(
    status_payload: dict[str, Any],
    *,
    safe_goal_id: str,
    requested_agent_id: str | None,
    item: dict[str, Any],
    plan: dict[str, Any],
    goal_health_ok: bool,
    include_scheduler_detail: bool,
    codex_app_current_rrule: Any,
    codex_app_automation_id: Any = None,
    resolved_scheduler_context: SchedulerExecutionContextResolution,
) -> dict[str, Any]:
    """Project one canonical paused contract with no contradicting lane authority.

    The whole Goal is hard-paused, so every automatic authority field resolves to
    the same terminal decision: `should_run=false`, all delivery/repair
    permissions false, `DONT_NOTIFY`, no quota spend, and a scheduler cadence that
    is never `run_now`. No capability_gate, workspace_guard, replan, monitor, or
    inbox candidate is constructed here.
    """

    quota = item.get("quota") if isinstance(item.get("quota"), dict) else {}
    quota = {**quota, "state": "paused"}
    reason = str(
        quota.get("reason")
        or "compute quota is 0; the whole Goal is hard-paused and automatic agent turns stop"
    )
    agent_identity = build_quota_agent_identity(item, agent_id=requested_agent_id)
    heartbeat_recommendation = {
        "source": "quota.should-run",
        "recommended_mode": QUOTA_PAUSED_MODE,
        "notify": "DONT_NOTIFY",
        "reason": reason,
        "spend_policy": "do not append quota spend while the Goal is paused",
    }
    execution_obligation = _execution_obligation(
        should_run=False,
        effective_action="quota_skip",
        heartbeat_recommendation=heartbeat_recommendation,
    )
    payload: dict[str, Any] = {
        "ok": goal_health_ok,
        "status_health_ok": goal_health_ok,
        "mode": "should-run",
        "goal_id": safe_goal_id,
        "decision": "skip",
        "should_run": False,
        "normal_delivery_allowed": False,
        "recovery_delivery_allowed": False,
        "self_repair_allowed": False,
        "capability_repair_allowed": False,
        "workspace_repair_allowed": False,
        "effective_action": "quota_skip",
        "actionable_by_codex": False,
        "reason": reason,
        "quota": quota,
        "state": "paused",
        "safe_bypass_allowed": False,
        "waiting_on": item.get("waiting_on"),
        "status": item.get("status"),
        "lifecycle_phase": item.get("lifecycle_phase"),
        "lifecycle_flags": item.get("lifecycle_flags"),
        "source": item.get("source"),
        "recommended_action": reason,
        "requires_user_action": False,
        "heartbeat_recommendation": heartbeat_recommendation,
        "execution_obligation": execution_obligation,
        "plan_summary": plan.get("summary"),
        "todo_write_hint": build_todo_write_hint(safe_goal_id),
    }
    payload = _attach_agent_identity_contracts(
        payload=payload,
        agent_identity=agent_identity,
    )
    payload["automation_liveness"] = build_automation_liveness(payload)
    payload["interaction_contract"] = build_interaction_contract(
        payload,
        available_capabilities=None,
        scheduler_execution_context=resolved_scheduler_context,
    )
    payload["scheduler_hint"] = _scheduler_hint(
        payload,
        include_detail=include_scheduler_detail,
        available_capabilities=None,
        codex_app_current_rrule=codex_app_current_rrule,
        codex_app_automation_id=codex_app_automation_id,
        scheduler_execution_context=resolved_scheduler_context,
    )
    payload["protocol_action_packet"] = build_protocol_action_packet(payload)
    return payload


def build_quota_should_run(
    status_payload: dict[str, Any],
    *,
    goal_id: str,
    agent_id: str | None = None,
    available_capabilities: Any = None,
    include_scheduler_detail: bool = False,
    codex_app_current_rrule: Any = None,
    codex_app_automation_id: Any = None,
    scheduler_execution_context: (
        Mapping[str, Any] | SchedulerExecutionContextResolution | None
    ) = None,
    operator_inbox_urgency_projector: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    safe_goal_id = str(goal_id or "").strip()
    resolved_scheduler_context = resolve_scheduler_execution_context(
        scheduler_execution_context
    )
    registry_goal = _registry_goal_by_id(status_payload).get(safe_goal_id) or {}
    plan, goal_health_ok = _build_quota_plan_for_goal(
        status_payload,
        goal_id=safe_goal_id,
    )
    item = next(
        (
            candidate
            for candidate in _quota_plan_items(plan)
            if candidate.get("goal_id") == safe_goal_id
        ),
        None,
    )
    health_items = (
        plan.get("health_items")
        if isinstance(plan.get("health_items"), list)
        else []
    )
    health_item = next(
        (
            candidate
            for candidate in health_items
            if isinstance(candidate, dict) and candidate.get("goal_id") == safe_goal_id
        ),
        None,
    )
    if item:
        if _quota_item_is_paused(item):
            return build_quota_paused_should_run_payload(
                status_payload,
                safe_goal_id=safe_goal_id,
                requested_agent_id=agent_id,
                item=item,
                plan=plan,
                goal_health_ok=goal_health_ok,
                include_scheduler_detail=include_scheduler_detail,
                codex_app_current_rrule=codex_app_current_rrule,
                codex_app_automation_id=codex_app_automation_id,
                resolved_scheduler_context=resolved_scheduler_context,
            )
        prepared = _prepare_quota_should_run_item(
            status_payload,
            safe_goal_id=safe_goal_id,
            requested_agent_id=agent_id,
            available_capabilities=available_capabilities,
            include_scheduler_detail=include_scheduler_detail,
            codex_app_current_rrule=codex_app_current_rrule,
            codex_app_automation_id=codex_app_automation_id,
            resolved_scheduler_context=resolved_scheduler_context,
            operator_inbox_urgency_projector=operator_inbox_urgency_projector,
            registry_goal=registry_goal,
            plan=plan,
            goal_health_ok=goal_health_ok,
            item=item,
            health_items=health_items,
        )
        return _build_quota_should_run_payload(
            prepared,
            _resolve_quota_should_run_route(prepared),
        )
    if health_item:
        return {
            "ok": False,
            "mode": "should-run",
            "goal_id": safe_goal_id,
            "decision": "skip",
            "should_run": False,
            "reason": str(
                health_item.get("recommended_action")
                or "health item blocks automatic compute"
            ),
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
        "recommended_action": (
            "run `loopx registry` and connect or sync the goal before spending compute"
        ),
        "plan_summary": plan.get("summary"),
    }
