from __future__ import annotations

import json
from pathlib import Path

from loopx.capabilities.periodic_report.pending_intent import (
    consume_pending_periodic_report_intent,
    pending_periodic_report_intents,
    periodic_report_pending_intent_interaction_hook,
)
from loopx.control_plane.capability_hooks import dispatch_interaction_projection_hooks
from loopx.control_plane.quota.live_decision import (
    _apply_pending_capability_intent_precedence,
)


GOAL_ID = "report-goal"
AGENT_ID = "report-agent"


def _intent() -> dict[str, object]:
    return {
        "schema_version": "loopx_capability_intent_v0",
        "intent_kind": "periodic_report.trigger_evaluation",
        "idempotency_key": "periodic-report:stage-example",
        "source_receipt_id": "pwr_example",
        "payload": {
            "schema_version": "periodic_report_trigger_evaluation_intent_v0",
            "stage_completion": {
                "schema_version": "periodic_report_stage_completion_receipt_v0",
                "stage_identity": "stage-example",
                "agent_id": AGENT_ID,
                "closed_vision_revision": "2026-08-30T09:00:00Z",
                "frontier_identity": "validated-goal-terminal",
                "transition": "goal_terminal",
                "completed_at": "2026-08-30T09:00:00Z",
                "acceptance": "validated",
                "outcome_checkpoint_satisfied": True,
                "durable_writeback_required": True,
                "evidence_refs": ["goal_terminal_state_v0"],
            },
            "profile_ref": {
                "profile_id": "weekly_progress",
                "profile_version": "v1",
                "profile_digest": "sha256:" + "1" * 64,
            },
            "trigger_policy": {
                "enabled_kinds": ["bounded_segment_milestone"],
                "minimum_interval_seconds": 0,
            },
            "generation_authorized": False,
            "external_delivery_authorized": False,
        },
        "requested_write_scope": [],
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    runtime = tmp_path / "runtime"
    state = project / "ACTIVE_GOAL_STATE.md"
    state.parent.mkdir(parents=True)
    state.write_text(
        """---
status: active
---

# Active Goal State

## User Todo

## Agent Todo

- [x] Finish the bounded analysis.
  <!-- loopx:todo todo_id=todo_finished status=done task_class=advancement_task claimed_by=report-agent evidence=validated-analysis-outcome updated_at=2026-08-30T09:00:00Z -->
""",
        encoding="utf-8",
    )
    registry = project / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(project),
                        "state_file": "ACTIVE_GOAL_STATE.md",
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sidecar_dir = runtime / "goals" / GOAL_ID / "post_writeback_hooks"
    sidecar_dir.mkdir(parents=True)
    sidecar = sidecar_dir / ("pwh_" + "a" * 64 + ".json")
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": "loopx_post_writeback_capability_hook_receipt_v0",
                "dispatch_id": sidecar.stem,
                "hook_id": "periodic_report.runtime_trigger",
                "capability_id": "periodic-report",
                "source_receipt_id": "pwr_example",
                "status": "intent_recorded",
                "intent": _intent(),
                "error_code": None,
                "attempt_count": 1,
                "recorded_at": "2026-08-30T09:00:01Z",
            }
        ),
        encoding="utf-8",
    )
    return registry, runtime


