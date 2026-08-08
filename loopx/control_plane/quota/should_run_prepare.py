from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...quota import (
    AUTONOMOUS_REPLAN_ACK_NEUTRAL_CLASSIFICATIONS,
    _resolve_reward_memory_experiment_from_status,
)
from ..agents.agent_lane_recommendation import (
    scope_status_item_to_agent_lane as _scope_status_item_to_agent_lane,
)
from ..agents.agent_scope import (
    _agent_scoped_user_todo_override,
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
from ..quota.policy_constants import (
    MONITOR_DUE_ITEM_LIMIT,
)
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
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
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
from ..todos.user_gate import (
    open_todo_count as _open_todo_count,
)
from ..work_items.capability_monitor_fallback import (
    build_capability_gate_with_monitor_fallback,
)
from ..work_items.primary_action import protocol_action_text as _protocol_action_text
from ..work_items.work_lane import (
    lark_inbox_reply_due_work_lane_contract,
    scoped_user_gate_due_monitor_contract,
    work_lane_contract_is_lark_inbox_reply_due,
)

@dataclass(slots=True)
class _QuotaDecisionPreparation:
    status_payload: dict[str, Any]
    safe_goal_id: str
    requested_agent_id: str | None
    plan: dict[str, Any]
    goal_health_ok: bool
    item: dict[str, Any]
    quota: dict[str, Any]
    state: str
    normal_delivery_allowed: bool
    recovery_allowed: bool
    reason: str
    agent_identity: dict[str, Any] | None
    project_asset: dict[str, Any]
    agent_lane_recommendation: Any
    effective_available_capabilities: Any
    runtime_available_capabilities: Any
    user_todo_summary: dict[str, Any] | None
    agent_todo_summary: dict[str, Any] | None
    agent_scoped_user_todo_override: dict[str, Any] | None
    goal_boundary: dict[str, Any] | None
    automation_prompt_upgrade: dict[str, Any] | None
    automation_prompt_upgrade_required: bool
    blocked_priority_fallback: dict[str, Any] | None
    stall_self_repair: dict[str, Any] | None
    self_repair_allowed: bool
    monitor_debt_arbitration: dict[str, Any]
    agent_monitor_only: bool
    work_lane_contract: dict[str, Any] | None
    task_orchestration_contract: dict[str, Any] | None
    capability_gate: dict[str, Any] | None
    capability_monitor_fallback: dict[str, Any] | None
    scoped_user_gate_fallback: dict[str, Any] | None
    inbox_reply_due: bool
    workspace_guard: dict[str, Any] | None
    agent_frontier_id: str | None
    registered_agent_ids: list[str]
    replan_obligation: dict[str, Any] | None
    replan_scope: dict[str, Any]
    goal_frontier_projection: dict[str, Any]
    projection_gap: dict[str, Any] | None
    boundary_projection_repair: dict[str, Any] | None
    include_scheduler_detail: bool
    codex_app_current_rrule: Any
    resolved_scheduler_context: SchedulerExecutionContextResolution

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
