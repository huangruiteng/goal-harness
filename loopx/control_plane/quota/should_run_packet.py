from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...state_projection import (
    next_action_projection_warning,
    state_action_projection_warning as build_state_action_projection_warning,
)
from .. import compact_control_plane_policy
from ..agents.agent_lane_recommendation import (
    build_agent_lane_next_action,
    selected_action_with_agent_lane,
    selected_recommended_action_from_work_lane,
)
from ..agents.agent_scope import (
    AgentScopeFrontierAction,
    _action_scope_tokens_from_text,
    _agent_lane_frontier_hint,
    _agent_scope_deferred_resume_candidates,
    _agent_scope_frontier_action,
    _agent_scope_no_candidate_frontier,
    _attach_agent_identity_contracts,
)
from ..goals.goal_frontier import (
    AUTONOMOUS_REPLAN_REQUIRED_MODE,
)
from ..quota.goal_boundary import (
    quota_execution_profile_summary as _quota_execution_profile_summary,
)
from ..quota.decision_summary import (
    quota_decision_agent_id,
    refine_quota_recommended_action,
    resolve_quota_run_decision,
)
from ..quota.heartbeat_recommendation import (
    build_heartbeat_recommendation,
    refine_heartbeat_recommendation,
)
from ..quota.policy_constants import (
    AUTONOMOUS_CANDIDATE_CONTEXT_FIELDS,
    MONITOR_DUE_ITEM_LIMIT,
)
from ..quota.recent_runs import (
    goal_latest_runs as _goal_latest_runs,
    recent_external_monitor_observation_unchanged as _recent_external_monitor_observation_unchanged,
)
from ..quota.selected_todo_projection import (
    selected_todo_projection as _selected_todo_projection,
)
from ..quota.stall_repair import (
    stall_repair_blocked_action_scope,
    stall_repair_payload,
    standing_decision_authority_payload_from_status_item as _standing_decision_authority_payload_from_status_item,
)
from ..quota.task_orchestration import (
    attach_task_orchestration_payload,
    payload_work_lane_contract as _payload_work_lane_contract,
    task_goal_route_hint,
)
from ..scheduler.automation_liveness import build_automation_liveness
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
)
from ..scheduler.external_evidence_observation import (
    build_external_evidence_observation_obligation,
)
from ..scheduler.scheduler_hint import build_scheduler_hint
from ..scheduler.state import (
    CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
    CODEX_APP_SURFACE,
    load_scheduler_state,
)
from ..runtime.agent_scoped_evidence_log import build_agent_scoped_required_read
from ..runtime.decision_freshness import decision_freshness_warning as _decision_freshness_warning
from ..runtime.promotion_readiness import promotion_readiness_warning as _promotion_readiness_warning
from ..todos.contract import (
    normalize_todo_claimed_by,
)
from ..todos.quota_summary import (
    compact_quota_todo_summary_for_payload,
)
from ..todos.user_gate import (
    apply_scoped_user_gate_fallback_projection as _apply_scoped_user_gate_fallback_projection,
    build_gate_prompt as _build_gate_prompt,
    build_user_todo_notification as _build_user_todo_notification,
)
from ..todos.write_hint import build_todo_write_hint
from ..work_items.execution_obligation import build_execution_obligation
from ..work_items.goal_route_hint import build_goal_route_hint
from ..work_items.interaction_contract import (
    build_interaction_contract,
    build_protocol_action_packet,
    finalize_user_gate_notification_cooldown,
    user_channel_action_required as _user_channel_action_required,
)
from ..work_items.primary_action import protocol_action_text as _protocol_action_text
from ..work_items.work_lane import (
    work_lane_contract_is_due_monitor_attempt,
)

from .should_run_prepare import _QuotaDecisionPreparation

