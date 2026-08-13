"""Write-time gate: maintenance writebacks are rejected while replan is due."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.status.autonomous_replan_projection import (
    AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD,
)
from loopx.state_refresh import (
    reject_maintenance_writeback_during_open_replan,
    refresh_state_run,
)


GOAL_ID = "replan-gate-fixture"
AGENT_ID = "codex-replan-gate-agent"
STATE_TEXT = "# Active Goal State\n"


def _durable_runs(count: int) -> list[dict]:
    return [
        {
            "classification": "source_audit_progress",
            "generated_at": f"2026-08-13T00:{index:02d}:00+00:00",
            "agent_id": AGENT_ID,
            "progress_scope": "agent_lane",
            "delivery_outcome": "surface_only",
        }
        for index in reversed(range(count))
    ]


def _call_gate(
    *,
    runs: list[dict],
    classification: str = "source_audit_progress",
    vision_unchanged_reason: str | None = "无新攻击面，审计维持",
    repair_delta_kinds: list[str] | None = None,
    autonomous_replan_recorded: bool = False,
) -> None:
    reject_maintenance_writeback_during_open_replan(
        classification=classification,
        vision_unchanged_reason=vision_unchanged_reason,
        repair_delta_kinds=repair_delta_kinds,
        autonomous_replan_recorded=autonomous_replan_recorded,
        newest_first_runs=runs,
        state_text=STATE_TEXT,
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
    )


def test_maintenance_writeback_rejected_when_replan_due() -> None:
    with pytest.raises(ValueError) as exc:
        _call_gate(runs=_durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD))
    message = str(exc.value)
    assert "autonomous replan obligation" in message
    assert "source_audit_progress" in message
    assert "evidence-log" in message
    assert "--autonomous-replan-recorded" in message


def test_maintenance_writeback_rejected_even_without_unchanged_reason() -> None:
    with pytest.raises(ValueError):
        _call_gate(
            runs=_durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD),
            vision_unchanged_reason=None,
        )


def test_ack_writeback_allowed_under_open_obligation() -> None:
    _call_gate(
        runs=_durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD),
        autonomous_replan_recorded=True,
    )


def test_repair_delta_writeback_allowed_under_open_obligation() -> None:
    _call_gate(
        runs=_durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD),
        repair_delta_kinds=["runnable_todo_set"],
    )


def test_material_classification_allowed_under_open_obligation() -> None:
    _call_gate(
        runs=_durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD),
        classification="validated_progress",
        vision_unchanged_reason=None,
    )


def test_writeback_allowed_when_replan_not_due() -> None:
    _call_gate(runs=_durable_runs(5))


def test_refresh_state_run_rejects_maintenance_writeback(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = (
        project
        / ".codex"
        / "goals"
        / GOAL_ID
        / "ACTIVE_GOAL_STATE.md"
    )
    state.parent.mkdir(parents=True)
    state.write_text(STATE_TEXT, encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state.relative_to(project)),
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime_root = tmp_path / "runtime"
    runs_index = (
        runtime_root
        / "goals"
        / GOAL_ID
        / "runs"
        / "index.jsonl"
    )
    runs_index.parent.mkdir(parents=True)
    with runs_index.open("w", encoding="utf-8") as handle:
        for run in _durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD):
            handle.write(json.dumps(run) + "\n")

    with pytest.raises(ValueError) as exc:
        refresh_state_run(
            registry_path=registry_path,
            runtime_root_override=str(runtime_root),
            goal_id=GOAL_ID,
            project=project,
            state_file=None,
            classification="source_audit_progress",
            recommended_action="Observe the fixture.",
            delivery_batch_scale="single_surface",
            delivery_outcome="surface_only",
            agent_id=AGENT_ID,
            vision_unchanged_reason="无新攻击面，审计维持",
            dry_run=False,
            sync_global=False,
        )
    message = str(exc.value)
    assert "--autonomous-replan-recorded" in message
    assert "evidence-log" in message
