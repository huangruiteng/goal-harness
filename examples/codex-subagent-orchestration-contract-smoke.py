#!/usr/bin/env python3
"""Smoke-test the Codex sub-agent shared-control-plane contract."""

from __future__ import annotations

import json
from pathlib import Path

from loopx.control_plane.turn_driver import build_loopx_turn_plan
from loopx.control_plane.turn_driver.child_execution_topology import (
    build_multi_agent_execution_topology,
    child_execution_receipts_json_schema,
    normalize_multi_agent_host_execution_receipts,
    reconcile_multi_agent_execution,
)
from loopx.control_plane.turn_driver.child_host_adapter import (
    project_child_context_adapter,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "integrations" / "codex-subagent-orchestration.md"
TOPOLOGY_RFC = (
    REPO_ROOT
    / "docs"
    / "architecture"
    / "rfcs"
    / "generic-multi-agent-execution-topology-v0.md"
)
DRIFT_FIXTURE = (
    REPO_ROOT
    / "examples"
    / "fixtures"
    / "multi-agent-execution-topology-drift.public.json"
)

REQUIRED_PHRASES = (
    "shared control plane",
    "subagent_control_plane_handoff_v0",
    "`parent_goal_id`",
    "`authority_artifact`",
    "`latest_state_ref`",
    "`quota_gate_snapshot`",
    "`evidence_boundary`",
    "`writeback_spend_contract`",
    "`child_guard_policy`",
    "`prevention_first_v0`",
    "`child_execution_task_packet_v0`",
    "`task_packet_digest`",
    "temporary task coordinator",
    "child worker reports evidence only; task coordinator writes accepted state and spends",
    "control_plane_handoff_version",
    "It does not own durable goal authority",
    "one pending lease for `(goal_id, todo_id)`",
    "`goal_id` is the shared control-plane lane",
    "`todo_id` is the work item being claimed",
    '"agent_model": "peer_v1"',
    "independent worktrees",
    "subagents that parallelize multiple Todos inside one registered agent lane",
    "does not describe orchestration among multiple registered LoopX agents",
    "Multiple registered LoopX agents remain equal peers",
    "Subagent cards or host workers must never be reclassified as peer agents",
    "Review remains `action_kind=review`",
    "Dormant registered agents and closed, blocked, or deferred todos are not coordinator candidates.",
    "multi_agent_execution_topology_v0",
    "multi_agent_host_execution_receipt_v0",
    "multi_agent_control_plane_reconciliation_v0",
    "worktree proves filesystem isolation",
    "Do not spawn without a current admitted child lane",
    "The Guard is fail-local",
    "`parent_blocked=false`",
    "`spawn_agent(fork_context=false)`",
    "`subagent_context_fork`",
    "neither the task packet nor its digest contains Codex tool names or arguments",
)

TOPOLOGY_REQUIRED_PHRASES = (
    "Status: Draft",
    "## TL;DR",
    "ephemeral subagents that parallelize",
    "LoopX versus Harness",
    "Child packets never copy parent-owned",
    "valid siblings and the parent remain runnable",
    "evidence-acceptance enforcement still require",
    "`serial`",
    "`ephemeral_children`",
    "`task_orchestration_contract_v2`",
    "`task_orchestration_contract_v1`",
    "`multi_agent_execution_topology_v0`",
    "`multi_agent_host_execution_receipt_v0`",
    "`multi_agent_control_plane_reconciliation_v0`",
    "`child_execution_task_packet_v0`",
    "`child_execution_guard_v0`",
    "`unadmitted_child_spawn`",
    "`child_capacity_exceeded`",
    "`child_task_packet_incomplete`",
    "`task_packet_mismatch`",
    "`context_mode_mismatch`",
    "`side_effect_boundary_exceeded`",
    "`loopx/control_plane/turn_driver/` task-packet, receipt, and reconciliation",
    "`control_plane/turn_driver/child_execution_topology.py`",
    "`demo/multi_agent/` package is a source-checkout",
    "This slice itself introduced no runtime behavior.",
    "a research-specific coordinator or worker protocol",
    "This contract does not coordinate",
    "multiple registered LoopX agents",
    "The correction is not to call the children LoopX agents",
    "`parent_blocked` remains `false`",
    "evidence acceptance, live tool interception",
    "Context creation is a Harness/host capability, not a LoopX control-plane",
)

FORBIDDEN_PHRASES = (
    "PRIVATE_HOME/",
    "lark" + "office.com",
    "~/.codex/sessions",
    "raw_thread",
    "session_history",
    "coordination.primary_agent",
    "primary-agent review todo",
    "side agents",
    "main controller",
    '"role": "controller"',
    '"role": "subagent"',
    "controller owns",
    "parent writes and spends",
    '"session_ref":',
    "/Users/",
)


def _child_operation(
    *,
    todo_id: str = "todo_review",
    include_acceptance: bool = True,
) -> dict[str, object]:
    brief: dict[str, object] = {
        "todo_id": todo_id,
        "objective": "Review one admitted change.",
        "action_kind": "review",
        "task_domain": "review",
        "required_capabilities": [],
        "task_repository": None,
        "required_write_scopes": [],
        "workspace_isolation": "not_required",
        "target_key": None,
        "authority_artifact": "quota_should_run.goal_boundary",
        "latest_state_ref": "quota_should_run.action_signature.source_hash",
        "expected_output": "public_safe_evidence",
        "execution_policy": {
            "timeout": "bounded_by_host_turn",
            "cancel": "task_coordinator_or_host_timeout",
        },
        "child_guard_policy": "prevention_first_v0",
        "validation_policy": "report validation commands and results",
    }
    if include_acceptance:
        brief["acceptance"] = [
            "report completed scope and evidence",
            "do not write LoopX state or spend quota",
        ]
    return {
        "schema_version": "loopx_child_host_operation_v0",
        "todo_id": todo_id,
        "recommended_context": "fresh",
        "available_contexts": ["fresh"],
        "brief": brief,
    }


def _turn_envelope(*, max_children: int = 1) -> dict[str, object]:
    return {
        "goal_id": "example-pr-program",
        "agent_id": "codex-parent",
        "task_orchestration_contract": {
            "schema_version": "task_orchestration_contract_v2",
            "mode": "adaptive",
            "coordinator_agent_id": "codex-parent",
            "max_children": max_children,
        },
    }


def _turn_plan_envelope() -> dict[str, object]:
    envelope = _turn_envelope()
    envelope.update(
        {
            "ok": True,
            "schema_version": "loopx_turn_envelope_v0",
            "should_run": True,
            "effective_action": "normal_run",
            "action": {
                "must_attempt": True,
                "delivery_allowed": True,
                "quiet_noop_allowed": False,
                "selected_todo": {
                    "todo_id": "todo_review",
                    "text": "Review one admitted change.",
                },
            },
            "user": {
                "action_required": False,
                "open_count": 0,
                "notify": "DONT_NOTIFY",
            },
            "writeback": {"spend_after_validation": True},
            "scheduler": {"action": "run_now"},
            "action_signature": {
                "matches": True,
                "source_hash": "sha256:" + "b" * 64,
                "envelope_hash": "sha256:" + "b" * 64,
            },
            "compaction": {"within_budget": True},
        }
    )
    orchestration = envelope["task_orchestration_contract"]
    assert isinstance(orchestration, dict)
    orchestration.update(
        {
            "child_brief_defaults": {
                "schema_version": "subagent_control_plane_handoff_v0",
                "authority_artifact": "quota_should_run.goal_boundary",
                "latest_state_ref": (
                    "quota_should_run.action_signature.source_hash"
                ),
                "context_policy": {
                    "selection_owner": "task_coordinator",
                    "default": "fresh",
                    "allowed": ["fresh"],
                },
                "expected_output": "public_safe_evidence",
                "execution_policy": {
                    "timeout": "bounded_by_host_turn",
                    "cancel": "task_coordinator_or_host_timeout",
                },
                "child_guard_policy": "prevention_first_v0",
                "validation_policy": "report validation commands and results",
                "acceptance": [
                    "report completed scope and evidence",
                    "do not write LoopX state or spend quota",
                ],
            },
            "eligible_child_lanes": [
                {
                    "todo_id": "todo_review",
                    "task_domain": "review",
                    "execution_kind": "ephemeral_child",
                    "child_brief": _child_operation()["brief"],
                }
            ],
            "writeback_owner": "task_coordinator",
        }
    )
    return envelope


def _matching_receipt(
    topology: dict[str, object],
    *,
    effect_classes: list[str] | None = None,
) -> dict[str, object]:
    lanes = topology["lanes"]
    assert isinstance(lanes, list)
    lane = lanes[0]
    assert isinstance(lane, dict)
    return {
        "schema_version": "multi_agent_host_execution_receipt_v0",
        "bundle_id": topology["bundle_id"],
        "lane_id": lane["lane_id"],
        "goal_id": topology["goal_id"],
        "todo_id": lane["todo_id"],
        "execution_kind": "ephemeral_child",
        "runtime_id": "codex_app",
        "worker_ref": "worker-review",
        "source_state_ref": topology["source_state_ref"],
        "task_packet_digest": lane["task_packet_digest"],
        "context_mode": lane["task_packet"]["context"]["mode"],
        "workspace_ref": None,
        "status": "completed",
        "effect_classes": effect_classes or ["local_read"],
        "evidence_refs": ["artifact:review"],
        "raw_transcript_copied": False,
    }


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    topology = TOPOLOGY_RFC.read_text(encoding="utf-8")
    drift_fixture = json.loads(DRIFT_FIXTURE.read_text(encoding="utf-8"))
    compact = " ".join(text.split())
    for phrase in REQUIRED_PHRASES:
        assert phrase in compact, phrase
    for phrase in TOPOLOGY_REQUIRED_PHRASES:
        assert phrase in topology, phrase
    for source in (text, topology):
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in source, phrase
    assert text.count("subagent_control_plane_handoff_v0") >= 2, text
    assert text.count("## ") >= 7, text
    rejection_cases = {
        case["case_id"]: case for case in drift_fixture["pre_spawn_rejections"]
    }
    incomplete_case = rejection_cases["child_task_packet_incomplete"]
    incomplete_topology = build_multi_agent_execution_topology(
        turn_envelope=_turn_envelope(),
        child_operations=[_child_operation(include_acceptance=False)],
        turn_key="sha256:" + "a" * 64,
        source_state_ref="sha256:" + "b" * 64,
    )
    assert incomplete_topology is not None
    assert incomplete_topology["topology"] == "serial"
    assert incomplete_topology["lanes"] == []
    incomplete_rejection = incomplete_topology["pre_spawn_rejections"][0]
    assert incomplete_rejection["reason_codes"] == [
        incomplete_case["expected_reason_code"]
    ]
    assert incomplete_rejection["parent_blocked"] is False

    capacity_case = rejection_cases["child_capacity_exceeded"]
    capacity_topology = build_multi_agent_execution_topology(
        turn_envelope=_turn_envelope(
            max_children=capacity_case["execution_envelope"]["max_children"]
        ),
        child_operations=[
            _child_operation(todo_id="todo_review"),
            _child_operation(todo_id="todo_validate"),
        ],
        turn_key="sha256:" + "a" * 64,
        source_state_ref="sha256:" + "b" * 64,
    )
    assert capacity_topology is not None
    assert len(capacity_topology["lanes"]) == 1
    capacity_rejection = capacity_topology["pre_spawn_rejections"][0]
    assert capacity_rejection["reason_codes"] == [
        capacity_case["expected_reason_code"]
    ]
    assert capacity_rejection["parent_blocked"] is False

    topology_packet = build_multi_agent_execution_topology(
        turn_envelope=_turn_envelope(),
        child_operations=[_child_operation()],
        turn_key="sha256:" + "a" * 64,
        source_state_ref="sha256:" + "b" * 64,
    )
    assert topology_packet is not None
    lane = topology_packet["lanes"][0]
    receipt_schema = child_execution_receipts_json_schema()["items"]
    assert set(receipt_schema["required"]) == set(receipt_schema["properties"])
    assert {"agent_id", "session_ref", "task_lease_ref"}.isdisjoint(
        receipt_schema["properties"]
    )
    assert topology_packet["coordinator_agent_id"] == "codex-parent"
    assert lane["task_packet"]["schema_version"] == "child_execution_task_packet_v0"
    assert lane["task_packet"]["context"] == {
        "mode": "fresh",
        "inheritance": "none",
    }
    assert {
        "host",
        "native_operation",
        "native_arguments",
        "fork_context",
    }.isdisjoint(lane["task_packet"]["context"])
    assert lane["task_packet"]["guard"]["parent_blocked"] is False

    codex_plan = build_loopx_turn_plan(
        _turn_plan_envelope(),
        host="codex-cli",
        execution_mode="interactive-visible",
    )
    claude_plan = build_loopx_turn_plan(
        _turn_plan_envelope(),
        host="claude-code",
        execution_mode="interactive-visible",
    )
    assert (
        codex_plan["child_operations"][0]["task_packet_digest"]
        == claude_plan["child_operations"][0]["task_packet_digest"]
    )
    assert codex_plan["child_operations"][0]["host_adapter"] == {
        "host": "codex-cli",
        "native_operation": "spawn_agent",
        "arguments": {"fork_context": False},
        "requires_session": False,
    }
    assert (
        project_child_context_adapter(
            host="codex-cli",
            context_mode="resume",
        )
        is None
    )
    assert claude_plan["child_operations"][0]["host_adapter"] == {
        "host": "claude-code",
        "native_operation": "Task",
        "arguments": {},
        "requires_session": False,
    }

    validation_operation = _child_operation()
    validation_brief = validation_operation["brief"]
    assert isinstance(validation_brief, dict)
    validation_brief["validation_declared"] = True
    validation_topology = build_multi_agent_execution_topology(
        turn_envelope=_turn_envelope(),
        child_operations=[validation_operation],
        turn_key="sha256:" + "c" * 64,
        source_state_ref="sha256:" + "d" * 64,
    )
    assert validation_topology is not None
    validation = validation_topology["lanes"][0]["task_packet"]["validation"]
    assert validation["authority_ref"] == "todo:todo_review:completion_validation"
    assert validation["execution_owner"] == "registered_parent"
    assert validation["command_disclosed"] is False

    reconciliation_cases = {
        case["case_id"]: case for case in drift_fixture["reconciliation_cases"]
    }
    unadmitted_case = reconciliation_cases["unadmitted_child"]
    unadmitted_receipts = normalize_multi_agent_host_execution_receipts(
        [unadmitted_case["receipt"]]
    )
    unadmitted = reconcile_multi_agent_execution(None, unadmitted_receipts)
    assert unadmitted is not None
    orphan = unadmitted["orphaned_receipts"][0]
    assert orphan["reason_codes"] == unadmitted_case["expected_reason_codes"]
    assert orphan["evidence_disposition"] == "quarantined"
    assert orphan["parent_blocked"] is False

    packet_case = reconciliation_cases["task_packet_mismatch"]
    packet_receipt = _matching_receipt(topology_packet)
    packet_receipt["task_packet_digest"] = "sha256:" + "0" * 64
    packet_mismatch = reconcile_multi_agent_execution(
        topology_packet,
        normalize_multi_agent_host_execution_receipts([packet_receipt]),
    )
    assert packet_mismatch is not None
    packet_lane = packet_mismatch["lanes"][0]
    assert packet_lane["reason_codes"] == packet_case["expected_reason_codes"]
    assert packet_lane["evidence_disposition"] == "quarantined"
    assert packet_lane["parent_blocked"] is False

    context_case = reconciliation_cases["context_mode_mismatch"]
    context_receipt = _matching_receipt(topology_packet)
    context_receipt["context_mode"] = context_case["observed_context_mode"]
    context_mismatch = reconcile_multi_agent_execution(
        topology_packet,
        normalize_multi_agent_host_execution_receipts([context_receipt]),
    )
    assert context_mismatch is not None
    context_lane = context_mismatch["lanes"][0]
    assert context_lane["reason_codes"] == context_case["expected_reason_codes"]
    assert context_lane["evidence_disposition"] == "quarantined"
    assert context_lane["parent_blocked"] is False

    effect_case = reconciliation_cases["side_effect_boundary_exceeded"]
    effect_receipt = _matching_receipt(
        topology_packet,
        effect_classes=effect_case["observed_effect_classes"],
    )
    effect_mismatch = reconcile_multi_agent_execution(
        topology_packet,
        normalize_multi_agent_host_execution_receipts([effect_receipt]),
    )
    assert effect_mismatch is not None
    effect_lane = effect_mismatch["lanes"][0]
    assert effect_lane["reason_codes"] == effect_case["expected_reason_codes"]
    assert effect_lane["evidence_disposition"] == "quarantined"
    assert effect_lane["parent_blocked"] is False
    assert effect_lane["fallback_actions"] == effect_case["fallback_actions"]
    assert effect_mismatch["parent_blocked"] is False
    assert effect_mismatch["parent_continuation"] == "continue"
    assert effect_mismatch["child_guard"] == drift_fixture["child_guard"]
    assert all(value is False for value in drift_fixture["boundary"].values())
    print("codex-subagent-orchestration-contract-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
