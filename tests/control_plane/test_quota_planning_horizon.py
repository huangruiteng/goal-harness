from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pytest import MonkeyPatch

from loopx.control_plane.effect_program import interpret_quota_should_run_packet
from loopx.control_plane.effect_runtime import effect_runtime_result
from loopx.control_plane.quota.cli_projection import (
    compact_quota_should_run_cli_payload,
)
from loopx.control_plane.quota.should_run import build_quota_should_run
from loopx.control_plane.quota.turn_envelope import (
    ACTION_SIGNATURE_COVERAGE_V3,
    PLANNING_HORIZON_DETAIL_REFS_REF,
    build_turn_envelope,
    quota_action_signature_document,
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
from loopx.control_plane.work_items import action_portfolio as action_portfolio_module
from loopx.status import build_task_graph_projection

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
    assert horizon["detail_refs"]["agent_todos"] == (
        f"quota should-run --goal-id {GOAL_ID} --agent-id {AGENT_ID} "
        "--include-detail agent-todos"
    )
    assert horizon["detail_refs"]["full_todo_list"] == (
        f"todo list --goal-id {GOAL_ID} --role agent --status open "
        f"--agent-id {AGENT_ID}"
    )

    compact = compact_quota_should_run_cli_payload(packet)
    assert compact["planning_horizon"] == horizon
    effect_turn = interpret_quota_should_run_packet(packet)
    assert effect_turn.observation.planning_horizon == horizon

    envelope = build_turn_envelope(packet)
    envelope_horizon = envelope["action"]["planning_horizon"]
    assert "detail_refs" not in envelope_horizon
    assert envelope_horizon["detail_refs_ref"] == PLANNING_HORIZON_DETAIL_REFS_REF
    assert envelope["detail_ref"]["todo_detail"].endswith(
        f"--goal-id {GOAL_ID}"
    )
    assert quota_action_signature_document(packet)["action"][
        "planning_horizon"
    ] == envelope_horizon
    assert envelope["action_signature"]["coverage"] == (ACTION_SIGNATURE_COVERAGE_V3)
    assert envelope["action_signature"]["matches"] is True
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


def test_agent_todo_detail_expands_claim_semantics_from_the_shared_inventory() -> None:
    selected = quota_todo_item(
        todo_id="todo_selected_detail",
        index=1,
        priority="P0",
        title="Deliver the selected slice.",
        claimed_by=AGENT_ID,
    )
    unclaimed = [
        quota_todo_item(
            todo_id=f"todo_unclaimed_{index:03d}",
            index=index + 2,
            priority="P1",
            title=f"Deliver unclaimed slice {index}.",
        )
        for index in range(10)
    ]
    status = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=[selected, *unclaimed],
        recommended_action=selected["text"],
        next_action=selected["text"],
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [AGENT_ID],
        },
        claim_scope_agent_id=AGENT_ID,
    )

    default_packet = build_quota_should_run(
        status,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )
    detail_packet = build_quota_should_run(
        status,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        include_agent_todo_detail=True,
    )

    assert "agent_todo_planning_inventory" not in default_packet
    inventory = detail_packet["agent_todo_planning_inventory"]
    assert inventory["schema_version"] == "todo_planning_inventory_detail_v0"
    assert inventory["item_detail_ref"] == "$.agent_todo_summary"
    inventory_unclaimed = [
        item for item in inventory["items"] if item["claim_state"] == "unclaimed"
    ]
    compact_unclaimed = detail_packet["agent_todo_summary"][
        "unclaimed_priority_open_items"
    ]
    assert len(inventory_unclaimed) == 10
    assert len(inventory_unclaimed) > len(compact_unclaimed)
    runnable_unclaimed = [
        item for item in inventory_unclaimed if item["planning_state"] == "runnable"
    ]
    assert len(runnable_unclaimed) > len(compact_unclaimed)
    assert all(
        item["claim_required_before_work"] is True for item in runnable_unclaimed
    )
    assert all(
        item["claim_required_before_work"] is False
        for item in inventory_unclaimed
        if item["planning_state"] != "runnable"
    )


def test_planning_lenses_share_one_runtime_request(
    monkeypatch: MonkeyPatch,
) -> None:
    operations: list[str] = []

    def recording_effect_runtime_result(
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float = 5.0,
        retry_safe: bool = True,
    ) -> Any:
        operations.append(method)
        return effect_runtime_result(
            method,
            params,
            timeout=timeout,
            retry_safe=retry_safe,
        )

    monkeypatch.setattr(
        action_portfolio_module,
        "effect_runtime_result",
        recording_effect_runtime_result,
    )
    status = planning_horizon_strategic_context_status()

    default_packet = build_quota_should_run(
        status,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )
    assert "planning_horizon" in default_packet
    assert operations == ["work_item.action_portfolio.project"]

    operations.clear()
    detail_packet = build_quota_should_run(
        status,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        include_agent_todo_detail=True,
    )
    assert "agent_todo_planning_inventory" in detail_packet
    assert operations == ["work_item.action_portfolio.project"]


def test_task_graph_reads_deferred_nodes_from_the_shared_planning_source() -> None:
    selected = quota_todo_item(
        todo_id="todo_graph_selected",
        index=2,
        priority="P0",
        title="Deliver the selected graph slice.",
        claimed_by=AGENT_ID,
    )
    deferred = quota_todo_item(
        todo_id="todo_graph_deferred",
        index=1,
        status="deferred",
        priority="P0",
        title="Wait for the deferred predecessor.",
        claimed_by=AGENT_ID,
        successor_todo_ids=[selected["todo_id"]],
    )
    projection = build_task_graph_projection(
        {
            "goal_id": GOAL_ID,
            "agent_todos": {
                "total_count": 2,
                "open_count": 1,
                "deferred_count": 1,
                "items": [selected],
                "deferred_items": [deferred],
                "blocker_items": [],
                "monitor_open_items": [],
            },
            "user_todos": {
                "total_count": 0,
                "open_count": 0,
                "items": [],
            },
        },
        goal={"id": GOAL_ID},
    )

    assert projection is not None
    todo_ids = {
        todo_id
        for node in projection["nodes"]
        for todo_id in node["refs"].get("todo_ids", [])
    }
    assert deferred["todo_id"] in todo_ids
