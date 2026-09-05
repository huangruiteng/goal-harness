"""Real CLI recovery: missing checkpoint must not require another work Turn."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from loopx.state_refresh import render_state_refresh_markdown

from tests.control_plane.test_quota_settlement_cli import (
    AGENT_ID,
    GOAL_ID,
    TODO_ID,
    TURN_ID,
    _run_cli,
    _write_fixture,
    _spend_run_count,
)


def test_replay_markdown_exposes_saved_checkpoint_and_recovery():
    rendered = render_state_refresh_markdown({
        "ok": True,
        "refresh_recovery": {"decision": "replay", "reason": "original_writeback_preserved"},
        "vision_checkpoint": {"decision": "missing_required", "satisfied": False},
    })
    assert "missing_required" in rendered
    assert "same refresh command and Turn" in rendered
    assert "None" not in rendered


@pytest.mark.parametrize("decision", ["unchanged", "patch"])
def test_same_turn_checkpoint_supplement_is_idempotent(tmp_path: Path, decision: str):
    project, runtime, registry = _write_fixture(tmp_path)
    rc, initial = _run_cli(
        registry,
        runtime,
        "refresh-state",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
        "--vision-summary",
        "Validate the scoped change.",
        "--vision-acceptance",
        "Focused validation passes.",
        "--no-global-sync",
        "--suppress-external-sinks",
        cwd=project,
    )
    assert rc == 0, initial
    binding = (
        "--agent-id",
        AGENT_ID,
        "--todo-id",
        TODO_ID,
        "--turn-instance-id",
        TURN_ID,
    )
    rc, guard = _run_cli(
        registry,
        runtime,
        "quota",
        "should-run",
        "--codex-app",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--scan-path",
        str(project),
        cwd=project,
    )
    assert rc == 0, guard
    args = (
        "refresh-state",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--classification",
        "validated_change",
        "--delivery-batch-scale",
        "implementation",
        "--delivery-outcome",
        "outcome_progress",
        "--no-global-sync",
        "--suppress-external-sinks",
    )
    rc, first = _run_cli(registry, runtime, *args, cwd=project)
    assert rc == 0, first
    assert first["vision_checkpoint"]["decision"] == "missing_required"
    original_bytes = Path(first["json_path"]).read_bytes()
    supplement = (
        (
            "--vision-unchanged-reason",
            "The accepted scope and evidence remain applicable.",
        )
        if decision == "unchanged"
        else ("--vision-last-patch", "Validation evidence checked.")
    )
    index = runtime / "goals" / GOAL_ID / "runs" / "index.jsonl"
    before_preview = index.read_bytes()
    rc, preview = _run_cli(
        registry, runtime, *args, *supplement, "--dry-run", cwd=tmp_path
    )
    assert rc == 0, preview
    assert index.read_bytes() == before_preview
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: _run_cli(registry, runtime, *args, *supplement, cwd=tmp_path),
                range(2),
            )
        )
    assert all(rc == 0 for rc, _ in results), results
    assert sum(result["appended"] for _, result in results) == 1
    repaired = next(result for _, result in results if result["appended"])
    assert repaired["appended"] is True
    assert repaired["refresh_recovery"]["decision"] == "supplement_checkpoint"
    assert repaired["vision_checkpoint"]["satisfied"] is True
    assert repaired["settlement_identity"] == first["settlement_identity"]
    assert repaired["delivery_workspace"] == first["delivery_workspace"]
    assert Path(first["json_path"]).read_bytes() == original_bytes
    rc, replay = _run_cli(registry, runtime, *args, *supplement, cwd=tmp_path)
    assert rc == 0, replay
    assert replay["appended"] is False
    assert replay["idempotent_replay"] is True
    assert replay["vision_checkpoint"]["satisfied"] is True
    rc, conflict = _run_cli(
        registry,
        runtime,
        *args,
        "--vision-unchanged-reason",
        "A different checkpoint decision.",
        cwd=project,
    )
    assert rc == 1, conflict
    assert conflict["appended"] is False
    assert (
        conflict["refresh_recovery"]["reason"] == "committed_vision_decision_conflict"
    )
    assert _spend_run_count(runtime) == 0
    spend = (
        "quota",
        "spend-slot",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--source",
        "heartbeat",
        "--slots",
        "1",
        "--execute",
        "--scan-path",
        str(project),
    )
    for _ in range(2):
        rc, result = _run_cli(registry, runtime, *spend, cwd=project)
        assert rc == 0, result
    assert _spend_run_count(runtime) == 1


def test_invalid_supplement_leaves_original_writeback_intact(tmp_path: Path):
    project, runtime, registry = _write_fixture(tmp_path)
    binding = (
        "--agent-id",
        AGENT_ID,
        "--todo-id",
        TODO_ID,
        "--turn-instance-id",
        TURN_ID,
    )
    rc, guard = _run_cli(
        registry,
        runtime,
        "quota",
        "should-run",
        "--codex-app",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--scan-path",
        str(project),
        cwd=project,
    )
    assert rc == 0, guard
    args = (
        "refresh-state",
        "--goal-id",
        GOAL_ID,
        *binding,
        "--delivery-outcome",
        "outcome_progress",
        "--no-global-sync",
        "--suppress-external-sinks",
    )
    rc, first = _run_cli(registry, runtime, *args, cwd=project)
    assert rc == 0, first
    index = runtime / "goals" / GOAL_ID / "runs" / "index.jsonl"
    before = index.read_bytes()
    rc, rejected = _run_cli(
        registry,
        runtime,
        *args,
        "--vision-unchanged-reason",
        "No baseline exists.",
        cwd=project,
    )
    assert rc == 1, rejected
    assert "existing vision" in rejected["error"]
    assert index.read_bytes() == before
    rc, bad_patch = _run_cli(
        registry, runtime, *args, "--vision-summary", "x" * 421, cwd=project
    )
    assert rc == 1, bad_patch
    assert index.read_bytes() == before
    assert _spend_run_count(runtime) == 0
