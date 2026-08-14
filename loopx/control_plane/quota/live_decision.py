from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ...quota import build_quota_should_run
from ...rollout_event_log import rollout_event_log_path
from ..new_architecture import master_switch_enabled
from ..policy import PolicyEngine
from ..policy.decision_events import record_policy_decision
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
    resolve_scheduler_execution_context,
)


HostObservationResolver = Callable[..., Mapping[str, Any]]


class PolicyIntegrationError(RuntimeError):
    """Raised when the unified ``PolicyEngine`` decision diverges from the
    live quota path during the opt-in pilot wiring (RFC §12 Phase 5)."""


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def bind_scheduler_followup_cli_routes(
    payload: dict[str, Any],
    *,
    registry_path: Path,
    runtime_root: Path,
    source: str = "quota_cli_invocation",
) -> None:
    """Bind scheduler follow-ups to the registry/runtime that built the hint."""

    scheduler_hint = payload.get("scheduler_hint")
    if not isinstance(scheduler_hint, dict):
        return
    codex_app = scheduler_hint.get("codex_app")
    if not isinstance(codex_app, dict):
        return
    for hint_name in ("ack_hint", "failure_hint"):
        followup_hint = codex_app.get(hint_name)
        if not isinstance(followup_hint, dict):
            continue
        cli_args = followup_hint.get("cli_args")
        if not isinstance(cli_args, list) or not cli_args or cli_args[0] == "--registry":
            continue
        followup_hint["cli_args"] = [
            "--registry",
            str(registry_path.expanduser().resolve()),
            "--runtime-root",
            str(runtime_root.expanduser().resolve()),
            *cli_args,
        ]
        followup_hint["route_binding"] = {
            "schema_version": (
                "scheduler_ack_cli_route_v0"
                if hint_name == "ack_hint"
                else "scheduler_failure_cli_route_v0"
            ),
            "source": source,
            "registry_bound": True,
            "runtime_root_bound": True,
        }


def build_live_quota_should_run_decision(
    status_payload: dict[str, Any],
    *,
    goal_id: str,
    agent_id: str | None,
    available_capabilities: list[str] | None,
    include_scheduler_detail: bool,
    codex_app_current_rrule: str | None,
    registry_path: Path,
    runtime_root: Path,
    host_observation_resolver: HostObservationResolver | None = None,
    route_source: str = "quota_cli_invocation",
    scheduler_execution_context: Mapping[str, Any] | SchedulerExecutionContextResolution | None = None,
    operator_inbox_urgency_projector: Callable[..., dict[str, Any]] | None = None,
    use_policy_engine: bool | None = None,
    record_policy_decisions: bool | None = None,
) -> dict[str, Any]:
    """Build one live CLI decision while keeping host observation injectable.

    RFC §12 Phase 5 pilot wiring: when ``use_policy_engine`` is enabled (or the
    ``LOOPX_USE_POLICY_ENGINE`` env flag is set), the decision is additionally
    computed through the unified :class:`PolicyEngine`; the unified decision is
    verified for consistency with the legacy quota payload and attached under
    the ``policy_decision`` key. Optional decision audit events are recorded
    when ``record_policy_decisions`` (or ``LOOPX_POLICY_DECISION_RECORD``) is on.
    """

    resolved_context = resolve_scheduler_execution_context(scheduler_execution_context)
    codex_app_applicable = (
        resolved_context.ok
        and resolved_context.context is not None
        and resolved_context.context.codex_app_applicable
    )
    observed_rrule = str(codex_app_current_rrule or "").strip()
    if (
        codex_app_applicable
        and not observed_rrule
        and host_observation_resolver is not None
    ):
        observation = host_observation_resolver(goal_id=goal_id, agent_id=agent_id)
        if observation.get("available") is True:
            observed_rrule = str(observation.get("rrule") or "")
    payload = build_quota_should_run(
        status_payload,
        goal_id=goal_id,
        agent_id=agent_id,
        available_capabilities=available_capabilities,
        include_scheduler_detail=include_scheduler_detail,
        codex_app_current_rrule=observed_rrule,
        scheduler_execution_context=resolved_context,
        operator_inbox_urgency_projector=operator_inbox_urgency_projector,
    )
    bind_scheduler_followup_cli_routes(
        payload,
        registry_path=registry_path,
        runtime_root=runtime_root,
        source=route_source,
    )
    if use_policy_engine is None:
        use_policy_engine = _env_flag("LOOPX_USE_POLICY_ENGINE", default=master_switch_enabled())
    if record_policy_decisions is None:
        record_policy_decisions = _env_flag(
            "LOOPX_POLICY_DECISION_RECORD", default=master_switch_enabled()
        )
    if use_policy_engine:
        _attach_unified_policy_decision(
            payload,
            status_payload=status_payload,
            goal_id=goal_id,
            agent_id=agent_id,
            available_capabilities=available_capabilities,
            include_scheduler_detail=include_scheduler_detail,
            observed_rrule=observed_rrule,
            resolved_context=resolved_context,
            operator_inbox_urgency_projector=operator_inbox_urgency_projector,
            runtime_root=runtime_root,
            record_policy_decisions=record_policy_decisions,
        )
    return payload


