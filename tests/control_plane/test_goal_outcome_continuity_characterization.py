from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from loopx.control_plane.scheduler.execution_context import (
    scheduler_execution_context_for_runtime_profile,
)
from loopx.control_plane.testing.quota_fixtures import (
    quota_status_payload,
    quota_todo_item,
)
from loopx.quota import build_quota_should_run


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "control_plane"
    / "goal_outcome_continuity_characterization_v0.json"
)
APP_SCHEDULER_CONTEXT = scheduler_execution_context_for_runtime_profile(
    "codex_app_heartbeat"
)
_BANNED_KEYS = {
    "credential",
    "credentials",
    "raw_log",
    "raw_logs",
    "raw_state",
    "trajectory",
    "trajectories",
    "verifier_output",
}


def _load_case() -> dict[str, Any]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == (
        "goal_outcome_continuity_characterization_v0"
    )
    return cast(dict[str, Any], payload)


def _walk(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
    else:
        yield "", value


def _semantic_replan_required(case: dict[str, Any]) -> bool:
    final_outcome = case["final_outcome"]
    progress_events = case["progress_events"]
    required_evidence = set(final_outcome["required_evidence"])
    observed_evidence = set(final_outcome["evidence_refs"])
    for event in progress_events:
        observed_evidence.update(event["supporting_evidence"])
    return final_outcome["state"] == "open" and not required_evidence.issubset(
        observed_evidence
    )


def _progress_run(case: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    agent_id = case["agent_id"]
    satisfies_final_outcome = event["satisfies_final_outcome"] is True
    run: dict[str, Any] = {
        "classification": event["event_kind"],
        "generated_at": event["generated_at"],
        "agent_id": agent_id,
        "progress_scope": "agent_lane",
        "delivery_outcome": event["delivery_outcome"],
        "vision_checkpoint": {
            "schema_version": "vision_checkpoint_v0",
            "agent_id": agent_id,
            "required": True,
            "satisfied": True,
            "decision": (
                "patched" if satisfies_final_outcome else "unchanged_with_reason"
            ),
            "triggers": [
                {
                    "kind": "material_delivery_outcome",
                    "delivery_outcome": "outcome_progress",
                }
            ],
        },
    }
    if satisfies_final_outcome:
        run["agent_vision"] = {
            "schema_version": "goal_vision_replan_contract_v0",
            "agent_id": agent_id,
            "state": case["vision"]["state"],
            "vision_patch": {
                "acceptance_summary": case["vision"]["acceptance_summary"],
                "advancement_policy": case["vision"]["advancement_policy"],
            },
            "path_delta": {
                "schema_version": "goal_path_delta_v0",
                "outcome": "continue",
                "prior_assumption": "The milestone path still serves the final outcome.",
                "observed_reality": "The final-outcome evidence is now present.",
                "retained": ["Continue the evidence-backed milestone path."],
                "evidence_refs": event["supporting_evidence"],
            },
        }
        run["vision_checkpoint"]["agent_vision_state"] = case["vision"]["state"]
    else:
        run["vision_checkpoint"]["unchanged_reason"] = case["vision"][
            "unchanged_reason"
        ]
    return run


def _vision_run(case: dict[str, Any]) -> dict[str, Any]:
    agent_id = case["agent_id"]
    return {
        "classification": "vision_replanned",
        "generated_at": "2026-01-01T00:00:00Z",
        "agent_id": agent_id,
        "progress_scope": "agent_lane",
        "agent_vision": {
            "schema_version": "goal_vision_replan_contract_v0",
            "agent_id": agent_id,
            "state": case["vision"]["state"],
            "vision_patch": {
                "acceptance_summary": case["vision"]["acceptance_summary"],
                "advancement_policy": case["vision"]["advancement_policy"],
            },
        },
    }


def _replay_current_path(case: dict[str, Any]) -> dict[str, Any]:
    todo = case["current_todo"]
    agent_id = case["agent_id"]
    latest_runs = [
        *(
            _progress_run(case, event)
            for event in reversed(case["progress_events"])
        ),
        _vision_run(case),
    ]
    status = quota_status_payload(
        goal_id=case["case_id"],
        status="active",
        recommended_action=todo["text"],
        agent_todo_items=[
            quota_todo_item(
                todo_id=todo["todo_id"],
                priority=todo["priority"],
                text=todo["text"],
                status=todo["status"],
                task_class=todo["task_class"],
                action_kind=todo["action_kind"],
                claimed_by=agent_id,
            )
        ],
        claim_scope_agent_id=agent_id,
        latest_runs=latest_runs,
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [agent_id],
        },
    )
    decision = build_quota_should_run(
        status,
        goal_id=case["case_id"],
        agent_id=agent_id,
        scheduler_execution_context=APP_SCHEDULER_CONTEXT,
    )
    selected_todo = decision.get("selected_todo")
    return {
        "decision": decision["decision"],
        "effective_action": decision["effective_action"],
        "selected_todo_id": (
            selected_todo.get("todo_id")
            if isinstance(selected_todo, dict)
            else None
        ),
        "acceptance_gap_decision": decision["vision_continuation_audit"][
            "decision"
        ],
        "replan_required": decision["goal_frontier_projection"][
            "replan_required"
        ],
    }


def test_replay_is_public_safe_and_oracle_is_independent() -> None:
    case = _load_case()

    for key, value in _walk(case):
        assert key.lower() not in _BANNED_KEYS
        if isinstance(value, str):
            assert not value.startswith("/")
            assert "file://" not in value

    assert [event["event_kind"] for event in case["progress_events"]] == [
        "milestone_closeout",
        "release_completed",
        "narrow_gate_cleared",
    ]
    assert case["final_outcome"]["evidence_refs"] == []
    assert {
        event["delivery_outcome"] for event in case["progress_events"]
    } == {"outcome_progress"}
    assert _semantic_replan_required(case) is True
    assert case["independent_oracle"]["replan_required"] is True


def test_final_outcome_evidence_changes_the_independent_oracle() -> None:
    case = deepcopy(_load_case())
    case["progress_events"][-1]["supporting_evidence"].extend(
        case["final_outcome"]["required_evidence"]
    )
    case["progress_events"][-1]["satisfies_final_outcome"] = True

    assert _semantic_replan_required(case) is False
    assert _replay_current_path(case)["replan_required"] is False


def test_repaired_path_replans_semantic_divergence_during_local_progress() -> None:
    case = _load_case()

    observed = _replay_current_path(case)

    assert observed["acceptance_gap_decision"] == "acceptance_gap_open"
    assert observed["replan_required"] is case["independent_oracle"][
        "replan_required"
    ]
    assert case["characterized_legacy_path"]["replan_required"] is False