def _compact_autonomous_candidate_context(
    value: Any,
    *,
    goal_id: str | None = None,
    limit: int = 3,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    compact = {field: value[field] for field in AUTONOMOUS_CANDIDATE_CONTEXT_FIELDS if field in value}
    items = compact.get("items")
    if isinstance(items, list):
        compact_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if goal_id and str(item.get("goal_id") or "") != goal_id:
                continue
            compact_item = {
                key: item[key]
                for key in ("goal_id", "task_class", "text")
                if item.get(key) is not None
            }
            if compact_item:
                compact_items.append(compact_item)
            if len(compact_items) >= limit:
                break
        if not compact_items:
            return None
        compact["items"] = compact_items
        compact["open_count"] = len(compact_items)
    return compact or None


def _scheduler_hint(
    payload: dict[str, Any], *, include_detail: bool = False,
    codex_app_scheduler_state: dict[str, Any] | None = None, available_capabilities: Any = None, codex_app_current_rrule: Any = None,
    scheduler_execution_context: Mapping[str, Any] | SchedulerExecutionContextResolution | None = None,
) -> dict[str, Any]:
    return build_scheduler_hint(
        payload,
        user_action_required=_user_channel_action_required(payload),
        agent_scope_frontier_actions=[action.value for action in AgentScopeFrontierAction],
        include_detail=include_detail,
        codex_app_scheduler_state=codex_app_scheduler_state,
        available_capabilities=available_capabilities, codex_app_current_rrule=codex_app_current_rrule,
        scheduler_execution_context=scheduler_execution_context,
    )


def _load_codex_app_scheduler_state(
    status_payload: dict[str, Any],
    *,
    goal_id: str,
    agent_id: str | None,
) -> dict[str, Any] | None:
    raw_runtime_root = status_payload.get("runtime_root")
    safe_agent_id = normalize_todo_claimed_by(agent_id)
    if not raw_runtime_root or not safe_agent_id:
        return None
    return load_scheduler_state(
        Path(str(raw_runtime_root)).expanduser(),
        goal_id=goal_id,
        agent_id=safe_agent_id,
        surface=CODEX_APP_SURFACE,
        state_key=CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
    )


def _execution_obligation(
    *,
    should_run: bool,
    effective_action: str,
    heartbeat_recommendation: dict[str, Any],
    work_lane_contract: dict[str, Any] | None = None,
    external_evidence_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_execution_obligation(
        should_run=should_run,
        effective_action=effective_action,
        heartbeat_recommendation=heartbeat_recommendation,
        work_lane_contract=work_lane_contract,
        external_evidence_observation=external_evidence_observation,
        successor_replan_mode=AgentScopeFrontierAction.SUCCESSOR_REPLAN_REQUIRED.value,
    )


def _recent_reward_lessons(status_payload: dict[str, Any], *, goal_id: str) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    for run in _goal_latest_runs(status_payload, goal_id=goal_id):
        reward = run.get("human_reward") if isinstance(run.get("human_reward"), dict) else {}
        lesson = reward.get("lesson") if isinstance(reward.get("lesson"), dict) else {}
        if not lesson:
            continue
        lessons.append(
            {
                "generated_at": run.get("generated_at"),
                "decision": reward.get("decision"),
                "reward": reward.get("reward"),
                "kind": lesson.get("kind"),
                "summary": lesson.get("summary"),
                "avoid": lesson.get("avoid") if isinstance(lesson.get("avoid"), list) else [],
                "prefer": lesson.get("prefer") if isinstance(lesson.get("prefer"), list) else [],
            }
        )
    return lessons


def _reward_lesson_projection_warning(
    status_payload: dict[str, Any],
    *,
    goal_id: str,
    recommended_action: str | None,
) -> dict[str, Any] | None:
    action = str(recommended_action or "").strip()
    if not action:
        return None
    action_lower = action.lower()
    action_tokens = _action_scope_tokens_from_text(action)
    matches: list[dict[str, Any]] = []
    for lesson in _recent_reward_lessons(status_payload, goal_id=goal_id):
        for avoid in lesson.get("avoid") or []:
            avoid_text = str(avoid or "").strip()
            if not avoid_text:
                continue
            avoid_tokens = _action_scope_tokens_from_text(avoid_text)
            exact_match = avoid_text.lower() in action_lower
            if not exact_match and not avoid_tokens:
                continue
            token_overlap = sorted(action_tokens & avoid_tokens)
            if not exact_match and len(token_overlap) < min(2, len(avoid_tokens)):
                continue
            matches.append(
                {
                    "generated_at": lesson.get("generated_at"),
                    "decision": lesson.get("decision"),
                    "kind": lesson.get("kind"),
                    "summary": lesson.get("summary"),
                    "avoid": avoid_text,
                    "token_overlap": token_overlap[:5],
                }
            )
    if not matches:
        return None
    return {
        "schema_version": "reward_lesson_projection_warning_v0",
        "source": "run_history.human_reward.lesson",
        "goal_id": goal_id,
        "message": (
            "recommended_action overlaps a recent human_reward lesson avoid rule; "
            "rebase the route or update the affected todo/next action before continuing"
        ),
        "recommended_action": action,
        "match_count": len(matches),
        "matches": matches[:3],
    }


def _apply_agent_monitor_only_precedence(
    payload: dict[str, Any],
    *,
    monitor_only: bool,
    inbox_reply_due: bool,
) -> None:
    """Keep monitor/reply lanes alive while suppressing advancement work.

    This final precedence pass prevents autonomous replan, repair, or fallback
    from turning a configured monitor-only peer back into an advancement lane.
    """

    if not monitor_only or inbox_reply_due:
        return
    work_lane = (
        payload.get("work_lane_contract")
        if isinstance(payload.get("work_lane_contract"), dict)
        else {}
    )
    monitor_lane = work_lane.get("lane") == "continuous_monitor"
    monitor_due = monitor_lane and work_lane.get("must_attempt_work") is True
    if monitor_lane:
        reason = (
            "agent work mode is monitor_only; run the due monitor without "
            "opening an advancement or autonomous replan lane"
            if monitor_due
            else "agent work mode is monitor_only; wait quietly for the next "
            "material monitor transition or direct operator reply"
        )
        payload.update(
            {
                "decision": "run" if monitor_due else "skip",
                "should_run": monitor_due,
                "normal_delivery_allowed": monitor_due,
                "recovery_delivery_allowed": False,
                "self_repair_allowed": False,
                "capability_repair_allowed": False,
                "workspace_repair_allowed": False,
                "effective_action": "monitor_due" if monitor_due else "monitor_quiet_skip",
                "actionable_by_codex": monitor_due,
                "reason": reason,
                "blocked_action_scope": "advancement_work",
                "safe_bypass_allowed": False,
                "safe_bypass_kind": None,
                "safe_bypass_policy": None,
                "requires_user_action": False,
                "agent_work_mode": "monitor_only",
                "recommended_action": work_lane.get("action"),
                "heartbeat_recommendation": {
                    "recommended_mode": (
                        "monitor_due"
                        if monitor_due
                        else "monitor_quiet_until_material_transition"
                    ),
                    "notify": "DONT_NOTIFY",
                    "reason": reason,
                    "spend_policy": (
                        "spend only after a validated material monitor transition; "
                        "unchanged monitor polls are no-spend"
                    ),
                },
                "execution_obligation": {
                    "must_attempt_work": monitor_due,
                    "kind": "work_lane_contract" if monitor_due else "monitor_quiet_skip",
                    "contract": "work_lane_contract",
                    "contract_obligation": work_lane.get("obligation"),
                    "delivery_allowed": monitor_due,
                    "notify_is_execution_gate": False,
                    "reason": reason,
                },
            }
        )
    else:
        reason = (
            "agent work mode is monitor_only; advancement, autonomous replan, "
            "repair, and fallback remain paused until an explicit mode change"
        )
        payload.update(
            {
                "decision": "skip",
                "should_run": False,
                "normal_delivery_allowed": False,
                "recovery_delivery_allowed": False,
                "self_repair_allowed": False,
                "capability_repair_allowed": False,
                "workspace_repair_allowed": False,
                "effective_action": "agent_monitor_only",
                "actionable_by_codex": False,
                "reason": reason,
                "blocked_action_scope": "advancement_work",
                "safe_bypass_allowed": False,
                "safe_bypass_kind": None,
                "safe_bypass_policy": None,
                "requires_user_action": False,
                "agent_work_mode": "monitor_only",
                "recommended_action": (
                    "Wait for a due monitor, verified direct operator reply, or "
                    "explicit work-mode change."
                ),
                "heartbeat_recommendation": {
                    "recommended_mode": "agent_monitor_only",
                    "notify": "DONT_NOTIFY",
                    "reason": reason,
                    "spend_policy": "do not append quota spend while advancement is paused",
                },
                "execution_obligation": {
                    "must_attempt_work": False,
                    "kind": "agent_monitor_only",
                    "delivery_allowed": False,
                    "notify_is_execution_gate": False,
                    "reason": reason,
                    "spend_policy": "do not append quota spend while advancement is paused",
                },
            }
        )
    monitor_selected_todo = (
        _selected_todo_projection(
            agent_lane_next_action=None,
            work_lane_contract=work_lane,
        )
        if monitor_due
        else None
    )
    if monitor_selected_todo:
        payload["selected_todo"] = monitor_selected_todo
    else:
        payload.pop("selected_todo", None)
    frontier = payload.get("goal_frontier_projection")
    if isinstance(frontier, dict):
        frontier.pop("vision_continuation_audit", None)
    for key in (
        "agent_command",
        "agent_lane_frontier_hint",
        "agent_lane_next_action",
        "agent_scope_frontier",
        "autonomous_replan_decision",
        "autonomous_replan_obligation",
        "autonomous_replan_scope",
        "blocked_priority_fallback",
        "capability_gate",
        "capability_monitor_fallback",
        "external_evidence_observation",
        "goal_route_hint",
        "notify_user_on_capability_gate",
        "notify_user_on_gate",
        "notify_user_on_open_todo",
        "open_todo_notification_policy",
        "open_todo_notify_reason",
        "required_reads",
        "scoped_user_gate_fallback",
        "stall_self_repair",
        "vision_continuation_audit",
        "vision_wait_state",
        "workspace_guard",
    ):
        payload.pop(key, None)


def _attach_truthy_fields(payload: dict[str, Any], **fields: Any) -> None:
    payload.update({key: value for key, value in fields.items() if value})


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    return payload.get(key) if isinstance(payload.get(key), dict) else None


def _attach_quota_supporting_projections(
    payload: dict[str, Any],
    *,
    status_payload: dict[str, Any],
    item: dict[str, Any],
    project_asset: dict[str, Any],
    goal_id: str,
    selected_recommended_action: Any,
    state: str,
    user_todo_summary: dict[str, Any] | None,
    should_run: bool,
    state_action_projection_warning: dict[str, Any] | None,
    next_action_warning: dict[str, Any] | None,
    replan_obligation: dict[str, Any] | None,
) -> None:
    _attach_truthy_fields(
        payload,
        stale_latest_run_warning=_dict_field(item, "stale_latest_run_warning"),
        state_action_projection_warning=state_action_projection_warning,
        next_action_projection_warning=next_action_warning,
        backlog_hygiene_warning=_dict_field(item, "backlog_hygiene_warning"),
        completed_todo_archive_warning=_dict_field(item, "completed_todo_archive_warning"),
        autonomous_replan_obligation=replan_obligation,
        dreaming_proposal=_dict_field(item, "dreaming_proposal"),
        dreaming_lane_badge=_dict_field(item, "dreaming_lane_badge"),
        interface_budget_cadence=_dict_field(project_asset, "interface_budget_cadence"),
        decision_freshness_warning=_decision_freshness_warning(status_payload, goal_id=goal_id),
        promotion_readiness_warning=_promotion_readiness_warning(status_payload),
        reward_lesson_projection_warning=_reward_lesson_projection_warning(
            status_payload,
            goal_id=goal_id,
            recommended_action=selected_recommended_action,
        ),
    )
    if state == "operator_gate" and (
        gate_prompt := _build_gate_prompt(item, user_todo_summary=user_todo_summary)
    ):
        payload["gate_prompt"] = gate_prompt
        payload["notify_user_on_gate"] = True
    _attach_truthy_fields(
        payload, next_handoff_condition=item.get("next_handoff_condition"),
        agent_command=item.get("agent_command") if should_run else None,
    )

@dataclass(slots=True)
class _QuotaDecisionRoute:
    normal_delivery_allowed: bool
    recovery_allowed: bool
    self_repair_allowed: bool
    capability_repair_allowed: bool
    workspace_repair_allowed: bool
    should_run: bool
    effective_action: str
    reason: str
    state: str
    quota: dict[str, Any]
    replan_decision_allowed: bool
    heartbeat_recommendation: dict[str, Any]
    external_evidence_observation: dict[str, Any] | None
    external_evidence_observation_recent: dict[str, Any] | None
    selected_recommended_action: Any
    agent_lane_next_action: dict[str, Any] | None
    agent_scope_frontier: dict[str, Any] | None
    agent_lane_frontier_hint: dict[str, Any] | None
    state_action_projection_warning: dict[str, Any] | None
    active_state_next_action_text: str
    latest_run_recommended_action_text: str
    next_action_warning: dict[str, Any] | None
    goal_route_hint: dict[str, Any] | None
    payload_work_lane_contract: dict[str, Any] | None


def _resolve_quota_should_run_route(
    prepared: _QuotaDecisionPreparation,
) -> _QuotaDecisionRoute:
    item = prepared.item
    normal_delivery_allowed = prepared.normal_delivery_allowed
    recovery_allowed = prepared.recovery_allowed
    self_repair_allowed = prepared.self_repair_allowed
    state = prepared.state
    quota = prepared.quota
    reason = prepared.reason
    run_decision = resolve_quota_run_decision(
        normal_delivery_allowed=normal_delivery_allowed,
        recovery_delivery_allowed=recovery_allowed,
        self_repair_allowed=self_repair_allowed,
        stall_self_repair=prepared.stall_self_repair,
        state=state,
        quota=quota,
        reason=reason,
        capability_gate=prepared.capability_gate,
        capability_monitor_fallback=prepared.capability_monitor_fallback,
        workspace_guard=prepared.workspace_guard,
        automation_prompt_upgrade=prepared.automation_prompt_upgrade,
        automation_prompt_upgrade_required=prepared.automation_prompt_upgrade_required,
        replan_obligation=prepared.replan_obligation,
        goal_health_ok=prepared.goal_health_ok,
        inbox_reply_due=prepared.inbox_reply_due,
        agent_frontier_id=prepared.agent_frontier_id,
        registered_agent_ids=prepared.registered_agent_ids,
        goal_frontier_projection=prepared.goal_frontier_projection,
        task_orchestration_contract=prepared.task_orchestration_contract,
    )
    normal_delivery_allowed = run_decision.normal_delivery_allowed
    recovery_allowed = run_decision.recovery_delivery_allowed
    self_repair_allowed = run_decision.self_repair_allowed
    capability_repair_allowed = run_decision.capability_repair_allowed
    workspace_repair_allowed = run_decision.workspace_repair_allowed
    should_run = run_decision.should_run
    effective_action = run_decision.effective_action
    reason = run_decision.reason
    state = run_decision.state
    quota = run_decision.quota
    replan_decision_allowed = run_decision.replan_decision_allowed
    heartbeat_recommendation = build_heartbeat_recommendation(
        {**item, "quota": quota},
        goal_id=prepared.safe_goal_id,
        state=state,
        should_run=should_run,
        user_todo_summary=prepared.user_todo_summary,
        agent_todo_summary=prepared.agent_todo_summary,
        work_lane_contract=prepared.work_lane_contract,
        stall_self_repair=prepared.stall_self_repair,
        replan_obligation=prepared.replan_obligation,
        select_replan_obligation=False,
        monitor_due_item_limit=MONITOR_DUE_ITEM_LIMIT,
    )
    heartbeat_recommendation = refine_heartbeat_recommendation(
        heartbeat_recommendation,
        should_run=should_run,
        capability_gate=prepared.capability_gate,
        capability_monitor_fallback=prepared.capability_monitor_fallback,
        workspace_guard=prepared.workspace_guard,
        automation_prompt_upgrade=prepared.automation_prompt_upgrade,
        automation_prompt_upgrade_required=prepared.automation_prompt_upgrade_required,
        blocked_priority_fallback=prepared.blocked_priority_fallback,
    )
    external_evidence_observation = build_external_evidence_observation_obligation(
        item,
        state=state,
        agent_todo_summary=prepared.agent_todo_summary,
        work_lane_contract=prepared.work_lane_contract,
    )
    external_evidence_observation_recent = None
    if external_evidence_observation:
        external_evidence_observation_recent = _recent_external_monitor_observation_unchanged(
            prepared.status_payload,
            goal_id=prepared.safe_goal_id,
            agent_id=(
                normalize_todo_claimed_by(prepared.agent_identity.get("agent_id"))
                if isinstance(prepared.agent_identity, dict)
                else None
            ),
        )
        if external_evidence_observation_recent or (
            external_evidence_observation.get("poll_window_status") == "before_next_due"
        ):
            external_evidence_observation = None
    ready_deferred_resume_candidates: list[dict[str, Any]] = []
    if isinstance(prepared.agent_identity, dict) and isinstance(
        prepared.agent_todo_summary, dict
    ):
        ready_deferred_resume_candidates = _agent_scope_deferred_resume_candidates(
            prepared.agent_todo_summary,
            agent_id=normalize_todo_claimed_by(
                prepared.agent_identity.get("agent_id")
            ),
        )
    if (
        external_evidence_observation
        and not prepared.workspace_guard
        and not prepared.inbox_reply_due
    ):
        normal_delivery_allowed = False
        should_run = True
        heartbeat_recommendation = {
            **heartbeat_recommendation,
            "recommended_mode": "external_evidence_observe_or_blocker",
            "notify": "DONT_NOTIFY",
            "reason": (
                "waiting external evidence requires a read-only observation "
                "or compact blocker before quiet no-op"
            ),
            "spend_policy": external_evidence_observation.get("spend_policy")
            or heartbeat_recommendation.get("spend_policy"),
        }
        effective_action = "external_evidence_observe"
        reason = "external evidence monitor requires read-only observation before quiet no-op"
    monitor_quiet_skip = (
        not replan_decision_allowed
        and normal_delivery_allowed
        and not recovery_allowed
        and not self_repair_allowed
        and isinstance(prepared.work_lane_contract, dict)
        and prepared.work_lane_contract.get("obligation")
        == "quiet_until_material_monitor_transition"
        and prepared.work_lane_contract.get("must_attempt_work") is False
        and heartbeat_recommendation.get("recommended_mode")
        == "monitor_quiet_until_material_transition"
        and heartbeat_recommendation.get("notify") == "DONT_NOTIFY"
        and not ready_deferred_resume_candidates
    )
    if monitor_quiet_skip:
        normal_delivery_allowed = False
        should_run = False
        effective_action = "monitor_quiet_skip"
        reason = str(
            heartbeat_recommendation.get("reason")
            or "monitor-only polling has no material transition; skip delivery compute"
        )
    selected_recommended_action = selected_recommended_action_from_work_lane(
        item,
        agent_todo_summary=prepared.agent_todo_summary,
        work_lane_contract=prepared.work_lane_contract,
        agent_lane_recommendation=prepared.agent_lane_recommendation,
        prefer_agent_lane_recommendation=monitor_quiet_skip,
    )
    selected_recommended_action = refine_quota_recommended_action(
        selected_recommended_action,
        task_orchestration_contract=prepared.task_orchestration_contract,
        capability_gate=prepared.capability_gate,
        capability_monitor_fallback=prepared.capability_monitor_fallback,
        work_lane_contract=prepared.work_lane_contract,
        workspace_guard=prepared.workspace_guard,
        automation_prompt_upgrade=prepared.automation_prompt_upgrade,
        automation_prompt_upgrade_required=prepared.automation_prompt_upgrade_required,
        replan_obligation=prepared.replan_obligation,
        replan_decision_allowed=replan_decision_allowed,
    )
    due_monitor_attempt = work_lane_contract_is_due_monitor_attempt(
        prepared.work_lane_contract
    )
    agent_lane_next_action = None
    if (
        not due_monitor_attempt
        and not prepared.inbox_reply_due
        and not prepared.task_orchestration_contract
        and not prepared.capability_monitor_fallback
    ):
        agent_lane_next_action = build_agent_lane_next_action(
            agent_identity=prepared.agent_identity,
            agent_todo_summary=prepared.agent_todo_summary,
            capability_gate=prepared.capability_gate,
            scoped_user_gate_fallback=prepared.scoped_user_gate_fallback,
            active_next_action=(
                item.get("active_state_next_action")
                or (
                    item.get("project_asset", {}).get("next_action")
                    if isinstance(item.get("project_asset"), dict)
                    else None
                )
            ),
        )
    agent_scope_frontier = None
    agent_lane_frontier_hint = None
    if not replan_decision_allowed:
        selected_recommended_action = selected_action_with_agent_lane(
            selected_recommended_action,
            agent_lane_next_action=agent_lane_next_action,
        )
        agent_scope_frontier = _agent_scope_no_candidate_frontier(
            agent_identity=prepared.agent_identity,
            agent_todo_summary=prepared.agent_todo_summary,
            agent_lane_next_action=agent_lane_next_action,
            work_lane_contract=prepared.work_lane_contract,
            candidate_should_run=bool(
                (should_run and normal_delivery_allowed)
                or ready_deferred_resume_candidates
            ),
        )
        if (
            isinstance(agent_scope_frontier, dict)
            and agent_scope_frontier.get("priority_preemption") is True
        ):
            agent_lane_next_action = None
        agent_lane_frontier_hint = _agent_lane_frontier_hint(
            goal_id=prepared.safe_goal_id,
            agent_identity=prepared.agent_identity,
            agent_todo_summary=prepared.agent_todo_summary,
            agent_lane_next_action=agent_lane_next_action,
            agent_scope_frontier=agent_scope_frontier,
            work_lane_contract=prepared.work_lane_contract,
        )
        if agent_scope_frontier and agent_lane_frontier_hint:
            agent_scope_frontier["frontier_hint"] = agent_lane_frontier_hint
        if agent_scope_frontier:
            frontier_action = str(agent_scope_frontier.get("effective_action") or "")
            successor_replan_required = (
                frontier_action
                == AgentScopeFrontierAction.SUCCESSOR_REPLAN_REQUIRED.value
            )
            normal_delivery_allowed = False
            should_run = bool(successor_replan_required)
            effective_action = frontier_action
            reason = str(agent_scope_frontier.get("reason") or reason)
            selected_recommended_action = (
                agent_scope_frontier.get("recommended_action")
                or selected_recommended_action
            )
            heartbeat_recommendation = {
                **heartbeat_recommendation,
                "recommended_mode": effective_action,
                "notify": "DONT_NOTIFY",
                "reason": reason,
                "spend_policy": agent_scope_frontier.get("spend_policy")
                or "do not append quota spend while the current agent has no in-scope runnable candidate",
            }
    state_action_projection_warning = build_state_action_projection_warning(
        item,
        agent_todo_summary=prepared.agent_todo_summary,
        selected_action=selected_recommended_action,
        work_lane_contract=prepared.work_lane_contract,
    )
    active_state_next_action_text = _protocol_action_text(
        item.get("active_state_next_action")
        or prepared.project_asset.get("active_state_next_action")
        or prepared.project_asset.get("next_action"),
        limit=320,
    )
    latest_run_recommended_action_text = _protocol_action_text(
        item.get("latest_run_recommended_action")
        or prepared.project_asset.get("latest_run_recommended_action"),
        limit=320,
    )
    next_action_warning = next_action_projection_warning(
        active_state_next_action=active_state_next_action_text,
        latest_run_recommended_action=latest_run_recommended_action_text,
        agent_lane_next_action=agent_lane_next_action,
    )
    goal_route_hint = build_goal_route_hint(
        agent_identity=prepared.agent_identity,
        agent_todo_summary=prepared.agent_todo_summary,
        agent_lane_next_action=agent_lane_next_action,
        agent_scope_frontier=agent_scope_frontier,
        agent_lane_frontier_hint=agent_lane_frontier_hint,
        active_state_next_action=active_state_next_action_text,
        latest_run_recommended_action=latest_run_recommended_action_text,
        selected_recommended_action=selected_recommended_action,
    )
    goal_route_hint = task_goal_route_hint(
        goal_route_hint,
        prepared.task_orchestration_contract,
    )
    payload_work_lane_contract = _payload_work_lane_contract(
        prepared.work_lane_contract,
        effective_action=effective_action,
        recovery_allowed=recovery_allowed,
        agent_scope_frontier=agent_scope_frontier,
    )
    return _QuotaDecisionRoute(
        normal_delivery_allowed=normal_delivery_allowed,
        recovery_allowed=recovery_allowed,
        self_repair_allowed=self_repair_allowed,
        capability_repair_allowed=capability_repair_allowed,
        workspace_repair_allowed=workspace_repair_allowed,
        should_run=should_run,
        effective_action=effective_action,
        reason=reason,
        state=state,
        quota=quota,
        replan_decision_allowed=replan_decision_allowed,
        heartbeat_recommendation=heartbeat_recommendation,
        external_evidence_observation=external_evidence_observation,
        external_evidence_observation_recent=external_evidence_observation_recent,
        selected_recommended_action=selected_recommended_action,
        agent_lane_next_action=agent_lane_next_action,
        agent_scope_frontier=agent_scope_frontier,
        agent_lane_frontier_hint=agent_lane_frontier_hint,
        state_action_projection_warning=state_action_projection_warning,
        active_state_next_action_text=active_state_next_action_text,
        latest_run_recommended_action_text=latest_run_recommended_action_text,
        next_action_warning=next_action_warning,
        goal_route_hint=goal_route_hint,
        payload_work_lane_contract=payload_work_lane_contract,
    )


def _build_quota_should_run_payload(
    prepared: _QuotaDecisionPreparation,
    route: _QuotaDecisionRoute,
) -> dict[str, Any]:
    agent_scope_action = _agent_scope_frontier_action(route.effective_action)
    payload = {
        **_standing_decision_authority_payload_from_status_item(
            prepared.item,
            project_asset=prepared.project_asset,
            agent_id=normalize_todo_claimed_by(
                (prepared.agent_identity or {}).get("agent_id")
            ),
        ),
        "ok": (
            prepared.goal_health_ok
            or route.self_repair_allowed
            or route.capability_repair_allowed
            or route.workspace_repair_allowed
        ),
        "status_health_ok": prepared.goal_health_ok,
        "mode": "should-run",
        "goal_id": prepared.safe_goal_id,
        "decision": (
            AUTONOMOUS_REPLAN_REQUIRED_MODE
            if route.replan_decision_allowed
            else "run"
            if route.normal_delivery_allowed
            else "observe"
            if route.external_evidence_observation
            else "safe_bypass_recovery"
            if route.recovery_allowed
            else "self_repair"
            if route.self_repair_allowed
            else "repair_bridge"
            if route.capability_repair_allowed
            else "workspace_guard"
            if route.workspace_repair_allowed
            else "automation_prompt_upgrade"
            if prepared.automation_prompt_upgrade_required
            else agent_scope_action.value
            if agent_scope_action is not None
            else "skip"
        ),
        "should_run": route.should_run,
        "normal_delivery_allowed": route.normal_delivery_allowed,
        "recovery_delivery_allowed": route.recovery_allowed,
        "self_repair_allowed": route.self_repair_allowed,
        "capability_repair_allowed": route.capability_repair_allowed,
        "workspace_repair_allowed": route.workspace_repair_allowed,
        "effective_action": route.effective_action,
        "actionable_by_codex": bool(
            route.should_run
            or route.recovery_allowed
            or route.external_evidence_observation
            or route.capability_repair_allowed
            or route.workspace_repair_allowed
        ),
        "reason": (
            str(prepared.stall_self_repair.get("reason"))
            if route.self_repair_allowed
            and isinstance(prepared.stall_self_repair, dict)
            else route.reason
        ),
        "quota": route.quota,
        "state": route.state,
        "blocked_action_scope": (
            prepared.boundary_projection_repair.get("blocked_action_scope")
            if prepared.boundary_projection_repair
            else stall_repair_blocked_action_scope(prepared.stall_self_repair)
            or route.quota.get("blocked_action_scope")
        ),
        "safe_bypass_allowed": bool(route.quota.get("safe_bypass_allowed")),
        "safe_bypass_kind": route.quota.get("safe_bypass_kind"),
        "safe_bypass_policy": route.quota.get("safe_bypass_policy"),
        "waiting_on": prepared.item.get("waiting_on"),
        "status": prepared.item.get("status"),
        "lifecycle_phase": prepared.item.get("lifecycle_phase"),
        "lifecycle_flags": prepared.item.get("lifecycle_flags"),
        "source": prepared.item.get("source"),
        "project_asset_source": prepared.item.get("project_asset_source"),
        "recommended_action": route.selected_recommended_action,
        "active_state_next_action": route.active_state_next_action_text or None,
        "latest_run_recommended_action": (
            route.latest_run_recommended_action_text or None
        ),
        "execution_profile": (
            _quota_execution_profile_summary(
                prepared.project_asset.get("execution_profile")
            )
            if prepared.project_asset
            else None
        ),
        "long_task_cadence_hint": (
            prepared.item.get("long_task_cadence_hint")
            if isinstance(prepared.item.get("long_task_cadence_hint"), dict)
            else None
        ),
        "handoff_readiness": prepared.item.get("handoff_readiness"),
        "heartbeat_recommendation": route.heartbeat_recommendation,
        "execution_obligation": _execution_obligation(
            should_run=route.should_run,
            effective_action=route.effective_action,
            heartbeat_recommendation=route.heartbeat_recommendation,
            work_lane_contract=route.payload_work_lane_contract,
            external_evidence_observation=route.external_evidence_observation,
        ),
        "goal_boundary": prepared.goal_boundary,
        "goal_frontier_projection": prepared.goal_frontier_projection,
        "plan_summary": prepared.plan.get("summary"),
        "todo_write_hint": build_todo_write_hint(prepared.safe_goal_id),
    }
    payload = attach_task_orchestration_payload(
        payload,
        prepared.task_orchestration_contract,
    )
    for key in (
        "autonomous_replan_decision",
        "vision_continuation_audit",
        "vision_wait_state",
    ):
        if isinstance(value := prepared.goal_frontier_projection.get(key), dict):
            payload[key] = value
    if prepared.replan_scope.get("required"):
        payload["autonomous_replan_scope"] = prepared.replan_scope
    payload = _attach_agent_identity_contracts(
        payload=payload,
        agent_identity=prepared.agent_identity,
    )
    _attach_truthy_fields(
        payload,
        agent_lane_next_action=route.agent_lane_next_action,
    )
    selected_todo_projection = _selected_todo_projection(
        agent_lane_next_action=route.agent_lane_next_action,
        work_lane_contract=route.payload_work_lane_contract,
        agent_scope_frontier=route.agent_scope_frontier,
    )
    if selected_todo_projection:
        payload["selected_todo"] = selected_todo_projection
    _attach_truthy_fields(
        payload,
        agent_lane_frontier_hint=route.agent_lane_frontier_hint,
        goal_route_hint=route.goal_route_hint,
        agent_scope_frontier=route.agent_scope_frontier,
        workspace_guard=prepared.workspace_guard,
        automation_prompt_upgrade=prepared.automation_prompt_upgrade,
    )
    if prepared.agent_scoped_user_todo_override:
        payload[str(prepared.agent_scoped_user_todo_override["kind"])] = (
            prepared.agent_scoped_user_todo_override
        )
    _attach_truthy_fields(
        payload,
        work_lane_contract=route.payload_work_lane_contract,
        monitor_debt_arbitration=(
            prepared.monitor_debt_arbitration
            if prepared.monitor_debt_arbitration.get("active")
            else None
        ),
    )
    if prepared.capability_gate:
        payload["capability_gate"] = prepared.capability_gate
        if prepared.capability_gate.get("owner_missing"):
            payload["notify_user_on_capability_gate"] = True
    _attach_truthy_fields(
        payload,
        capability_monitor_fallback=prepared.capability_monitor_fallback,
        external_evidence_observation=route.external_evidence_observation,
        external_evidence_observation_recent=(
            route.external_evidence_observation_recent
        ),
    )
    control_plane = compact_control_plane_policy(prepared.item.get("control_plane"))
    if control_plane:
        payload["control_plane"] = control_plane
    if prepared.stall_self_repair:
        payload["stall_self_repair"] = prepared.stall_self_repair
        payload.update(stall_repair_payload(prepared.stall_self_repair))
    _attach_truthy_fields(
        payload,
        state_projection_gap=prepared.projection_gap,
        boundary_projection_gap=prepared.boundary_projection_repair,
        operator_question=prepared.item.get("operator_question"),
        missing_gates=prepared.item.get("missing_gates"),
    )
    if prepared.user_todo_summary:
        payload["user_todo_summary"] = compact_quota_todo_summary_for_payload(
            prepared.user_todo_summary
        )
        payload.update(
            _build_user_todo_notification(
                prepared.user_todo_summary,
                state=route.state,
                waiting_on=str(prepared.item.get("waiting_on") or ""),
                repeat_notification_required=(
                    route.heartbeat_recommendation.get(
                        "repeat_notification_required"
                    )
                    is True
                ),
                repeat_notification_reason=route.heartbeat_recommendation.get(
                    "reason"
                ),
            )
        )
    payload = _apply_scoped_user_gate_fallback_projection(
        payload,
        fallback=prepared.scoped_user_gate_fallback,
        replan_decision_allowed=route.replan_decision_allowed,
    )
    payload["requires_user_action"] = bool(
        route.state == "operator_gate"
        or payload.get("notify_user_on_gate") is True
        or payload.get("notify_user_on_open_todo") is True
        or payload.get("notify_user_on_capability_gate") is True
    )
    _attach_truthy_fields(
        payload,
        agent_todo_summary=(
            compact_quota_todo_summary_for_payload(prepared.agent_todo_summary)
            if prepared.agent_todo_summary
            else None
        ),
        blocked_priority_fallback=prepared.blocked_priority_fallback,
    )
    attention_queue = (
        prepared.status_payload.get("attention_queue")
        if isinstance(prepared.status_payload.get("attention_queue"), dict)
        else {}
    )
    _attach_truthy_fields(
        payload,
        autonomous_backlog_candidates=_compact_autonomous_candidate_context(
            attention_queue.get("autonomous_backlog_candidates"),
            goal_id=prepared.safe_goal_id,
        ),
        autonomous_monitor_candidates=_compact_autonomous_candidate_context(
            attention_queue.get("autonomous_monitor_candidates"),
            goal_id=prepared.safe_goal_id,
        ),
    )
    _attach_quota_supporting_projections(
        payload,
        status_payload=prepared.status_payload,
        item=prepared.item,
        project_asset=prepared.project_asset,
        goal_id=prepared.safe_goal_id,
        selected_recommended_action=route.selected_recommended_action,
        state=route.state,
        user_todo_summary=prepared.user_todo_summary,
        should_run=route.should_run,
        state_action_projection_warning=route.state_action_projection_warning,
        next_action_warning=route.next_action_warning,
        replan_obligation=prepared.replan_obligation,
    )
    _apply_agent_monitor_only_precedence(
        payload,
        monitor_only=prepared.agent_monitor_only,
        inbox_reply_due=prepared.inbox_reply_due,
    )
    required_reads = _quota_required_reads(payload)
    if required_reads:
        payload["required_reads"] = required_reads
        if isinstance(payload.get("autonomous_replan_obligation"), dict):
            payload["autonomous_replan_obligation"] = {
                **payload["autonomous_replan_obligation"],
                "required_reads": required_reads,
            }
    payload["automation_liveness"] = build_automation_liveness(payload)
    payload["interaction_contract"] = build_interaction_contract(
        payload,
        available_capabilities=prepared.runtime_available_capabilities,
        scheduler_execution_context=prepared.resolved_scheduler_context,
    )
    payload["scheduler_hint"] = _scheduler_hint(
        payload,
        include_detail=prepared.include_scheduler_detail,
        available_capabilities=prepared.runtime_available_capabilities,
        codex_app_scheduler_state=(
            _load_codex_app_scheduler_state(
                prepared.status_payload,
                goal_id=prepared.safe_goal_id,
                agent_id=quota_decision_agent_id(payload)
                or prepared.requested_agent_id,
            )
            if prepared.resolved_scheduler_context.ok
            and prepared.resolved_scheduler_context.context is not None
            and prepared.resolved_scheduler_context.context.codex_app_applicable
            else None
        ),
        codex_app_current_rrule=prepared.codex_app_current_rrule,
        scheduler_execution_context=prepared.resolved_scheduler_context,
    )
    finalize_user_gate_notification_cooldown(
        payload,
        available_capabilities=prepared.runtime_available_capabilities,
        scheduler_execution_context=prepared.resolved_scheduler_context,
    )
    payload["protocol_action_packet"] = build_protocol_action_packet(payload)
    return payload


def _quota_required_reads(decision: dict[str, Any]) -> list[dict[str, Any]]:
    effective_action = str(decision.get("effective_action") or "")
    replan_required = effective_action in {
        AUTONOMOUS_REPLAN_REQUIRED_MODE,
        AgentScopeFrontierAction.SUCCESSOR_REPLAN_REQUIRED.value,
    } or isinstance(decision.get("autonomous_replan_obligation"), dict)
    if not replan_required:
        return []
    read = build_agent_scoped_required_read(
        goal_id=str(decision.get("goal_id") or ""),
        agent_id=quota_decision_agent_id(decision),
        reason=(
            "read recent public-safe evidence across this agent lane before "
            "replan; if local evidence is thin, use bounded public-safe search"
        ),
    )
    return [read] if read else []
