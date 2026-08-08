"""Bounded `quota should-run` decision and packet builder."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ...quota import (
    AUTONOMOUS_REPLAN_ACK_NEUTRAL_CLASSIFICATIONS,
    _QuotaDecisionPreparation,
    _build_quota_plan_for_goal,
    _build_quota_should_run_payload,
    _execution_obligation,
    _resolve_reward_memory_experiment_from_status,
    _resolve_quota_should_run_route,
    _scheduler_hint,
)
from ..agents.agent_lane_recommendation import (
    scope_status_item_to_agent_lane as _scope_status_item_to_agent_lane,
)
from ..agents.agent_scope import (
    _agent_scoped_user_todo_override,
    _attach_agent_identity_contracts,
    _scoped_user_gate_fallback,
)
from ..agents.identity import (
    build_identity_aware_prompt_upgrade,
    build_quota_agent_identity,
)
from ..agents.workspace_guard import build_agent_workspace_guard
from ..goals.goal_frontier import (
    build_goal_frontier_projection_context_from_status,
)
from ..quota.goal_boundary import (
    effective_available_capabilities as _effective_available_capabilities,
    goal_boundary as _goal_boundary,
)
from ..quota.policy_constants import MONITOR_DUE_ITEM_LIMIT
from ..quota.projection_repair import (
    build_boundary_projection_repair_hint,
    build_state_projection_gap,
    build_state_projection_gap_repair_hint,
)
from ..quota.recent_runs import (
    build_monitor_debt_arbitration as _build_monitor_debt_arbitration,
    goal_latest_runs as _goal_latest_runs,
)
from ..quota.selected_todo_projection import (
    selected_todo_projection as _selected_todo_projection,
)
from ..quota.stall_repair import (
    apply_stall_repair_delivery_guard,
    build_quota_stall_self_repair_hint,
    standing_decision_authority_from_status_item as _standing_decision_authority_from_status_item,
)
from ..quota.task_orchestration import (
    apply_task_orchestration_contract,
    build_quota_work_lane_contract,
)
from ..quota.decision_summary import quota_plan_items as _quota_plan_items
from ..quota.goal_boundary import registry_goal_by_id as _registry_goal_by_id
from ..quota.states import quota_item_is_paused as _quota_item_is_paused
from ..scheduler.automation_liveness import build_automation_liveness
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
    resolve_scheduler_execution_context,
)
from ..todos.contract import (
    TODO_STATUS_OPEN,
    TODO_TASK_CLASS_ADVANCEMENT,
    TODO_TASK_CLASS_BLOCKER,
    normalize_todo_claimed_by,
    normalize_todo_status,
)
from ..todos.projection import (
    todo_item_is_actionable_open as projection_todo_item_is_actionable_open,
    todo_item_task_class as projection_todo_item_task_class,
)
from ..todos.quota_summary import (
    select_quota_todo_source_items,
    select_quota_todo_summary,
    select_task_orchestration_authority_items,
)
from ..todos.summary_item import compact_todo_summary_item
from ..todos.user_gate import open_todo_count as _open_todo_count
from ..todos.write_hint import build_todo_write_hint
from ..work_items.capability_monitor_fallback import (
    build_capability_gate_with_monitor_fallback,
)
from ..work_items.interaction_contract import (
    build_interaction_contract,
    build_protocol_action_packet,
)
from ..work_items.primary_action import protocol_action_text as _protocol_action_text
from ..work_items.work_lane import (
    lark_inbox_reply_due_work_lane_contract,
    scoped_user_gate_due_monitor_contract,
    work_lane_contract_is_lark_inbox_reply_due,
)


QUOTA_PAUSED_MODE = "quota_paused"


def _same_todo_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_id = str(left.get("todo_id") or "").strip()
    right_id = str(right.get("todo_id") or "").strip()
    if left_id and right_id:
        return left_id == right_id
    return (
        left.get("index") == right.get("index")
        and str(left.get("text") or "").strip() == str(right.get("text") or "").strip()
    )


def _blocked_priority_fallback(
    agent_todo_summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(agent_todo_summary, dict):
        return None
    first_open = (
        agent_todo_summary.get("first_open_items")
        if isinstance(agent_todo_summary.get("first_open_items"), list)
        else []
    )
    first_executable = (
        agent_todo_summary.get("first_executable_items")
        if isinstance(agent_todo_summary.get("first_executable_items"), list)
        else []
    )
    selected = next((item for item in first_executable if isinstance(item, dict)), None)
    if not selected:
        return None

    blocked_items: list[dict[str, Any]] = []
    for item in first_open:
        if not isinstance(item, dict):
            continue
        if _same_todo_identity(item, selected):
            break
        if _todo_task_class(item) != TODO_TASK_CLASS_ADVANCEMENT:
            continue
        if item.get("done") is True:
            continue
        status = normalize_todo_status(item.get("status")) or TODO_STATUS_OPEN
        if status == TODO_STATUS_OPEN:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        blocked_items.append(compact_todo_summary_item(item, text=text))

    if not blocked_items:
        return None
    selected_text = str(selected.get("text") or "").strip()
    selected_item = compact_todo_summary_item(selected, text=selected_text) if selected_text else dict(selected)
    return {
        "schema_version": "blocked_priority_fallback_v0",
        "kind": "blocked_priority_fallback",
        "severity": "warning",
        "notify_user": False,
        "requires_user_action": False,
        "reason": (
            "a higher-priority agent todo is blocked or deferred before the "
            "selected executable fallback"
        ),
        "blocked_items": blocked_items[:3],
        "selected_executable": selected_item,
        "recommended_action": (
            "Keep the blocked core todo visible in status while selecting fallback; "
            "continue the fallback only if it still matches the latest user priority."
        ),
    }


def _automation_prompt_upgrade(
    goal: dict[str, Any],
    *,
    goal_id: str,
    agent_identity: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return build_identity_aware_prompt_upgrade(
        goal,
        goal_id=goal_id,
        agent_identity=agent_identity,
    )


def _todo_task_class(item: dict[str, Any]) -> str:
    return projection_todo_item_task_class(item)


def _todo_item_is_actionable_open(item: dict[str, Any]) -> bool:
    return projection_todo_item_is_actionable_open(item)


def _outcome_floor_blocker_already_projected(
    agent_todo_summary: dict[str, Any] | None,
) -> bool:
    if not isinstance(agent_todo_summary, dict):
        return False
    if _open_todo_count(agent_todo_summary) <= 0:
        return False

    executable_items = (
        agent_todo_summary.get("first_executable_items")
        if isinstance(agent_todo_summary.get("first_executable_items"), list)
        else []
    )
    if any(
        isinstance(item, dict) and _todo_item_is_actionable_open(item)
        for item in executable_items
    ):
        return False

    first_open = (
        agent_todo_summary.get("first_open_items")
        if isinstance(agent_todo_summary.get("first_open_items"), list)
        else []
    )
    visible_open = [
        item
        for item in first_open
        if isinstance(item, dict) and _todo_item_is_actionable_open(item)
    ]
    if not visible_open:
        return False
    visible_classes = [_todo_task_class(item) for item in visible_open]
    return (
        TODO_TASK_CLASS_BLOCKER in visible_classes
        and all(task_class != TODO_TASK_CLASS_ADVANCEMENT for task_class in visible_classes)
    )


def _recovery_delivery_allowed(quota: dict[str, Any], *, plan_ok: bool) -> bool:
    return (
        bool(plan_ok)
        and quota.get("safe_bypass_allowed") is True
        and str(quota.get("safe_bypass_kind") or "") == "outcome_floor_recovery"
    )


def _quota_agent_profile(agent_identity: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(agent_identity, dict):
        return None
    profile = agent_identity.get("agent_profile")
    return profile if isinstance(profile, dict) else None


def _agent_monitor_only(agent_identity: Mapping[str, Any] | None) -> bool:
    return bool(
        isinstance(agent_identity, Mapping)
        and agent_identity.get("work_mode") == "monitor_only"
    )


def _build_agent_work_lane(
    item: Mapping[str, Any],
    *,
    status_payload: Mapping[str, Any],
    project_asset: Mapping[str, Any],
    goal_id: str,
    agent_id: str | None,
    goal_boundary: Mapping[str, Any],
    agent_identity: Mapping[str, Any] | None,
    agent_todo_summary: Mapping[str, Any],
    agent_todo_source_items: list[dict[str, Any]],
    user_todo_source_items: list[dict[str, Any]],
    available_capabilities: Any,
    monitor_debt_arbitration: Mapping[str, Any] | None,
) -> tuple[bool, dict[str, Any], dict[str, Any] | None]:
    monitor_only = _agent_monitor_only(agent_identity)
    work_lane = build_quota_work_lane_contract(
        item,
        status_payload=status_payload,
        goal_id=goal_id,
        agent_id=agent_id,
        agent_todo_summary=agent_todo_summary,
        monitor_due_item_limit=MONITOR_DUE_ITEM_LIMIT,
        monitor_debt_arbitration=monitor_debt_arbitration,
        advancement_allowed=not monitor_only,
    )
    if monitor_only:
        return monitor_only, work_lane, None
    task_orchestration, work_lane = apply_task_orchestration_contract(
        fallback_work_lane_contract=work_lane,
        goal_boundary=goal_boundary,
        agent_identity=agent_identity,
        agent_todo_summary=agent_todo_summary,
        raw_agent_todo_summary=(
            item.get("agent_todos")
            if isinstance(item.get("agent_todos"), dict)
            else project_asset.get("agent_todos")
            if isinstance(project_asset.get("agent_todos"), dict)
            else None
        ),
        raw_user_todo_summary=(
            item.get("user_todos")
            if isinstance(item.get("user_todos"), dict)
            else project_asset.get("user_todos")
            if isinstance(project_asset.get("user_todos"), dict)
            else None
        ),
        agent_todo_source_items=agent_todo_source_items,
        user_todo_source_items=user_todo_source_items,
        available_capabilities=available_capabilities,
        parent_goal_id=goal_id,
    )
    return monitor_only, work_lane, task_orchestration


def _prepare_quota_should_run_item(
    status_payload: dict[str, Any],
    *,
    safe_goal_id: str,
    requested_agent_id: str | None,
    available_capabilities: Any,
    include_scheduler_detail: bool,
    codex_app_current_rrule: Any,
    resolved_scheduler_context: SchedulerExecutionContextResolution,
    operator_inbox_urgency_projector: Callable[..., dict[str, Any]] | None,
    registry_goal: dict[str, Any],
    plan: dict[str, Any],
    goal_health_ok: bool,
    item: dict[str, Any],
    health_items: list[Any],
) -> _QuotaDecisionPreparation:
    quota = item.get("quota") if isinstance(item.get("quota"), dict) else {}
    state = str(quota.get("state") or "unknown")
    normal_delivery_allowed = goal_health_ok and state == "eligible"
    recovery_allowed = _recovery_delivery_allowed(quota, plan_ok=goal_health_ok)
    reason = str(quota.get("reason") or "quota state is not eligible")
    if not goal_health_ok:
        reason = "status or contract health is not ok; skip automatic compute"
    agent_identity = build_quota_agent_identity(item, agent_id=requested_agent_id)
    item, project_asset, agent_lane_recommendation = _scope_status_item_to_agent_lane(
        item=item,
        latest_runs=_goal_latest_runs(status_payload, goal_id=safe_goal_id),
        agent_id=requested_agent_id,
        public_safe_compact_text=_protocol_action_text,
    )
    effective_available_capabilities = _effective_available_capabilities(
        available_capabilities,
        item=item,
        project_asset=project_asset,
    )
    user_todo_summary = select_quota_todo_summary(
        item.get("user_todos"),
        project_asset.get("user_todos") if project_asset else None,
        agent_identity=agent_identity,
        filter_user_gate_blocks_agent=True,
        available_capabilities=effective_available_capabilities,
    )
    agent_todo_summary = select_quota_todo_summary(
        item.get("agent_todos"),
        project_asset.get("agent_todos") if project_asset else None,
        agent_identity=agent_identity,
        available_capabilities=effective_available_capabilities,
    )
    user_todo_source_items = select_quota_todo_source_items(
        item.get("user_todos"),
        project_asset.get("user_todos") if project_asset else None,
    )
    agent_todo_source_items = select_quota_todo_source_items(
        item.get("agent_todos"),
        project_asset.get("agent_todos") if project_asset else None,
    )
    task_orchestration_agent_items = select_task_orchestration_authority_items(
        item.get("agent_todos"),
        project_asset.get("agent_todos") if project_asset else None,
        role="agent",
    )
    task_orchestration_user_blockers = select_task_orchestration_authority_items(
        item.get("user_todos"),
        project_asset.get("user_todos") if project_asset else None,
        role="user",
    )
    agent_scoped_user_todo_override = _agent_scoped_user_todo_override(
        state=state,
        item=item,
        user_todo_summary=user_todo_summary,
        agent_todo_summary=agent_todo_summary,
        agent_identity=agent_identity,
    )
    if agent_scoped_user_todo_override:
        state = str(agent_scoped_user_todo_override["to_state"])
        reason = str(agent_scoped_user_todo_override["reason"])
        quota = {
            **quota,
            **agent_scoped_user_todo_override.pop("quota_patch", {}),
            "state": state,
            str(agent_scoped_user_todo_override["kind"]): agent_scoped_user_todo_override,
            "reason": reason,
        }
        item = {**item, **agent_scoped_user_todo_override.pop("item_patch", {})}
        normal_delivery_allowed = goal_health_ok and state == "eligible"
        recovery_allowed = _recovery_delivery_allowed(quota, plan_ok=goal_health_ok)
    if recovery_allowed and _outcome_floor_blocker_already_projected(agent_todo_summary):
        quota = {
            **quota,
            "safe_bypass_allowed": False,
            "safe_bypass_kind": None,
            "outcome_floor_blocker_projected": True,
            "reason": (
                "handoff outcome floor blocker already projected: no executable "
                "agent todo exists; wait for fresh ranker/cross-domain evidence "
                "or a new manifest before spending recovery compute"
            ),
        }
        recovery_allowed = False
        reason = str(quota["reason"])
    boundary_agent_id = normalize_todo_claimed_by((agent_identity or {}).get("agent_id"))
    reward_memory_experiment_status = _resolve_reward_memory_experiment_from_status(
        status_payload,
        goal_id=safe_goal_id,
        agent_id=boundary_agent_id,
    )
    boundary_registry_value = str(status_payload.get("registry") or "").strip()
    goal_boundary = _goal_boundary(
        registry_goal or item,
        item=item,
        agent_id=boundary_agent_id,
        registry_path=Path(boundary_registry_value) if boundary_registry_value else None,
        operator_inbox_urgency_projector=operator_inbox_urgency_projector,
        reward_memory_experiment_status=reward_memory_experiment_status,
    )
    workspace_guard = None
    automation_prompt_upgrade = _automation_prompt_upgrade(
        item,
        goal_id=safe_goal_id,
        agent_identity=agent_identity,
    )
    automation_prompt_upgrade_required = bool(
        automation_prompt_upgrade
        and automation_prompt_upgrade.get("blocks_should_run") is True
    )
    blocked_priority_fallback = _blocked_priority_fallback(agent_todo_summary)
    stall_self_repair = build_quota_stall_self_repair_hint(
        item,
        state=state,
        plan_ok=goal_health_ok,
        health_items=health_items,
        user_todo_summary=user_todo_summary,
        agent_todo_summary=agent_todo_summary,
        agent_id=boundary_agent_id,
        user_todo_source_items=user_todo_source_items,
        agent_todo_source_items=agent_todo_source_items,
        standing_decision_authority=_standing_decision_authority_from_status_item(
            item,
            project_asset=project_asset,
            agent_id=boundary_agent_id,
        ),
        available_capabilities=effective_available_capabilities,
    )
    self_repair_allowed = bool(stall_self_repair and stall_self_repair.get("allowed"))
    normal_delivery_allowed, recovery_allowed, reason = apply_stall_repair_delivery_guard(
        stall_self_repair,
        normal_delivery_allowed=normal_delivery_allowed,
        recovery_allowed=recovery_allowed,
        reason=reason,
    )
    monitor_debt_arbitration = _build_monitor_debt_arbitration(
        status_payload,
        goal_id=safe_goal_id,
        agent_id=boundary_agent_id,
    )
    agent_monitor_only, work_lane_contract, task_orchestration_contract = (
        _build_agent_work_lane(
            item,
            status_payload=status_payload,
            project_asset=project_asset,
            goal_id=safe_goal_id,
            agent_id=boundary_agent_id,
            goal_boundary=goal_boundary,
            agent_identity=agent_identity,
            agent_todo_summary=agent_todo_summary,
            agent_todo_source_items=task_orchestration_agent_items,
            user_todo_source_items=task_orchestration_user_blockers,
            available_capabilities=available_capabilities,
            monitor_debt_arbitration=monitor_debt_arbitration,
        )
    )
    capability_gate, capability_monitor_contract, capability_monitor_fallback = (
        build_capability_gate_with_monitor_fallback(
            agent_todo_summary,
            available_capabilities=effective_available_capabilities,
            agent_identity=agent_identity,
            monitor_item_limit=MONITOR_DUE_ITEM_LIMIT,
        )
    )
    if task_orchestration_contract:
        capability_monitor_contract = capability_monitor_fallback = None
    work_lane_contract = capability_monitor_contract or work_lane_contract
    scoped_user_gate_fallback = _scoped_user_gate_fallback(
        user_todo_summary,
        agent_todo_summary,
        capability_gate=capability_gate,
        allow_unrelated_gate=bool(quota.get("safe_bypass_allowed")),
        monitor_debt_backoff_active=bool(monitor_debt_arbitration.get("active")),
    )
    work_lane_contract = (
        scoped_user_gate_due_monitor_contract(
            scoped_user_gate_fallback,
            current_contract=work_lane_contract,
        )
        or work_lane_contract
    )
    work_lane_contract = lark_inbox_reply_due_work_lane_contract(
        goal_boundary,
        current_contract=work_lane_contract,
    )
    inbox_reply_due = work_lane_contract_is_lark_inbox_reply_due(work_lane_contract)
    work_lane_selected_todo = _selected_todo_projection(
        agent_lane_next_action=None,
        work_lane_contract=work_lane_contract,
    )
    if inbox_reply_due:
        task_orchestration_contract = capability_gate = capability_monitor_contract = None
        capability_monitor_fallback = scoped_user_gate_fallback = workspace_guard = None
    else:
        workspace_guard = build_agent_workspace_guard(
            item,
            agent_identity,
            agent_todo_summary=agent_todo_summary,
            selected_todo=work_lane_selected_todo,
        )
    agent_frontier_id = (
        normalize_todo_claimed_by(agent_identity.get("agent_id"))
        if isinstance(agent_identity, dict)
        else None
    )
    registered_agent_ids = (
        list(agent_identity.get("registered_agents") or [])
        if isinstance(agent_identity, dict)
        else []
    )
    goal_frontier_context = build_goal_frontier_projection_context_from_status(
        goal_id=safe_goal_id,
        agent_id=agent_frontier_id,
        status_payload=status_payload,
        item=item,
        project_asset=project_asset,
        user_todo_summary=user_todo_summary,
        agent_todo_summary=agent_todo_summary,
        work_lane_contract=work_lane_contract,
        neutral_replan_ack_classifications=AUTONOMOUS_REPLAN_ACK_NEUTRAL_CLASSIFICATIONS,
        registered_agent_ids=registered_agent_ids,
        goal_status=str(registry_goal.get("status") or ""),
        agent_profile=_quota_agent_profile(agent_identity),
    )
    replan_obligation = goal_frontier_context.get("replan_obligation")
    replan_scope = goal_frontier_context.get("replan_scope") or {}
    goal_frontier_projection = (
        goal_frontier_context.get("goal_frontier_projection")
        if isinstance(goal_frontier_context.get("goal_frontier_projection"), dict)
        else {}
    )
    projection_gap = build_state_projection_gap(item, project_asset)
    projection_gap_repair = build_state_projection_gap_repair_hint(
        projection_gap,
        candidate_should_run=bool(
            normal_delivery_allowed or recovery_allowed or self_repair_allowed
        ),
        user_todo_summary=user_todo_summary,
        agent_todo_summary=agent_todo_summary,
        work_lane_contract=work_lane_contract,
    )
    if projection_gap_repair:
        stall_self_repair = projection_gap_repair
        self_repair_allowed = True
        normal_delivery_allowed = False
        recovery_allowed = False
        reason = str(projection_gap_repair.get("reason") or reason)
    boundary_projection_repair = build_boundary_projection_repair_hint(
        goal_boundary,
        agent_todo_summary,
        candidate_should_run=bool(
            normal_delivery_allowed or recovery_allowed or self_repair_allowed
        ),
        capability_gate=capability_gate,
        selected_todo=work_lane_selected_todo,
    )
    if boundary_projection_repair:
        stall_self_repair = boundary_projection_repair
        self_repair_allowed = True
        normal_delivery_allowed = False
        recovery_allowed = False
        reason = str(boundary_projection_repair.get("reason") or reason)
    return _QuotaDecisionPreparation(
        status_payload=status_payload,
        safe_goal_id=safe_goal_id,
        requested_agent_id=requested_agent_id,
        plan=plan,
        goal_health_ok=goal_health_ok,
        item=item,
        quota=quota,
        state=state,
        normal_delivery_allowed=normal_delivery_allowed,
        recovery_allowed=recovery_allowed,
        reason=reason,
        agent_identity=agent_identity,
        project_asset=project_asset,
        agent_lane_recommendation=agent_lane_recommendation,
        effective_available_capabilities=effective_available_capabilities,
        runtime_available_capabilities=available_capabilities,
        user_todo_summary=user_todo_summary,
        agent_todo_summary=agent_todo_summary,
        agent_scoped_user_todo_override=agent_scoped_user_todo_override,
        goal_boundary=goal_boundary,
        automation_prompt_upgrade=automation_prompt_upgrade,
        automation_prompt_upgrade_required=automation_prompt_upgrade_required,
        blocked_priority_fallback=blocked_priority_fallback,
        stall_self_repair=stall_self_repair,
        self_repair_allowed=self_repair_allowed,
        monitor_debt_arbitration=monitor_debt_arbitration,
        agent_monitor_only=agent_monitor_only,
        work_lane_contract=work_lane_contract,
        task_orchestration_contract=task_orchestration_contract,
        capability_gate=capability_gate,
        capability_monitor_fallback=capability_monitor_fallback,
        scoped_user_gate_fallback=scoped_user_gate_fallback,
        inbox_reply_due=inbox_reply_due,
        workspace_guard=workspace_guard,
        agent_frontier_id=agent_frontier_id,
        registered_agent_ids=registered_agent_ids,
        replan_obligation=replan_obligation,
        replan_scope=replan_scope,
        goal_frontier_projection=goal_frontier_projection,
        projection_gap=projection_gap,
        boundary_projection_repair=boundary_projection_repair,
        include_scheduler_detail=include_scheduler_detail,
        codex_app_current_rrule=codex_app_current_rrule,
        resolved_scheduler_context=resolved_scheduler_context,
    )
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
                resolved_scheduler_context=resolved_scheduler_context,
            )
        prepared = _prepare_quota_should_run_item(
            status_payload,
            safe_goal_id=safe_goal_id,
            requested_agent_id=agent_id,
            available_capabilities=available_capabilities,
            include_scheduler_detail=include_scheduler_detail,
            codex_app_current_rrule=codex_app_current_rrule,
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
