"""Policy Engine: composes existing decision modules into a unified Decision.

RFC C1 (Unified Policy Decision Contract) + §7.3 Implementation Rule:

* ``PolicyEngine`` must not duplicate existing domain rules;
* it composes existing pure functions (quota, capability, scope,
  execution-context validation);
* it owns composition and normalization, not the underlying business rules;
* it remains free of persistence side effects (decision recording is an
  opt-in concern handled by the caller / ``policy/decision_events.py``).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..agents.capability_gate import build_capability_gate
from ..quota.should_run import build_quota_should_run
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
    resolve_scheduler_execution_context,
)
from .decision import (
    Decision,
    combine_decisions,
    normalize_capability_action,
    normalize_quota_decision,
    normalize_scheduler_resolution,
)


class PolicyEngine:
    """Unified decision facade over quota / capability / scope / scheduler."""

    def __init__(self) -> None:
        self._supports_capability_gate = True

    def decide_live(
        self,
        *,
        status_payload: dict[str, Any],
        goal_id: str,
        agent_id: str | None,
        available_capabilities: list[str] | None,
        include_scheduler_detail: bool,
        codex_app_current_rrule: str | None,
        registry_path: Any = None,
        runtime_root: Any = None,
        host_observation_resolver: Callable[..., Mapping[str, Any]] | None = None,
        scheduler_execution_context: (
            Mapping[str, Any] | SchedulerExecutionContextResolution | None
        ) = None,
        operator_inbox_urgency_projector: Callable[..., dict[str, Any]] | None = None,
        capability_agent_todo_summary: dict[str, Any] | None = None,
        capability_agent_identity: dict[str, Any] | None = None,
    ) -> Decision:
        """Phase 5 integration adapter (opt-in; does not change existing paths).

        Mirrors ``quota/live_decision.build_live_quota_should_run_decision``
        signature so a live caller can switch to the unified contract without
        restructuring its inputs. Returns the normalized ``Decision``.
        """
        return self.decide(
            status_payload=status_payload,
            goal_id=goal_id,
            agent_id=agent_id,
            available_capabilities=available_capabilities,
            include_scheduler_detail=include_scheduler_detail,
            codex_app_current_rrule=codex_app_current_rrule,
            scheduler_execution_context=scheduler_execution_context,
            operator_inbox_urgency_projector=operator_inbox_urgency_projector,
            capability_agent_todo_summary=capability_agent_todo_summary,
            capability_agent_identity=capability_agent_identity,
        )

    def decide(
        self,
        *,
        status_payload: dict[str, Any],
        goal_id: str,
        agent_id: str | None = None,
        available_capabilities: Any = None,
        scheduler_execution_context: (
            Mapping[str, Any] | SchedulerExecutionContextResolution | None
        ) = None,
        codex_app_current_rrule: Any = None,
        operator_inbox_urgency_projector: Callable[..., dict[str, Any]] | None = None,
        include_scheduler_detail: bool = False,
        capability_agent_todo_summary: dict[str, Any] | None = None,
        capability_agent_identity: dict[str, Any] | None = None,
    ) -> Decision:
        """Return the unified decision for a single Goal / Task evaluation.

        Composition order (most restrictive wins on tie):

        1. scheduler execution-context validation;
        2. quota should_run (already embeds agent-scope frontier semantics);
        3. optional capability gate when ``capability_agent_todo_summary``
           is supplied.
        """
        scheduler_resolution = resolve_scheduler_execution_context(
            scheduler_execution_context
        )
        scheduler_decision = normalize_scheduler_resolution(scheduler_resolution)
        if not scheduler_resolution.ok:
            return scheduler_decision

        quota_payload = build_quota_should_run(
            status_payload,
            goal_id=goal_id,
            agent_id=agent_id,
            available_capabilities=available_capabilities,
            include_scheduler_detail=include_scheduler_detail,
            codex_app_current_rrule=codex_app_current_rrule,
            scheduler_execution_context=scheduler_resolution,
            operator_inbox_urgency_projector=operator_inbox_urgency_projector,
        )
        quota_decision = normalize_quota_decision(
            quota_payload.get("decision"),
            extra_detail={
                "effective_action": quota_payload.get("effective_action"),
                "state": quota_payload.get("state"),
                "should_run": quota_payload.get("should_run"),
            },
        )
        decision = quota_decision

        if capability_agent_todo_summary is not None:
            capability_gate = build_capability_gate(
                capability_agent_todo_summary,
                available_capabilities=list(available_capabilities or []),
                agent_identity=capability_agent_identity,
            )
            if capability_gate is not None:
                capability_decision = normalize_capability_action(
                    capability_gate.get("action"),
                    extra_detail={"gate": capability_gate.get("gate")},
                )
                decision = combine_decisions(decision, capability_decision)

        return decision


# Shared engine instance for stateless callers.
policy_engine = PolicyEngine()


def decide(
    *,
    status_payload: dict[str, Any],
    goal_id: str,
    **kwargs: Any,
) -> Decision:
    """Module-level convenience for ``PolicyEngine.decide``."""
    return policy_engine.decide(status_payload=status_payload, goal_id=goal_id, **kwargs)
