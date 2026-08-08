"""Autonomous replan status projections inside the `status` bounded context."""

from __future__ import annotations

import re
from typing import Any

from ..runtime.public_safety import public_safe_compact_text
from ..work_items.autonomous_replan_ack import (
    AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW,
    autonomous_replan_ack_recorded,
    latest_autonomous_replan_ack_for_projection as _latest_autonomous_replan_ack_for_projection,
)
from ..work_items.autonomous_replan_obligation import (
    AUTONOMOUS_REPLAN_STALL_THRESHOLD,
    autonomous_replan_obligation_from_runs as _autonomous_replan_obligation_from_runs,
    autonomous_replan_periodic_review_from_runs as _autonomous_replan_periodic_review_from_runs,
    build_autonomous_replan_obligation as _build_autonomous_replan_obligation,
    run_history_monitor_wait_already_acknowledged as _run_history_monitor_wait_already_acknowledged,
    run_history_stall_signal as _run_history_stall_signal_read_model,
)
from ..work_items.delivery_outcome import (
    PROGRESS_DELIVERY_OUTCOMES,
    normalize_delivery_outcome,
)


DEAD_MONITOR_REPEAT_THRESHOLD = 6
DEAD_MONITOR_REPEAT_SCHEMA_VERSION = "dead_monitor_repeat_v0"
AUTONOMOUS_REPLAN_SCHEMA_VERSION = "autonomous_replan_obligation_v0"
AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD = AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW
AUTONOMOUS_RUN_HISTORY_PROGRESS_OUTCOMES = PROGRESS_DELIVERY_OUTCOMES
AUTONOMOUS_RUN_HISTORY_NEUTRAL_CLASSIFICATIONS = {
    "quota_slot_spent",
    "quota_slot_voided",
    "delivery_completion_spend_accounted_v0",
}
AUTONOMOUS_RUN_HISTORY_STALL_PATTERN = re.compile(
    r"(?i)(?:monitor|observe|observation|poll|watch|quiet|no[-_ ]?op|no[-_ ]?progress|stalled?|unchanged|dependency|停转|无进展|重复|反复|观察|轮询)"
)


def build_autonomous_replan_obligation(
    evidence: list[dict[str, Any]],
    *,
    agent_todos: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _build_autonomous_replan_obligation(
        evidence,
        agent_todos=agent_todos,
        public_safe_compact_text=public_safe_compact_text,
        autonomous_replan_schema_version=AUTONOMOUS_REPLAN_SCHEMA_VERSION,
        autonomous_replan_stall_threshold=AUTONOMOUS_REPLAN_STALL_THRESHOLD,
        dead_monitor_repeat_threshold=DEAD_MONITOR_REPEAT_THRESHOLD,
        dead_monitor_repeat_schema_version=DEAD_MONITOR_REPEAT_SCHEMA_VERSION,
    )


def _run_history_stall_signal(run: dict[str, Any]) -> dict[str, Any] | None:
    return _run_history_stall_signal_read_model(
        run,
        autonomous_replan_ack_recorded=autonomous_replan_ack_recorded,
        neutral_classifications=AUTONOMOUS_RUN_HISTORY_NEUTRAL_CLASSIFICATIONS,
        progress_outcomes=AUTONOMOUS_RUN_HISTORY_PROGRESS_OUTCOMES,
        stall_pattern=AUTONOMOUS_RUN_HISTORY_STALL_PATTERN,
        public_safe_compact_text=public_safe_compact_text,
        normalize_delivery_outcome=normalize_delivery_outcome,
    )


def run_history_monitor_wait_already_acknowledged(
    latest_runs: list[dict[str, Any]] | None,
    *,
    signal_count: int,
) -> bool:
    return _run_history_monitor_wait_already_acknowledged(
        latest_runs,
        signal_count=signal_count,
        autonomous_replan_ack_recorded=autonomous_replan_ack_recorded,
        neutral_classifications=AUTONOMOUS_RUN_HISTORY_NEUTRAL_CLASSIFICATIONS,
    )


def latest_autonomous_replan_ack_for_projection(
    latest_runs: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    return _latest_autonomous_replan_ack_for_projection(
        latest_runs,
        neutral_classifications=AUTONOMOUS_RUN_HISTORY_NEUTRAL_CLASSIFICATIONS,
    )


def autonomous_replan_periodic_review_from_runs(
    latest_runs: list[dict[str, Any]] | None,
    *,
    agent_todos: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return _autonomous_replan_periodic_review_from_runs(
        latest_runs,
        agent_todos=agent_todos,
        autonomous_replan_ack_recorded=autonomous_replan_ack_recorded,
        neutral_classifications=AUTONOMOUS_RUN_HISTORY_NEUTRAL_CLASSIFICATIONS,
        periodic_run_threshold=AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD,
        build_autonomous_replan_obligation=build_autonomous_replan_obligation,
    )


def autonomous_replan_obligation_from_runs(
    latest_runs: list[dict[str, Any]] | None,
    *,
    agent_todos: dict[str, Any] | None,
    agent_id: str | None = None,
) -> dict[str, Any] | None:
    return _autonomous_replan_obligation_from_runs(
        latest_runs,
        agent_todos=agent_todos,
        agent_id=agent_id,
        autonomous_replan_ack_recorded=autonomous_replan_ack_recorded,
        neutral_classifications=AUTONOMOUS_RUN_HISTORY_NEUTRAL_CLASSIFICATIONS,
        progress_outcomes=AUTONOMOUS_RUN_HISTORY_PROGRESS_OUTCOMES,
        stall_pattern=AUTONOMOUS_RUN_HISTORY_STALL_PATTERN,
        public_safe_compact_text=public_safe_compact_text,
        normalize_delivery_outcome=normalize_delivery_outcome,
        build_autonomous_replan_obligation=build_autonomous_replan_obligation,
        autonomous_replan_stall_threshold=AUTONOMOUS_REPLAN_STALL_THRESHOLD,
        dead_monitor_repeat_threshold=DEAD_MONITOR_REPEAT_THRESHOLD,
        dead_monitor_repeat_schema_version=DEAD_MONITOR_REPEAT_SCHEMA_VERSION,
        periodic_run_threshold=AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD,
    )
