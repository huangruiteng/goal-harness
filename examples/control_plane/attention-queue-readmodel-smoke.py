#!/usr/bin/env python3
"""Smoke-test attention queue read-model parity."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loopx import status as status_module  # noqa: E402
from loopx.control_plane.work_items import attention_queue as queue_read_model  # noqa: E402


def direct_queue(
    items: list[dict[str, Any]],
    *,
    goal_id_filter: str | None,
    backlog: dict[str, Any] | None,
    monitors: dict[str, Any] | None,
) -> dict[str, Any]:
    return queue_read_model.build_attention_queue_projection(
        items=items,
        goal_id_filter=goal_id_filter,
        autonomous_backlog_candidates=backlog,
        autonomous_monitor_candidates=monitors,
        monitor_signal_waiting_on=status_module.MONITOR_SIGNAL_WAITING_ON,
    )


def direct_merge_global_registry(
    *,
    health_items: list[dict[str, Any]],
    history_items: list[dict[str, Any]],
    findings: list[Any],
    goal_id_filter: str | None,
) -> None:
    queue_read_model.merge_global_registry_findings(
        health_items=health_items,
        history_items=history_items,
        findings=findings,
        goal_id_filter=goal_id_filter,
        source_registry_shadow_findings=status_module.SOURCE_REGISTRY_SHADOW_FINDINGS,
        attention_item=status_module.attention_item,
        attach_global_registry_shadow_finding=status_module.attach_global_registry_shadow_finding,
    )


def open_agent_todos(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "first_open_items": [
            {
                "index": index,
                "text": item["text"],
                "status": "open",
                "task_class": item["task_class"],
                "action_kind": item.get("action_kind"),
            }
            for index, item in enumerate(items, start=1)
        ]
    }


def queue_item(goal_id: str, waiting_on: str, *, agent_todos: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "goal_id": goal_id,
        "status": "state_refreshed",
        "waiting_on": waiting_on,
        "severity": "action",
        "recommended_action": "continue bounded work",
        "source": "latest_run",
        "quota": {"state": "eligible"},
        "project_asset": {},
    }
    if agent_todos:
        item["agent_todos"] = agent_todos
    return item


def assert_projection_parity() -> None:
    items = [
        queue_item(
            "goal-a",
            "codex",
            agent_todos=open_agent_todos(
                {
                    "text": "[P1] Extract another durable read-model seam",
                    "task_class": "advancement_task",
                    "action_kind": "read_model_refactor",
                }
            ),
        ),
        queue_item("goal-b", "controller"),
        queue_item("goal-c", "external_evidence"),
        queue_item(
            "goal-d",
            status_module.MONITOR_SIGNAL_WAITING_ON,
            agent_todos=open_agent_todos(
                {
                    "text": "[P2] Monitor compact status drift",
                    "task_class": "continuous_monitor",
                    "action_kind": "monitor",
                }
            ),
        ),
    ]
    backlog = status_module.autonomous_backlog_candidates(items)
    monitors = status_module.autonomous_monitor_candidates(items)

    wrapper = status_module.build_attention_queue_projection(
        items=deepcopy(items),
        goal_id_filter="goal-a",
        autonomous_backlog_candidates=deepcopy(backlog),
        autonomous_monitor_candidates=deepcopy(monitors),
    )
    direct = direct_queue(
        deepcopy(items),
        goal_id_filter="goal-a",
        backlog=deepcopy(backlog),
        monitors=deepcopy(monitors),
    )

    assert wrapper == direct, (wrapper, direct)
    assert wrapper["item_count"] == 4, wrapper
    assert wrapper["needs_user_or_controller"] == 1, wrapper
    assert wrapper["needs_controller"] == 1, wrapper
    assert wrapper["needs_codex"] == 1, wrapper
    assert wrapper["watching_external_evidence"] == 1, wrapper
    assert wrapper["watching_monitor"] == 1, wrapper
    assert wrapper["goal_filter"] == "goal-a", wrapper
    assert wrapper["autonomous_backlog_candidates"]["open_count"] == 1, wrapper
    assert wrapper["autonomous_monitor_candidates"]["open_count"] == 1, wrapper


def assert_global_registry_merge_parity() -> None:
    findings: list[Any] = [
        {
            "kind": "source_registry_missing",
            "goal_id": "goal-shadow",
            "severity": "high",
            "message": "source registry missing",
            "recommended_action": "restore source registry",
        },
        {
            "kind": "registry_contract_failed",
            "goal_id": "goal-health",
            "severity": "action",
            "recommended_action": "repair registry contract",
        },
        {
            "kind": "filtered_registry_issue",
            "goal_id": "other-goal",
            "goal_ids": ["goal-filter"],
            "severity": "action",
            "recommended_action": "inspect filtered goal reference",
        },
        {
            "kind": "ignored_info",
            "goal_id": "ignored",
            "severity": "info",
            "recommended_action": "do not surface",
        },
    ]
    wrapper_health: list[dict[str, Any]] = []
    wrapper_history = [queue_item("goal-shadow", "codex")]
    direct_health: list[dict[str, Any]] = []
    direct_history = [queue_item("goal-shadow", "codex")]

    status_module.merge_global_registry_attention_findings(
        health_items=wrapper_health,
        history_items=wrapper_history,
        findings=deepcopy(findings),
        goal_id_filter="goal-filter",
    )
    direct_merge_global_registry(
        health_items=direct_health,
        history_items=direct_history,
        findings=deepcopy(findings),
        goal_id_filter="goal-filter",
    )
    assert wrapper_health == direct_health, (wrapper_health, direct_health)
    assert wrapper_history == direct_history, (wrapper_history, direct_history)
    assert not wrapper_history[0].get("global_registry_shadow_findings"), wrapper_history
    assert [item["goal_id"] for item in wrapper_health] == ["other-goal"], wrapper_health

    wrapper_health = []
    wrapper_history = [queue_item("goal-shadow", "codex")]
    status_module.merge_global_registry_attention_findings(
        health_items=wrapper_health,
        history_items=wrapper_history,
        findings=deepcopy(findings),
        goal_id_filter=None,
    )
    assert wrapper_history[0]["global_registry_shadow_findings"][0]["kind"] == "source_registry_missing"
    assert wrapper_history[0]["project_asset"]["global_registry_shadow_findings"]["open"] == 1
    assert [item["goal_id"] for item in wrapper_health] == ["goal-health", "other-goal"], wrapper_health


def main() -> int:
    assert_projection_parity()
    assert_global_registry_merge_parity()
    print("attention-queue-readmodel-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
