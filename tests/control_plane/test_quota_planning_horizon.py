from __future__ import annotations

from loopx.control_plane.effect_program import interpret_quota_should_run_packet
from loopx.control_plane.quota.cli_projection import (
    compact_quota_should_run_cli_payload,
)
from loopx.control_plane.quota.should_run import build_quota_should_run
from loopx.control_plane.quota.turn_envelope import (
    ACTION_SIGNATURE_COVERAGE_V3,
    build_turn_envelope,
)
from loopx.control_plane.testing.action_portfolio_scenarios import (
    ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
    planning_horizon_strategic_context_status,
)
from loopx.control_plane.testing.quota_fixtures import (
    quota_status_payload,
    quota_todo_item,
)


GOAL_ID = ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID
AGENT_ID = ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID


def test_default_quota_and_turn_envelope_expose_one_bounded_planning_horizon() -> None:
    packet = build_quota_should_run(
        planning_horizon_strategic_context_status(),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        turn_instance_id="turn-planning-horizon-001",
    )

    assert packet["selected_todo"]["todo_id"] == "todo_regression_gate"
    horizon = packet["planning_horizon"]
    assert horizon["schema_version"] == "quota_planning_horizon_v0"
    assert horizon["mode"] == "read_only"
    assert [item["todo_id"] for item in horizon["work_items"]] == [
        "todo_regression_gate",
        "todo_per_model_tests",
        "todo_runtime_admission",
        "todo_allowlist_policy",
        "todo_facts_source",
    ]
    assert horizon["selection_contract"]["horizon_changes_selection"] is False
    assert horizon["completeness"]["source_context_todo_count"] == 5
    assert {
        "from_todo_id": "todo_per_model_tests",
        "to_ref": "todo_regression_gate",
        "relation": "successor",
        "enforcement": "lineage_only",
    } in horizon["relations"]
    assert horizon["detail_refs"]["selected_todo"]["todo_id"] == (
        "todo_regression_gate"
    )

    compact = compact_quota_should_run_cli_payload(packet)
    assert compact["planning_horizon"] == horizon
    effect_turn = interpret_quota_should_run_packet(packet)
    assert effect_turn.observation.planning_horizon == horizon

    envelope = build_turn_envelope(packet)
    assert envelope["action"]["planning_horizon"] == horizon
    assert envelope["action_signature"]["coverage"] == (ACTION_SIGNATURE_COVERAGE_V3)
    assert envelope["compaction"]["within_budget"] is True
    assert envelope["compaction"]["envelope_json_bytes"] <= 8_192


def test_single_selected_todo_does_not_add_a_redundant_horizon() -> None:
    selected = quota_todo_item(
        todo_id="todo_only_work",
        index=1,
        priority="P0",
        title="Deliver the only runnable slice.",
        claimed_by=AGENT_ID,
    )
    packet = build_quota_should_run(
        quota_status_payload(
            goal_id=GOAL_ID,
            status="active",
            agent_todo_items=[selected],
            recommended_action=selected["text"],
            next_action=selected["text"],
            coordination={
                "agent_model": "peer_v1",
                "registered_agents": [AGENT_ID],
            },
            claim_scope_agent_id=AGENT_ID,
        ),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert "planning_horizon" not in packet


def test_flat_runnable_backlog_stays_in_action_portfolio_without_horizon() -> None:
    items = [
        quota_todo_item(
            todo_id=f"todo_flat_{index:03d}",
            index=index,
            priority="P0",
            title=f"Deliver independent slice {index}.",
            claimed_by=AGENT_ID,
        )
        for index in range(8)
    ]
    packet = build_quota_should_run(
        quota_status_payload(
            goal_id=GOAL_ID,
            status="active",
            agent_todo_items=items,
            recommended_action=items[0]["text"],
            next_action=items[0]["text"],
            coordination={
                "agent_model": "peer_v1",
                "registered_agents": [AGENT_ID],
            },
            claim_scope_agent_id=AGENT_ID,
        ),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert packet["action_portfolio"]["primary"]["todo_id"] == items[0]["todo_id"]
    assert "planning_horizon" not in packet
