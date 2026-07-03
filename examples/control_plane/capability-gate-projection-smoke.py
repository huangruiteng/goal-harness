#!/usr/bin/env python3
"""Smoke-test capability-gate projection helpers used by quota."""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.projections.capability_gate import (  # noqa: E402
    _capability_candidate_item,
    _capability_missing_action,
    _sort_capability_runnable_candidates,
)


AGENT_ID = "codex-product-capability"
PRIMARY_AGENT = "codex-main-control"


def todo(
    todo_id: str,
    index: int,
    priority: str,
    *,
    claimed_by: str | None = None,
    blocks_agent: str | None = None,
    action_kind: str | None = None,
    required_capabilities: list[str] | None = None,
    target_capabilities: list[str] | None = None,
) -> dict:
    item = {
        "schema_version": "todo_item_v0",
        "todo_id": todo_id,
        "role": "agent",
        "source_section": "Agent Todo",
        "status": "open",
        "done": False,
        "index": index,
        "priority": priority,
        "text": f"[{priority}] fixture {todo_id}",
        "task_class": "advancement_task",
    }
    if claimed_by:
        item["claimed_by"] = claimed_by
    if blocks_agent:
        item["blocks_agent"] = blocks_agent
    if action_kind:
        item["action_kind"] = action_kind
    if required_capabilities:
        item["required_capabilities"] = required_capabilities
    if target_capabilities:
        item["target_capabilities"] = target_capabilities
    return item


def assert_missing_action_contract() -> None:
    assert _capability_missing_action([]) == "run"
    assert _capability_missing_action(["benchmark_runner"]) == "repair_bridge"
    assert _capability_missing_action(["network"]) == "ask_owner"
    assert _capability_missing_action(["custom_capability"]) == "skip"


def assert_candidate_compaction_contract() -> None:
    item = todo(
        "todo_bridge",
        3,
        "P1",
        claimed_by=AGENT_ID,
        required_capabilities=["shell", "benchmark_runner"],
        target_capabilities=["status_quota_read_model_refactor"],
    )
    candidate = _capability_candidate_item(
        item,
        missing=["benchmark_runner"],
        missing_target_capabilities=["benchmark_runner"],
    )
    assert candidate["todo_id"] == "todo_bridge", candidate
    assert candidate["required_capabilities"] == ["shell", "benchmark_runner"], candidate
    assert candidate["target_capabilities"] == ["status_quota_read_model_refactor"], candidate
    assert candidate["missing_capabilities"] == ["benchmark_runner"], candidate
    assert candidate["missing_target_capabilities"] == ["benchmark_runner"], candidate
    assert candidate["capability_action"] == "repair_bridge", candidate
    assert candidate["capability_repair_mode"] is True, candidate


def assert_current_agent_candidate_order_contract() -> None:
    runnable = [
        todo("todo_unclaimed_p0", 1, "P0"),
        todo("todo_current_p2", 2, "P2", claimed_by=AGENT_ID),
        todo(
            "todo_current_unblock_p2",
            3,
            "P2",
            claimed_by=AGENT_ID,
            blocks_agent="codex-value-explorer",
        ),
        todo("todo_other_p0", 4, "P0", claimed_by=PRIMARY_AGENT),
        todo("todo_primary_review", 5, "P2", claimed_by=AGENT_ID, action_kind="primary_review"),
    ]
    ordered, policy = _sort_capability_runnable_candidates(
        runnable,
        agent_identity={
            "agent_id": AGENT_ID,
            "primary_agent": PRIMARY_AGENT,
        },
    )
    assert policy == "active_next_then_claim_then_unblock_handoff_then_priority_then_repair"
    assert [item["todo_id"] for item in ordered] == [
        "todo_current_unblock_p2",
        "todo_primary_review",
        "todo_current_p2",
        "todo_unclaimed_p0",
        "todo_other_p0",
    ], ordered


def main() -> int:
    assert_missing_action_contract()
    assert_candidate_compaction_contract()
    assert_current_agent_candidate_order_contract()
    print("capability-gate-projection-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
