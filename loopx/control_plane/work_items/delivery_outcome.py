from __future__ import annotations

from enum import Enum
from typing import Any


class DeliveryOutcome(str, Enum):
    """Structured machine signal for what a delivery run actually advanced."""

    SURFACE_ONLY = "surface_only"
    OUTCOME_GAP = "outcome_gap"
    OUTCOME_PROGRESS = "outcome_progress"
    PRIMARY_GOAL_OUTCOME = "primary_goal_outcome"


class DeliveryTurnKind(str, Enum):
    """Compact public-safe classification for why a delivery turn counts."""

    CONTRACT_ONLY_PREPARATION = "contract_only_preparation"
    COMPACT_EVIDENCE = "compact_evidence"
    BLOCKER_WRITEBACK = "blocker_writeback"
    PRODUCT_PATH_EXECUTION = "product_path_execution"
    OUTCOME_GAP = "outcome_gap"
    UNKNOWN = "unknown"


DELIVERY_OUTCOME_CHOICES = tuple(outcome.value for outcome in DeliveryOutcome)
DELIVERY_TURN_KIND_CHOICES = tuple(kind.value for kind in DeliveryTurnKind)
DELIVERY_OUTCOME_UNKNOWN = "unknown"
DELIVERY_OUTCOME_NOT_CONFIGURED = "not_configured"

ACCOUNTABLE_DELIVERY_OUTCOMES = frozenset(
    {
        DeliveryOutcome.OUTCOME_PROGRESS,
        DeliveryOutcome.PRIMARY_GOAL_OUTCOME,
    }
)
FOLLOWTHROUGH_REQUIRED_DELIVERY_OUTCOMES = frozenset(
    {
        DeliveryOutcome.SURFACE_ONLY,
        DeliveryOutcome.OUTCOME_GAP,
    }
)
PROGRESS_DELIVERY_OUTCOMES = ACCOUNTABLE_DELIVERY_OUTCOMES

DELIVERY_SURFACE_ACTION_KIND_HINTS = (
    "planning",
    "planner",
    "plan_",
    "_plan",
    "brief",
    "dispatch",
    "binding",
    "checkpoint",
    "preparation",
    "prepare",
    "setup",
    "onboarding",
    "governance",
    "policy",
    "protocol",
    "projection",
    "state_refresh",
    "status_refresh",
    "writeback",
    "handoff",
    "registry_sync",
)
DELIVERY_SURFACE_CLASSIFICATION_HINTS = (
    "contract",
    "planning",
    "planner",
    "brief",
    "dispatch",
    "binding",
    "checkpoint",
    "preparation",
    "setup",
    "onboarding",
    "governance",
    "policy",
    "protocol",
    "state_refreshed",
    "state_refresh",
    "status_refresh",
    "writeback",
    "handoff",
)
DELIVERY_MATERIAL_EVIDENCE_KEYS = (
    "benchmark_run_summary",
    "benchmark_result_summary",
    "benchmark_comparison_summary",
    "benchmark_learning_ledger_summary",
    "benchmark_experiment_report_summary",
    "active_user_assisted_pilot_summary",
    "benchmark_run",
    "benchmark_result",
    "benchmark_comparison",
    "benchmark_learning_ledger",
    "benchmark_experiment_report",
    "case_result",
    "compact_evidence",
    "product_evidence",
    "validation_evidence",
)


def normalize_delivery_outcome(value: Any) -> DeliveryOutcome | None:
    if isinstance(value, DeliveryOutcome):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return DeliveryOutcome(text)
    except ValueError:
        return None


def require_delivery_outcome(value: Any) -> DeliveryOutcome:
    outcome = normalize_delivery_outcome(value)
    if outcome is None:
        raise ValueError("delivery_outcome must be one of: " + ", ".join(DELIVERY_OUTCOME_CHOICES))
    return outcome


def delivery_outcome_value(value: Any) -> str | None:
    outcome = normalize_delivery_outcome(value)
    return outcome.value if outcome else None


def delivery_action_kind_is_surface_only(value: Any) -> bool:
    """Return whether a typed Todo names control-plane preparation only.

    Action kinds remain project-defined.  The built-in denylist is therefore
    deliberately limited to unambiguous planning/orchestration terms; unknown
    advancement kinds remain eligible for project delivery.
    """

    action_kind = str(value or "").strip().lower()
    return bool(
        action_kind
        and any(hint in action_kind for hint in DELIVERY_SURFACE_ACTION_KIND_HINTS)
    )


def delivery_run_is_surface_only(run: dict[str, Any]) -> bool:
    turn_kind = normalize_delivery_turn_kind(run.get("delivery_turn_kind"))
    if turn_kind == DeliveryTurnKind.CONTRACT_ONLY_PREPARATION:
        return True
    if delivery_action_kind_is_surface_only(
        run.get("todo_action_kind") or run.get("action_kind")
    ):
        return True
    classification = str(run.get("classification") or "").strip().lower()
    return bool(
        classification
        and any(
            hint in classification
            for hint in DELIVERY_SURFACE_CLASSIFICATION_HINTS
        )
    )