def test_pending_intent_projects_a_ts_validated_governed_action(tmp_path: Path) -> None:
    _registry, runtime = _fixture(tmp_path)

    dispatch = dispatch_interaction_projection_hooks(
        [
            periodic_report_pending_intent_interaction_hook(
                runtime_root=runtime, goal_id=GOAL_ID, agent_id=AGENT_ID
            )
        ]
    )

    projection = dispatch["projections"]["pending_capability_intent"]
    assert projection["state"] == "pending"
    assert projection["generation_authorized"] is True
    assert projection["external_delivery_authorized"] is False
    assert "consume-pending" in projection["command"]

    quiet = {
        "decision": "skip",
        "should_run": False,
        "state": "terminal_no_followup",
        "effective_action": "terminal_no_followup",
        "interaction_contract": {
            "mode": "terminal_no_followup",
            "agent_channel": {"must_attempt": False, "quiet_noop_allowed": True},
        },
    }
    _apply_pending_capability_intent_precedence(quiet, projection)
    assert quiet["effective_action"] == "governed_capability_intent"
    assert quiet["should_run"] is True
    assert quiet["interaction_contract"]["agent_channel"]["must_attempt"] is True
    assert quiet["interaction_contract"]["agent_channel"]["quiet_noop_allowed"] is False
    assert quiet["interaction_contract"]["cli_channel"]["next_cli_actions"] == [
        projection["command"]
    ]

    gated = {
        "decision": "skip",
        "should_run": False,
        "state": "operator_gate",
        "requires_user_action": True,
        "action_required": True,
        "open_count": 1,
        "interaction_contract": {
            "mode": "user_gate",
            "user_channel": {"action_required": True, "notify": "NOTIFY"},
            "agent_channel": {"must_attempt": False, "quiet_noop_allowed": True},
        },
    }
    _apply_pending_capability_intent_precedence(gated, projection)
    assert gated["requires_user_action"] is True
    assert gated["open_count"] == 1
    assert gated["interaction_contract"]["user_channel"] == {
        "action_required": True,
        "notify": "NOTIFY",
    }
    assert gated["interaction_contract"]["agent_channel"]["must_attempt"] is True


def test_consumption_is_local_and_exact_replay_does_not_duplicate_gate(
    tmp_path: Path,
) -> None:
    registry, runtime = _fixture(tmp_path)

    first = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    replay = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )

    assert first["status"] == "approval_pending"
    assert first["external_writes_performed"] is False
    assert first["content_checks"] == {
        "schema_version": "periodic_report_content_checks_v0",
        "document_normalized": True,
        "artifact_digests_verified": True,
        "html_self_contained": True,
        "matching_document_digest": True,
        "external_writes_performed": False,
    }
    assert Path(first["artifacts"]["html_path"]).is_file()
    assert Path(first["artifacts"]["markdown_path"]).is_file()
    assert replay["status"] == "no_pending_intent"
    assert pending_periodic_report_intents(
        runtime_root=runtime, goal_id=GOAL_ID, agent_id=AGENT_ID
    ) == []
    state = (registry.parent / "ACTIVE_GOAL_STATE.md").read_text(encoding="utf-8")
    assert state.count("approve_periodic_report_payload") == 1
    assert "Miaoda publication or group delivery" in state


def test_consumption_recovers_when_gate_precedes_receipt_write(tmp_path: Path) -> None:
    registry, runtime = _fixture(tmp_path)

    first = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )
    receipt_path = Path(first["artifacts"]["html_path"]).parent / "receipt.json"
    receipt_path.unlink()

    recovered = consume_pending_periodic_report_intent(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        execute=True,
    )

    assert recovered["status"] == "approval_pending"
    assert recovered["generation_receipt"] == first["generation_receipt"]
    state = (registry.parent / "ACTIVE_GOAL_STATE.md").read_text(encoding="utf-8")
    assert state.count("approve_periodic_report_payload") == 1


def test_cross_agent_or_malformed_intent_fails_closed(tmp_path: Path) -> None:
    _registry, runtime = _fixture(tmp_path)
    assert pending_periodic_report_intents(
        runtime_root=runtime, goal_id=GOAL_ID, agent_id="other-agent"
    ) == []
    sidecar = next(
        (runtime / "goals" / GOAL_ID / "post_writeback_hooks").glob("*.json")
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["intent"]["requested_write_scope"] = ["external_delivery"]
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    assert pending_periodic_report_intents(
        runtime_root=runtime, goal_id=GOAL_ID, agent_id=AGENT_ID
    ) == []
