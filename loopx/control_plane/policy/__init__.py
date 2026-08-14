"""Unified policy decision layer for the LoopX control plane.

RFC: Event-Driven Control Plane and Unified Policy Decision Architecture.

This package is a facade over the existing decision modules
(``quota/should_run``, ``agents/capability_gate``, ``agents/agent_scope``,
``scheduler/execution_context``). It composes and normalizes their results
into a single stable ``Decision`` contract without reimplementing any domain
rules and without touching existing execution paths.
"""

from __future__ import annotations

from .decision import (
    CAPABILITY_ACTION_MAP,
    DECISION_MAP,
    Decision,
    DecisionOutcome,
    combine_decisions,
    normalize_capability_action,
    normalize_quota_decision,
    normalize_scheduler_resolution,
)
from .decision_events import (
    POLICY_DECISION_EVENT_KIND,
    PolicyDecisionRecorder,
    compute_decision_fingerprint,
    policy_decision_events,
    record_policy_decision,
)
from .engine import PolicyEngine, decide, policy_engine

__all__ = [
    "CAPABILITY_ACTION_MAP",
    "DECISION_MAP",
    "POLICY_DECISION_EVENT_KIND",
    "PolicyDecisionRecorder",
    "PolicyEngine",
    "combine_decisions",
    "compute_decision_fingerprint",
    "decide",
    "normalize_capability_action",
    "normalize_quota_decision",
    "normalize_scheduler_resolution",
    "policy_decision_events",
    "policy_engine",
    "record_policy_decision",
]
