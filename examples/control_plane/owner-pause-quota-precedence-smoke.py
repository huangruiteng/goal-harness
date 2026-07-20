#!/usr/bin/env python3
"""Smoke-test explicit owner pause outranking autonomous quota work."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from loopx.control_plane.scheduler.execution_context import (  # noqa: E402
    GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT,
)
from loopx.control_plane.testing.quota_fixtures import (  # noqa: E402
    quota_status_payload,
    quota_todo_item,
    quota_todo_summary,
)
from loopx.quota import build_quota_should_run  # noqa: E402


GOAL_ID = "owner-pause-precedence-smoke"
CURRENT_AGENT = "codex-current"
PEER_AGENT = "codex-peer"


def paused_quota(items: list[dict]) -> dict:
    agent_todos = quota_todo_summary(
        items,
        role="agent",
        claim_scope_agent_id=CURRENT_AGENT,
    )
    payload = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        recommended_action="Continue autonomous work.",
        agent_todos=agent_todos,
        user_todo_items=[
            quota_todo_item(
                todo_id="todo_user_notice",
                role="user",
                title="Review an unrelated decision when convenient.",
                task_class="user_action",
            )
        ],
        quota_state="paused",
        quota_extra={"compute": 0.0},
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [CURRENT_AGENT, PEER_AGENT],
        },
        latest_runs=[
            {
                "classification": "goal_vision_projection",
                "agent_id": CURRENT_AGENT,
                "agent_vision": {
                    "schema_version": "goal_vision_replan_contract_v0",
                    "agent_id": CURRENT_AGENT,
                    "state": "active",
                    "vision_patch": {
                        "acceptance_summary": "Keep advancing the current stage.",
                        "replan_trigger_summary": "No runnable current-agent work.",
                        "advancement_policy": "repeat_until_closed",
                    },
                },
            }
        ],
    )
    return build_quota_should_run(
        payload,
        goal_id=GOAL_ID,
        agent_id=CURRENT_AGENT,
        scheduler_execution_context=GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT,
    )


def assert_owner_pause(decision: dict) -> None:
    assert decision["decision"] == "skip", decision
    assert decision["state"] == "paused", decision
    assert decision["effective_action"] == "owner_pause", decision
    assert decision["should_run"] is False, decision
    for field in (
        "normal_delivery_allowed",
        "recovery_delivery_allowed",
        "self_repair_allowed",
        "capability_repair_allowed",
        "workspace_repair_allowed",
        "actionable_by_codex",
        "requires_user_action",
    ):
        assert decision[field] is False, (field, decision)
    for field in (
        "autonomous_replan_decision",
        "autonomous_replan_obligation",
        "autonomous_replan_scope",
        "required_reads",
        "scoped_user_gate_fallback",
    ):
        assert field not in decision, (field, decision)

    liveness = decision["automation_liveness"]
    assert liveness["automation_action"] == "keep_active_owner_pause_reply_only", (
        liveness
    )
    assert liveness["keep_active"] is True, liveness
    assert liveness["pause_allowed"] is False, liveness

    interaction = decision["interaction_contract"]
    assert interaction["mode"] == "owner_pause", interaction
    assert interaction["user_channel"]["action_required"] is False, interaction
    assert interaction["user_channel"]["notify"] == "DONT_NOTIFY", interaction
    assert interaction["agent_channel"]["must_attempt"] is False, interaction
    assert interaction["agent_channel"]["delivery_allowed"] is False, interaction
    assert interaction["agent_channel"]["quiet_noop_allowed"] is True, interaction
    assert interaction["cli_channel"]["spend_after_validation"] is False, interaction

    scheduler = decision["scheduler_hint"]
    assert scheduler["action"] == "backoff_owner_pause_reply_only", scheduler
    assert scheduler["cadence_class"] == "owner_pause", scheduler
    assert scheduler["unchanged_poll"]["limits"]["local_scheduler"] == 3, scheduler


def main() -> None:
    peer_only = paused_quota(
        [
            quota_todo_item(
                todo_id="todo_peer",
                title="Peer-owned advancement.",
                claimed_by=PEER_AGENT,
            )
        ]
    )
    assert_owner_pause(peer_only)

    own_delivery = paused_quota(
        [
            quota_todo_item(
                todo_id="todo_current",
                title="Current-agent advancement.",
                claimed_by=CURRENT_AGENT,
            )
        ]
    )
    assert_owner_pause(own_delivery)
    print("owner-pause-quota-precedence-smoke: ok")


if __name__ == "__main__":
    main()