def _attach_unified_policy_decision(
    payload: dict[str, Any],
    *,
    status_payload: dict[str, Any],
    goal_id: str,
    agent_id: str | None,
    available_capabilities: list[str] | None,
    include_scheduler_detail: bool,
    observed_rrule: str,
    resolved_context: SchedulerExecutionContextResolution,
    operator_inbox_urgency_projector: Callable[..., dict[str, Any]] | None,
    runtime_root: Path,
    record_policy_decisions: bool,
) -> None:
    """RFC §12 Phase 5 pilot wiring: compute the unified decision via
    :class:`PolicyEngine`, verify it matches the legacy quota payload, attach it
    as ``payload["policy_decision"]``, and optionally record an audit event."""
    unified = PolicyEngine().decide_live(
        status_payload=status_payload,
        goal_id=goal_id,
        agent_id=agent_id,
        available_capabilities=available_capabilities,
        include_scheduler_detail=include_scheduler_detail,
        codex_app_current_rrule=observed_rrule or None,
        scheduler_execution_context=resolved_context,
        operator_inbox_urgency_projector=operator_inbox_urgency_projector,
    )
    _verify_policy_decision_consistency(payload, unified)
    payload["policy_decision"] = unified.to_dict()
    if record_policy_decisions:
        record_policy_decision(
            unified,
            goal_id=goal_id,
            agent_id=agent_id,
            log_path=rollout_event_log_path(runtime_root, goal_id),
            state_dir=runtime_root / "goals" / str(goal_id) / "policy-decision-state",
            transition_only=True,
        )


def _verify_policy_decision_consistency(
    payload: dict[str, Any],
    unified: Any,
) -> None:
    """Verify the unified decision agrees with the legacy quota payload.

    The legacy ``should_run`` flag and the normalized ``outcome`` answer
    *different questions* and therefore legitimately diverge in one direction:

    * ``should_run=True`` means "some compute must execute now" — including the
      *repair* lanes (``repair_bridge`` / ``workspace_guard`` / ``self_repair``
      set ``capability_repair_allowed`` / ``workspace_repair_allowed``, which
      fold into ``should_run`` in ``decision_summary.resolve_quota_run_decision``).
    * ``outcome="wait"`` means "this is not a *normal* run delivery" — a repair
      bridge is intentionally normalized to ``wait`` (``DECISION_MAP``), because
      the agent must first close the capability/workspace gap.

    So ``should_run=True`` with ``outcome="wait"`` is the *intended* repair
    semantic, NOT a divergence. Two cases remain genuine bugs:

    * **permissive drift** (any source): ``outcome="run"`` while the quota says
      ``should_run=False`` — PolicyEngine authorized normal delivery the quota
      layer refused.
    * **single-layer deny** (``source == "quota"``): ``outcome="deny"`` while the
      quota says ``should_run=True`` — PolicyEngine consumed the same quota layer
      yet produced a stricter deny, which cannot happen for the *same* input and
      indicates a real mismatch. (A composed ``deny`` from a stricter outer layer
      is still valid, as ``test_stricter_composed_deny_over_quota_run_is_accepted``
      asserts.)
    """
    should_run = payload.get("should_run") is True
    ok = True
    if unified.outcome == "run" and not should_run:
        ok = False  # permissive drift
    elif unified.source == "quota" and unified.outcome == "deny" and should_run:
        ok = False  # single-layer deny over a running quota
    if not ok:
        raise PolicyIntegrationError(
            "PolicyEngine decision diverged from live quota payload: "
            f"outcome={unified.outcome!r} source={unified.source!r} "
            f"should_run={should_run!r} payload_decision={payload.get('decision')!r}"
        )
