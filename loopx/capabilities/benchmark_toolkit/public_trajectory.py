"""Public-safe trajectory summaries derived from compact adapter facts.

This module deliberately does not parse task text, event payloads, tool arguments,
or verifier output.  The first active adapter is the DeepSWE native Codex Goal
runner, whose compact receipt already contains the lifecycle counters needed here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


PUBLIC_TRAJECTORY_SUMMARY_SCHEMA_VERSION = "public_trajectory_summary_v0"
NATIVE_GOAL_LIFECYCLE_SCHEMA_VERSION = "native_codex_goal_turn_receipt_v0"

_PUBLIC_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}")
_NOTIFICATION_METHOD = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
    r"(?:(?:/|:)[A-Za-z0-9][A-Za-z0-9_.-]{0,63}){0,3}"
)
_ADAPTER_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
_TERMINAL_NOTIFICATION_METHODS = {
    "turn/completed",
    "event_msg:task_complete",
    "event_msg:task_completed",
    "event_msg:turn_completed",
}


class PublicTrajectorySummaryError(ValueError):
    """A compact adapter receipt cannot form a trustworthy public summary."""


class PublicTrajectoryLifecycleState(str, Enum):
    """States expressible by the native Goal lifecycle counters."""

    ATTACHED = "attached"
    IN_PROGRESS = "in_progress"
    TURN_TERMINAL = "turn_terminal"
    GOAL_TERMINAL = "goal_terminal"


def _non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PublicTrajectorySummaryError(f"{field}_invalid")
    return int(value)


def _public_label(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not _PUBLIC_LABEL.fullmatch(value):
        raise PublicTrajectorySummaryError(f"{field}_invalid")
    return value


@dataclass(frozen=True)
class NativeGoalLifecycleFacts:
    """Allowlisted lifecycle facts from one native Goal compact receipt."""

    goal_status: str
    post_goal_status: str | None
    turn_status: str
    terminal_event_observed: bool
    item_event_count: int
    error_event_count: int
    turn_started_count: int
    turn_completed_count: int
    continuation_turn_completed_count: int
    goal_status_poll_count: int
    notification_counts: tuple[tuple[str, int], ...]

    @classmethod
    def from_receipt(
        cls,
        receipt: Mapping[str, Any] | None,
    ) -> NativeGoalLifecycleFacts:
        if not isinstance(receipt, Mapping):
            raise PublicTrajectorySummaryError("native_goal_lifecycle_receipt_missing")
        if receipt.get("schema_version") != NATIVE_GOAL_LIFECYCLE_SCHEMA_VERSION:
            raise PublicTrajectorySummaryError("native_goal_lifecycle_schema_invalid")

        terminal_event_observed = receipt.get("terminal_event_observed")
        if not isinstance(terminal_event_observed, bool):
            raise PublicTrajectorySummaryError("terminal_event_observed_invalid")

        raw_notification_counts = receipt.get("notification_counts")
        if not isinstance(raw_notification_counts, Mapping):
            raise PublicTrajectorySummaryError("notification_counts_missing")
        notification_counts: list[tuple[str, int]] = []
        for raw_method, raw_count in raw_notification_counts.items():
            method = _public_label(raw_method, field="notification_method")
            assert method is not None
            if not _NOTIFICATION_METHOD.fullmatch(method):
                raise PublicTrajectorySummaryError("notification_method_invalid")
            notification_counts.append(
                (
                    method,
                    _non_negative_int(raw_count, field="notification_count"),
                )
            )
        notification_counts.sort()

        facts = cls(
            goal_status=str(
                _public_label(receipt.get("goal_status"), field="goal_status")
            ),
            post_goal_status=_public_label(
                receipt.get("post_goal_status"),
                field="post_goal_status",
                optional=True,
            ),
            turn_status=str(
                _public_label(receipt.get("turn_status"), field="turn_status")
            ),
            terminal_event_observed=terminal_event_observed,
            item_event_count=_non_negative_int(
                receipt.get("item_event_count"), field="item_event_count"
            ),
            error_event_count=_non_negative_int(
                receipt.get("error_event_count"), field="error_event_count"
            ),
            turn_started_count=_non_negative_int(
                receipt.get("turn_started_count"), field="turn_started_count"
            ),
            turn_completed_count=_non_negative_int(
                receipt.get("turn_completed_count"), field="turn_completed_count"
            ),
            continuation_turn_completed_count=_non_negative_int(
                receipt.get("goal_continuation_turn_completed_count"),
                field="goal_continuation_turn_completed_count",
            ),
            goal_status_poll_count=_non_negative_int(
                receipt.get("goal_status_poll_count"),
                field="goal_status_poll_count",
            ),
            notification_counts=tuple(notification_counts),
        )
        facts._validate_consistency()
        return facts

    def _validate_consistency(self) -> None:
        counts = dict(self.notification_counts)
        item_events = sum(
            count
            for method, count in self.notification_counts
            if method.startswith(("item/", "response_item:"))
        )
        terminal_events = sum(
            counts.get(method, 0) for method in _TERMINAL_NOTIFICATION_METHODS
        )
        if item_events != self.item_event_count:
            raise PublicTrajectorySummaryError("item_event_count_inconsistent")
        if counts.get("error", 0) != self.error_event_count:
            raise PublicTrajectorySummaryError("error_event_count_inconsistent")
        if counts.get("turn/started", 0) != self.turn_started_count:
            raise PublicTrajectorySummaryError("turn_started_count_inconsistent")
        if terminal_events != self.turn_completed_count:
            raise PublicTrajectorySummaryError("turn_completed_count_inconsistent")
        if self.turn_completed_count > self.turn_started_count:
            raise PublicTrajectorySummaryError("turn_lifecycle_order_invalid")
        if self.continuation_turn_completed_count != max(
            0, self.turn_completed_count - 1
        ):
            raise PublicTrajectorySummaryError("continuation_count_inconsistent")
        if self.terminal_event_observed != (self.turn_completed_count > 0):
            raise PublicTrajectorySummaryError("terminal_event_state_inconsistent")

    @property
    def lifecycle_state(self) -> PublicTrajectoryLifecycleState:
        if self.turn_started_count == 0:
            return PublicTrajectoryLifecycleState.ATTACHED
        if self.turn_completed_count < self.turn_started_count:
            return PublicTrajectoryLifecycleState.IN_PROGRESS
        if self.post_goal_status and self.post_goal_status != "active":
            return PublicTrajectoryLifecycleState.GOAL_TERMINAL
        return PublicTrajectoryLifecycleState.TURN_TERMINAL


def build_native_goal_public_trajectory_summary(
    receipt: Mapping[str, Any] | None,
    *,
    adapter_id: str,
) -> dict[str, Any]:
    """Reduce one native Goal receipt to content-free trajectory lifecycle facts."""

    if not isinstance(adapter_id, str) or not _ADAPTER_ID.fullmatch(adapter_id):
        raise PublicTrajectorySummaryError("adapter_id_invalid")
    normalized_adapter_id = adapter_id
    facts = NativeGoalLifecycleFacts.from_receipt(receipt)
    notification_counts = dict(facts.notification_counts)
    item_type_event_counts: dict[str, int] = {}
    for method, count in facts.notification_counts:
        if not method.startswith("item/"):
            continue
        method_parts = method.split("/")
        if len(method_parts) < 3:
            # ``item/started`` and ``item/completed`` carry their item type in
            # the omitted payload, so the compact receipt cannot classify them.
            continue
        _, item_type, *_ = method_parts
        item_type_event_counts[item_type] = (
            item_type_event_counts.get(item_type, 0) + count
        )

    state = facts.lifecycle_state
    return {
        "schema_version": PUBLIC_TRAJECTORY_SUMMARY_SCHEMA_VERSION,
        "summary_kind": "native_goal_lifecycle",
        "adapter_id": normalized_adapter_id,
        "source_schema_version": NATIVE_GOAL_LIFECYCLE_SCHEMA_VERSION,
        "lifecycle_state": state.value,
        "complete": state is PublicTrajectoryLifecycleState.GOAL_TERMINAL,
        "goal_status": facts.goal_status,
        "post_goal_status": facts.post_goal_status,
        "turn_status": facts.turn_status,
        "counts": {
            "notification_event_count": sum(notification_counts.values()),
            "notification_kind_count": len(notification_counts),
            "item_event_count": facts.item_event_count,
            "error_event_count": facts.error_event_count,
            "turn_started_count": facts.turn_started_count,
            "turn_completed_count": facts.turn_completed_count,
            "continuation_turn_completed_count": (
                facts.continuation_turn_completed_count
            ),
            "goal_status_poll_count": facts.goal_status_poll_count,
        },
        "notification_counts": notification_counts,
        "item_type_event_counts": dict(sorted(item_type_event_counts.items())),
        "coverage": {
            "adapter_lifecycle_facts_only": True,
            "raw_event_payloads_inspected": False,
            "message_content_available": False,
            "tool_call_semantics_available": False,
        },
        "public_boundary": {
            "raw_task_text_recorded": False,
            "raw_assistant_message_recorded": False,
            "raw_tool_arguments_recorded": False,
            "raw_tool_output_recorded": False,
            "raw_verifier_output_recorded": False,
            "credentials_recorded": False,
            "local_paths_recorded": False,
        },
    }


__all__ = [
    "NATIVE_GOAL_LIFECYCLE_SCHEMA_VERSION",
    "PUBLIC_TRAJECTORY_SUMMARY_SCHEMA_VERSION",
    "NativeGoalLifecycleFacts",
    "PublicTrajectoryLifecycleState",
    "PublicTrajectorySummaryError",
    "build_native_goal_public_trajectory_summary",
]
