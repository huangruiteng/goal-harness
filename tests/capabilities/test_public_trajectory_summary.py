from __future__ import annotations

import copy
import json
from collections.abc import Callable

import pytest

from loopx.capabilities.benchmark_toolkit import (
    NATIVE_GOAL_LIFECYCLE_SCHEMA_VERSION,
    PUBLIC_TRAJECTORY_SUMMARY_SCHEMA_VERSION,
    PublicTrajectorySummaryError,
    build_native_goal_public_trajectory_summary,
)


def _receipt() -> dict[str, object]:
    return {
        "schema_version": NATIVE_GOAL_LIFECYCLE_SCHEMA_VERSION,
        "goal_status": "active",
        "post_goal_status": "complete",
        "turn_status": "completed",
        "terminal_event_observed": True,
        "item_event_count": 3,
        "error_event_count": 0,
        "turn_started_count": 1,
        "turn_completed_count": 1,
        "goal_continuation_turn_completed_count": 0,
        "goal_status_poll_count": 1,
        "notification_counts": {
            "item/agentMessage/delta": 2,
            "item/commandExecution/completed": 1,
            "turn/completed": 1,
            "turn/started": 1,
        },
    }


def test_native_goal_summary_uses_only_compact_lifecycle_facts() -> None:
    receipt = _receipt()
    private_value = "private-task-body-and-verifier-output"
    receipt["raw_task"] = private_value
    receipt["raw_verifier_output"] = private_value

    summary = build_native_goal_public_trajectory_summary(
        receipt,
        adapter_id="deepswe-native-codex-goal",
    )

    assert summary["schema_version"] == PUBLIC_TRAJECTORY_SUMMARY_SCHEMA_VERSION
    assert summary["lifecycle_state"] == "goal_terminal"
    assert summary["complete"] is True
    assert summary["counts"] == {
        "notification_event_count": 5,
        "notification_kind_count": 4,
        "item_event_count": 3,
        "error_event_count": 0,
        "turn_started_count": 1,
        "turn_completed_count": 1,
        "continuation_turn_completed_count": 0,
        "goal_status_poll_count": 1,
    }
    assert summary["item_type_event_counts"] == {
        "agentMessage": 2,
        "commandExecution": 1,
    }
    assert summary["coverage"]["tool_call_semantics_available"] is False
    assert private_value not in json.dumps(summary, sort_keys=True)


def test_attached_preflight_is_explicitly_not_a_complete_trajectory() -> None:
    receipt = _receipt()
    receipt.update(
        {
            "post_goal_status": None,
            "turn_status": "not_started",
            "terminal_event_observed": False,
            "item_event_count": 0,
            "turn_started_count": 0,
            "turn_completed_count": 0,
            "goal_status_poll_count": 0,
            "notification_counts": {},
        }
    )

    summary = build_native_goal_public_trajectory_summary(
        receipt,
        adapter_id="deepswe-native-codex-goal",
    )

    assert summary["lifecycle_state"] == "attached"
    assert summary["complete"] is False
    assert summary["counts"]["notification_event_count"] == 0


def test_payload_only_item_type_is_not_inferred_from_lifecycle_method() -> None:
    receipt = _receipt()
    receipt["item_event_count"] = 4
    receipt["notification_counts"]["item/started"] = 1  # type: ignore[index]

    summary = build_native_goal_public_trajectory_summary(
        receipt,
        adapter_id="deepswe-native-codex-goal",
    )

    assert summary["counts"]["item_event_count"] == 4
    assert summary["item_type_event_counts"] == {
        "agentMessage": 2,
        "commandExecution": 1,
    }


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (lambda receipt: None, "native_goal_lifecycle_receipt_missing"),
        (
            lambda receipt: receipt.pop("schema_version"),
            "native_goal_lifecycle_schema_invalid",
        ),
        (
            lambda receipt: receipt.pop("notification_counts"),
            "notification_counts_missing",
        ),
        (
            lambda receipt: receipt.__setitem__("item_event_count", True),
            "item_event_count_invalid",
        ),
        (
            lambda receipt: receipt.__setitem__("item_event_count", 2),
            "item_event_count_inconsistent",
        ),
        (
            lambda receipt: receipt.__setitem__("turn_completed_count", 2),
            "turn_completed_count_inconsistent",
        ),
    ],
)
def test_missing_or_malformed_lifecycle_facts_fail_closed(
    mutate: Callable[[dict[str, object]], object],
    error_code: str,
) -> None:
    receipt = copy.deepcopy(_receipt())
    result = mutate(receipt)
    candidate = None if result is None and error_code.endswith("receipt_missing") else receipt

    with pytest.raises(PublicTrajectorySummaryError, match=f"^{error_code}$"):
        build_native_goal_public_trajectory_summary(
            candidate,
            adapter_id="deepswe-native-codex-goal",
        )