def delivery_run_has_material_evidence(run: dict[str, Any]) -> bool:
    if delivery_run_is_surface_only(run):
        return False
    task_class = str(
        run.get("todo_task_class") or run.get("task_class") or ""
    ).strip()
    action_kind = str(
        run.get("todo_action_kind") or run.get("action_kind") or ""
    ).strip()
    if task_class == "advancement_task" and action_kind:
        return True
    if str(run.get("delivery_batch_scale") or "").strip() in {
        "implementation",
        "multi_surface",
        "test_only",
    }:
        return True
    return any(run.get(key) for key in DELIVERY_MATERIAL_EVIDENCE_KEYS)


def evidence_bounded_delivery_outcome(
    run: dict[str, Any],
    claimed_outcome: Any,
) -> DeliveryOutcome | None:
    """Bound a caller claim to typed Todo or compact evidence already present.

    This is intentionally a semantic read model, not an artifact replay gate.
    It prevents a caller-controlled enum from turning planning or ambiguous
    bookkeeping into accountable outcome progress.
    """

    claimed = normalize_delivery_outcome(claimed_outcome)
    if claimed is None:
        return None
    if claimed in {
        DeliveryOutcome.SURFACE_ONLY,
        DeliveryOutcome.OUTCOME_GAP,
    }:
        return claimed
    if delivery_run_is_surface_only(run):
        return DeliveryOutcome.SURFACE_ONLY
    if delivery_run_has_material_evidence(run):
        return claimed
    return DeliveryOutcome.OUTCOME_GAP


def selected_todo_delivery_fields(
    parsed_state_todos: dict[str, Any],
    *,
    todo_id: Any,
) -> dict[str, Any]:
    """Project the delivery fields for one exact parsed active-state Todo."""

    selected_id = str(todo_id or "").strip()
    if not selected_id:
        return {}
    for summary_key in ("agent_todos", "user_todos"):
        summary = parsed_state_todos.get(summary_key)
        if not isinstance(summary, dict):
            continue
        for item_key in ("items", "recent_completed_advancement_items"):
            items = summary.get(item_key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("todo_id") or "").strip() != selected_id:
                    continue
                return {
                    target: item.get(source)
                    for target, source in (
                        ("todo_id", "todo_id"),
                        ("todo_task_class", "task_class"),
                        ("todo_action_kind", "action_kind"),
                        ("todo_status", "status"),
                    )
                    if item.get(source) is not None
                }
    return {"todo_id": selected_id}


def normalize_delivery_turn_kind(value: Any) -> DeliveryTurnKind | None:
    if isinstance(value, DeliveryTurnKind):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return DeliveryTurnKind(text)
    except ValueError:
        return None


def require_delivery_turn_kind(value: Any) -> DeliveryTurnKind:
    kind = normalize_delivery_turn_kind(value)
    if kind is None:
        raise ValueError("delivery_turn_kind must be one of: " + ", ".join(DELIVERY_TURN_KIND_CHOICES))
    return kind


def delivery_turn_kind_for_run(
    run: dict[str, Any],
    *,
    delivery_outcome: Any = None,
) -> str:
    """Classify the latest turn without relying on free-form classification text alone."""

    raw_explicit = str(run.get("delivery_turn_kind") or "").strip()
    if raw_explicit:
        explicit = normalize_delivery_turn_kind(raw_explicit)
        return explicit.value if explicit else DeliveryTurnKind.UNKNOWN.value

    claimed_outcome = normalize_delivery_outcome(
        delivery_outcome if delivery_outcome is not None else run.get("delivery_outcome")
    )
    outcome = evidence_bounded_delivery_outcome(run, claimed_outcome)
    classification = str(run.get("classification") or "").strip().lower()
    health_check = str(run.get("health_check") or "").strip().lower()
    recommended_action = str(run.get("recommended_action") or "").strip().lower()
    searchable = " ".join(part for part in (classification, health_check, recommended_action) if part)

    if (
        outcome == DeliveryOutcome.PRIMARY_GOAL_OUTCOME
        and delivery_run_has_material_evidence(run)
    ):
        return DeliveryTurnKind.PRODUCT_PATH_EXECUTION.value

    if (
        outcome == DeliveryOutcome.OUTCOME_PROGRESS
        and delivery_run_has_material_evidence(run)
    ):
        if str(run.get("todo_task_class") or run.get("task_class") or "") == "advancement_task":
            return DeliveryTurnKind.PRODUCT_PATH_EXECUTION.value
        return DeliveryTurnKind.COMPACT_EVIDENCE.value
    if any(run.get(key) for key in DELIVERY_MATERIAL_EVIDENCE_KEYS):
        return DeliveryTurnKind.COMPACT_EVIDENCE.value

    if any(hint in searchable for hint in ("blocker", "blocked", "cannot proceed", "can't proceed")):
        return DeliveryTurnKind.BLOCKER_WRITEBACK.value

    if outcome == DeliveryOutcome.SURFACE_ONLY or delivery_run_is_surface_only(run) or any(
        hint in classification
        for hint in (
            "contract",
            "prep",
            "preparation",
            "protocol",
            "policy",
            "surface",
            "smoke",
            "setup",
        )
    ):
        return DeliveryTurnKind.CONTRACT_ONLY_PREPARATION.value

    if outcome == DeliveryOutcome.OUTCOME_GAP:
        return DeliveryTurnKind.OUTCOME_GAP.value

    return DeliveryTurnKind.UNKNOWN.value
