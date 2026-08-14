"""Normalized policy decision contract.

RFC C1 (Unified Policy Decision Contract): the three outcomes are normalized
control semantics; the reason/source fields preserve domain-specific
information. This avoids collapsing ``backoff``, ``recovery``,
``repair_bridge``, and ``ask_owner`` into indistinguishable states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..scheduler.execution_context import SchedulerExecutionContextResolution

DecisionOutcome = Literal["run", "wait", "deny"]

# Rich action vocabulary (``plan/new_plan.md`` §5, P1): PolicyEngine returns an
# actionable verb rather than a bare should-run boolean. Each action is backed
# by a normalized outcome so existing consumers keep working unchanged.
DecisionAction = Literal[
    "ALLOW", "DENY", "DEFER", "RETRY", "BLOCK", "CANCEL", "ESCALATE",
]

# action -> (normalized outcome, default reason suffix)
DECISION_ACTION_MAP: dict[str, tuple[DecisionOutcome, str]] = {
    "ALLOW": ("run", "allow"),
    "DENY": ("deny", "deny"),
    "DEFER": ("wait", "defer"),
    "RETRY": ("wait", "retry"),
    "BLOCK": ("wait", "block"),
    "CANCEL": ("deny", "cancel"),
    "ESCALATE": ("wait", "escalate"),
}


def default_action_for_outcome(outcome: DecisionOutcome) -> DecisionAction:
    """Map a normalized outcome to a canonical rich action (backward default)."""
    if outcome == "run":
        return "ALLOW"
    if outcome == "deny":
        return "DENY"
    return "DEFER"


@dataclass(frozen=True)
class Decision:
    """Normalized control decision.

    ``outcome`` is one of three normalized control semantics:

    * ``run``  — the Task may execute now;
    * ``wait`` — the Task may execute later (backoff, recovery, repair, gate);
    * ``deny`` — the Task must not execute.

    ``reason`` preserves the domain-specific explanation, while ``source``
    records which policy layer produced the decision (``quota``, ``capability``,
    ``scope``, or ``scheduler``). ``detail`` may carry additional structured
    context. ``retry_*`` fields carry optional explicit retry metadata.

    ``action`` is the richer actionable verb from the
    ``ALLOW / DENY / DEFER / RETRY / BLOCK / CANCEL / ESCALATE`` vocabulary
    (``plan/new_plan.md`` §5). When omitted it is derived from ``outcome`` so
    the rich vocabulary is fully backward compatible. Optional scheduler-facing
    hints (``max_attempts``, ``priority``, ``required_capability``,
    ``resource_class``) let the policy layer steer the Task Queue.
    """

    outcome: DecisionOutcome
    reason: str
    source: str
    detail: dict[str, Any] = field(default_factory=dict)
    retry_at: str | None = None
    retry_after_seconds: int | None = None
    manual_approval_required: bool = False
    action: str | None = None
    max_attempts: int | None = None
    priority: int | None = None
    required_capability: str | None = None
    resource_class: str | None = None

    @property
    def rich_action(self) -> str:
        """Return the rich action (derived from outcome when not set)."""
        if self.action:
            return self.action
        return default_action_for_outcome(self.outcome)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "outcome": self.outcome,
            "reason": self.reason,
            "source": self.source,
        }
        # Only serialize an explicit action so round-tripping a legacy Decision
        # (action=None) stays lossless; derived actions are available via
        # ``rich_action`` for new consumers.
        if self.action:
            payload["action"] = self.action
        if self.detail:
            payload["detail"] = dict(self.detail)
        if self.max_attempts is not None:
            payload["max_attempts"] = self.max_attempts
        if self.priority is not None:
            payload["priority"] = self.priority
        if self.required_capability:
            payload["required_capability"] = self.required_capability
        if self.resource_class:
            payload["resource_class"] = self.resource_class
        if self.retry_at:
            payload["retry_at"] = self.retry_at
        if self.retry_after_seconds is not None:
            payload["retry_after_seconds"] = self.retry_after_seconds
        if self.manual_approval_required:
            payload["manual_approval_required"] = True
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "Decision":
        if isinstance(value, cls):
            return value
        payload = value if isinstance(value, dict) else {}
        raw_outcome = str(payload.get("outcome") or "deny")
        outcome: DecisionOutcome
        if raw_outcome in {"run", "wait", "deny"}:
            outcome = raw_outcome  # type: ignore[assignment]
        else:
            outcome = "deny"
        return cls(
            outcome=outcome,
            reason=str(payload.get("reason") or "unknown"),
            source=str(payload.get("source") or "unknown"),
            detail=dict(payload.get("detail") or {}),
            retry_at=payload.get("retry_at"),
            retry_after_seconds=payload.get("retry_after_seconds"),
            manual_approval_required=payload.get("manual_approval_required") is True,
            action=str(payload.get("action") or "") or None,
            max_attempts=payload.get("max_attempts"),
            priority=payload.get("priority"),
            required_capability=str(payload.get("required_capability") or "") or None,
            resource_class=str(payload.get("resource_class") or "") or None,
        )

    def __bool__(self) -> bool:
        return self.outcome == "run"


# ---------------------------------------------------------------------------
# Quota decision normalization
#
# ``quota/should_run.py`` exposes a ``decision`` field with values such as:
#   run | observe | safe_bypass_recovery | self_repair | repair_bridge
#   | workspace_guard | automation_prompt_upgrade | skip
#   | agent_scope_exhausted | agent_scope_wait | reassignment_required
#   | successor_replan_required | autonomous_replan_required
#
# RFC requires an exhaustive, testable mapping from every existing decision
# value to the normalized (outcome, reason) contract.
# ---------------------------------------------------------------------------

DECISION_MAP: dict[str, tuple[DecisionOutcome, str]] = {
    "run": ("run", "normal_delivery"),
    "observe": ("run", "external_evidence_observe"),
    "safe_bypass_recovery": ("run", "safe_bypass_recovery"),
    "recovery": ("run", "recovery"),
    "self_repair": ("run", "self_repair"),
    "repair_bridge": ("wait", "capability_repair_bridge"),
    "workspace_guard": ("wait", "workspace_guard"),
    "automation_prompt_upgrade": ("wait", "automation_prompt_upgrade"),
    "autonomous_replan_required": ("run", "autonomous_replan_required"),
    "agent_scope_exhausted": ("wait", "agent_scope_exhausted"),
    "agent_scope_wait": ("wait", "agent_scope_wait"),
    "reassignment_required": ("wait", "reassignment_required"),
    "successor_replan_required": ("wait", "successor_replan_required"),
    "skip": ("deny", "skip"),
}

# ---------------------------------------------------------------------------
# Capability gate normalization
#
# ``agents/capability_gate.py`` exposes an ``action`` field with values:
#   run | repair_bridge | ask_owner | skip | denied
# ---------------------------------------------------------------------------

CAPABILITY_ACTION_MAP: dict[str, tuple[DecisionOutcome, str]] = {
    "run": ("run", "capability_ok"),
    "repair_bridge": ("wait", "capability_repair_bridge"),
    "ask_owner": ("wait", "ask_owner"),
    "deny": ("deny", "capability_denied"),
    "denied": ("deny", "capability_denied"),
    "skip": ("deny", "capability_skip"),
}

# Strictness ordering for combining decisions: deny > wait > run.
_OUTCOME_RANK: dict[DecisionOutcome, int] = {"run": 0, "wait": 1, "deny": 2}


def _rank(outcome: DecisionOutcome) -> int:
    return _OUTCOME_RANK.get(outcome, 1)


def combine_decisions(primary: Decision, secondary: Decision) -> Decision:
    """Combine two decisions, keeping the most restrictive outcome.

    When outcomes tie, the primary decision wins so callers can control
    precedence (for example, quota before capability).
    """
    if _rank(secondary.outcome) > _rank(primary.outcome):
        return secondary
    return primary


def normalize_quota_decision(decision_value: Any, *, extra_detail: dict[str, Any] | None = None) -> Decision:
    """Normalize a ``quota/should_run`` decision value into a ``Decision``."""
    value = str(decision_value or "").strip()
    if not value:
        value = "skip"
    outcome, reason = DECISION_MAP.get(value, ("deny", f"unknown_quota_decision:{value}"))
    detail: dict[str, Any] = {"quota_decision": value}
    if extra_detail:
        detail.update(extra_detail)
    return Decision(outcome=outcome, reason=reason, source="quota", detail=detail)


def normalize_capability_action(action_value: Any, *, extra_detail: dict[str, Any] | None = None) -> Decision:
    """Normalize a capability gate ``action`` value into a ``Decision``."""
    value = str(action_value or "").strip()
    if not value:
        value = "skip"
    outcome, reason = CAPABILITY_ACTION_MAP.get(value, ("deny", f"unknown_capability_action:{value}"))
    detail: dict[str, Any] = {"capability_action": value}
    if extra_detail:
        detail.update(extra_detail)
    return Decision(outcome=outcome, reason=reason, source="capability", detail=detail)


def normalize_scheduler_resolution(
    resolution: SchedulerExecutionContextResolution,
    *,
    extra_detail: dict[str, Any] | None = None,
) -> Decision:
    """Normalize a scheduler execution-context resolution into a ``Decision``."""
    if resolution.ok:
        return Decision(outcome="run", reason="scheduler_context_ok", source="scheduler")
    detail: dict[str, Any] = {"errors": list(resolution.errors)}
    if extra_detail:
        detail.update(extra_detail)
    return Decision(
        outcome="deny",
        reason="invalid_scheduler_execution_context",
        source="scheduler",
        detail=detail,
    )
