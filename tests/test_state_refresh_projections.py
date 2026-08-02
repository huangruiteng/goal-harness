from pathlib import Path

from loopx import state_refresh


def test_refresh_output_projections_preserve_optional_run_contracts() -> None:
    delta_contract = {"schema_version": "repair_delta_contract_v0", "delta_present": True}
    agent_vision = {
        "schema_version": "goal_vision_v0",
        "agent_id": "quality-agent",
        "state": "vision_active",
        "vision_patch": {"acceptance_summary": "Keep simplification measurable."},
        "todo_delta": ["Simplify the projection owner."],
        "vision_budget": {"status": "within_budget"},
        "path_delta": {"changed": ["projection assembly"]},
        "validation": {"budget_checked": True},
    }
    record = {
        "generated_at": "2026-07-31T00:00:00+00:00",
        "goal_id": "projection-fixture",
        "classification": "validated_progress",
        "recommended_action": "continue the measured simplification",
        "recommended_action_source": "explicit_arg",
        "health_check": "state_file 1/1",
        "state": {
            "path": "/ignored/project/state.md",
            "sha256_16": "0123456789abcdef",
            "frontmatter": {"updated_at": "2026-07-30T23:59:00+00:00", "status": "active"},
            "next_action": ["continue"],
        },
        "runtime_projection_route": {"status": "resolved", "route_id": "route-1"},
        "delivery_batch_scale": "single_surface",
        "delivery_outcome": "outcome_progress",
        "delivery_workspace": {"workspace_kind": "independent_git_worktree"},
        "autonomous_replan_ack": {
            "recorded": True,
            "requested": True,
            "requested_classification": "repair_completed",
            "delta_contract": delta_contract,
        },
        "agent_vision": agent_vision,
        "vision_checkpoint": {"decision": "patched", "satisfied": True},
        "progress_scope": "agent_lane",
        "agent_id": "quality-agent",
        "agent_lane": "quality",
        "active_state_next_action_update": {"updated": True},
    }

    index_record, payload = state_refresh._build_state_refresh_output_projections(
        record=record,
        registry_path=Path("/registry.json"),
        runtime_root=Path("/runtime"),
        project=Path("/project"),
        json_path=Path("/runtime/run.json"),
        markdown_path=Path("/runtime/run.md"),
        index_path=Path("/runtime/index.jsonl"),
        dry_run=False,
        autonomous_replan_recorded_requested=True,
    )

    assert index_record["state"] == {
        "sha256_16": "0123456789abcdef",
        "frontmatter": {"updated_at": "2026-07-30T23:59:00+00:00"},
    }
    assert index_record["requested_classification"] == "repair_completed"
    assert index_record["agent_vision"] == {
        key: agent_vision[key]
        for key in (
            "schema_version",
            "agent_id",
            "state",
            "vision_patch",
            "todo_delta",
            "vision_budget",
            "path_delta",
        )
    }
    assert "validation" not in index_record["agent_vision"]
    for field in (
        "delivery_batch_scale",
        "delivery_outcome",
        "delivery_workspace",
        "autonomous_replan_ack",
        "vision_checkpoint",
        "progress_scope",
        "agent_id",
        "agent_lane",
    ):
        assert index_record[field] == record[field]

    assert payload["appended"] is True
    assert payload["autonomous_replan_recorded"] is True
    assert payload["autonomous_replan_recorded_requested"] is True
    assert payload["repair_delta_contract"] is delta_contract
    assert payload["active_state_next_action_update"] == {"updated": True}
    assert payload["agent_vision"] is agent_vision
    assert payload["state"] is record["state"]
