from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopx.cli_commands.post_writeback import (
    dispatch_committed_cli_post_writeback_hooks,
)
from loopx.control_plane.capability_hooks import (
    POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
    PostWritebackHookRegistration,
)
from loopx.control_plane.post_writeback_composition_retry import (
    POST_WRITEBACK_COMPOSITION_RETRY_RECEIPT_SCHEMA_VERSION,
    append_composition_retry_receipt,
    build_composition_retry_receipt,
    composition_retry_receipt_id,
    composition_retry_receipt_log_path,
    composition_retry_receipt_ref,
    pending_composition_retry_receipts,
    settle_composition_retry_receipt,
)


def _write_registry(tmp_path: Path) -> tuple[Path, Path]:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(exist_ok=True)
    registry_path = tmp_path / "registry.global.json"
    registry_path.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime_root),
                "goals": [{"id": "goal-1"}],
            }
        ),
        encoding="utf-8",
    )
    return registry_path, runtime_root


def _identity() -> dict[str, str]:
    return {
        "agent_id": "agent-1",
        "todo_id": "todo-1",
        "turn_instance_id": "turn-1",
        "effect_id": "goal-1:agent-1:todo-1:turn-1",
    }


def _hook(
    *, producer_calls: list[int] | None = None
) -> PostWritebackHookRegistration:
    def producer(value: object) -> dict[str, object]:
        if producer_calls is not None:
            producer_calls.append(1)
        assert isinstance(value, dict)
        receipt = value["receipt"]
        assert isinstance(receipt, dict)
        return {
            "schema_version": POST_WRITEBACK_HOOK_RESULT_SCHEMA_VERSION,
            "hook_id": "periodic_report.stage_completion",
            "capability_id": "periodic-report",
            "phase": "post_writeback",
            "status": "intent",
            "intent": {
                "schema_version": "loopx_capability_intent_v0",
                "intent_kind": "periodic_report.trigger_evaluation",
                "idempotency_key": "periodic-report:stage-123",
                "source_receipt_id": receipt["event_id"],
                "payload": {"stage_identity": "stage-123"},
                "requested_write_scope": [],
            },
        }

    return PostWritebackHookRegistration(
        hook_id="periodic_report.stage_completion",
        capability_id="periodic-report",
        event_kinds=("todo_complete",),
        intent_kinds=("periodic_report.trigger_evaluation",),
        requested_read_scope=("stage_completion",),
        producer=producer,
    )


def _stage_projection() -> dict[str, object]:
    return {
        "stage_completion": {
            "schema_version": "periodic_report_stage_completion_receipt_v0",
            "stage_identity": "stage-123",
        }
    }


def _dispatch(
    registry_path: Path,
    *,
    hooks: tuple[PostWritebackHookRegistration, ...],
    projection_builder: Any,
) -> dict[str, Any]:
    return dispatch_committed_cli_post_writeback_hooks(
        payload={"ok": True, "completed": True},
        registry_path=registry_path,
        runtime_root_arg=None,
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="2026-09-06T00:00:00Z",
        committed_at="2026-09-06T00:00:00Z",
        hooks=hooks,
        projection_builder=projection_builder,
    )


def _journal_rows(runtime_root: Path) -> list[dict[str, Any]]:
    journal_path = composition_retry_receipt_log_path(runtime_root, "goal-1")
    return [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_failed_projection_preserves_actionable_hook_identity(
    tmp_path: Path,
) -> None:
    """Acceptance 1: the failed projection keeps its concrete identity."""

    registry_path, runtime_root = _write_registry(tmp_path)

    def failing_builder(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("transient projection failure")

    result = _dispatch(
        registry_path, hooks=(_hook(),), projection_builder=failing_builder
    )

    assert result["registered_count"] == 1
    assert result["intent_count"] == 0
    assert result["primary_writeback_preserved"] is True
    assert result["external_writes_performed"] is False
    (failure,) = result["failures"]
    assert failure["hook_id"] == "periodic_report.stage_completion"
    assert failure["capability_id"] == "periodic-report"
    assert failure["error_code"] == "source_projection_failed"
    assert failure["durable_receipt_ref"].startswith(
        "post-writeback-composition:pwcr_"
    )

    pending = pending_composition_retry_receipts(runtime_root, "goal-1")
    (receipt,) = pending
    assert receipt["schema_version"] == (
        POST_WRITEBACK_COMPOSITION_RETRY_RECEIPT_SCHEMA_VERSION
    )
    assert receipt["status"] == "retryable"
    assert receipt["error_code"] == "source_projection_failed"
    assert receipt["event_kind"] == "todo_complete"
    assert receipt["identity"]["effect_id"] == "goal-1:agent-1:todo-1:turn-1"
    assert receipt["identity"]["todo_id"] == "todo-1"
    assert receipt["state_version"] == "2026-09-06T00:00:00Z"
    assert receipt["committed_at"] == "2026-09-06T00:00:00Z"
    assert receipt["hooks"] == [
        {
            "hook_id": "periodic_report.stage_completion",
            "capability_id": "periodic-report",
        }
    ]
    assert receipt["primary_writeback_preserved"] is True
    assert receipt["external_writes_performed"] is False


def test_replay_after_transient_recovery_projects_once_and_settles_receipt(
    tmp_path: Path,
) -> None:
    """Acceptance 2: recovery replays the projection once and settles the receipt."""

    registry_path, runtime_root = _write_registry(tmp_path)
    projection_calls: list[int] = []
    producer_calls: list[int] = []

    def flaky_builder(**_kwargs: object) -> dict[str, object]:
        projection_calls.append(1)
        if len(projection_calls) == 1:
            raise RuntimeError("transient projection failure")
        return _stage_projection()

    hooks = (_hook(producer_calls=producer_calls),)

    failed = _dispatch(
        registry_path, hooks=hooks, projection_builder=flaky_builder
    )
    assert failed["failures"][0]["error_code"] == "source_projection_failed"
    assert [receipt["status"] for receipt in pending_composition_retry_receipts(runtime_root, "goal-1")] == ["retryable"]

    recovered = _dispatch(
        registry_path, hooks=hooks, projection_builder=flaky_builder
    )
    assert recovered["failures"] == []
    assert recovered["intent_count"] == 1
    assert len(producer_calls) == 1
    assert len(projection_calls) == 2
    assert pending_composition_retry_receipts(runtime_root, "goal-1") == []
    rows = _journal_rows(runtime_root)
    assert [row["status"] for row in rows if row["receipt_id"] == rows[-1]["receipt_id"]][-1] == "settled"

    replayed = _dispatch(
        registry_path, hooks=hooks, projection_builder=flaky_builder
    )
    assert replayed["intent_count"] == 1
    assert replayed["replayed_hooks"] == ["periodic_report.stage_completion"]
    assert len(producer_calls) == 1
    assert len(projection_calls) == 3
    assert pending_composition_retry_receipts(runtime_root, "goal-1") == []
    settled_ids = {
        row["receipt_id"] for row in _journal_rows(runtime_root)
    }
    assert len(settled_ids) == 1


def test_composition_replay_keeps_primary_writeback_idempotent(
    tmp_path: Path,
) -> None:
    """Acceptance 3: replaying the primary writeback never repeats its effect."""

    registry_path, runtime_root = _write_registry(tmp_path)
    primary_effects: list[str] = ["goal-1:agent-1:todo-1:turn-1"]
    projection_calls: list[int] = []
    producer_calls: list[int] = []

    def flaky_builder(**_kwargs: object) -> dict[str, object]:
        projection_calls.append(1)
        if len(projection_calls) <= 2:
            raise RuntimeError("transient projection failure")
        return _stage_projection()

    hooks = (_hook(producer_calls=producer_calls),)
    first_failure = _dispatch(
        registry_path, hooks=hooks, projection_builder=flaky_builder
    )
    second_failure = _dispatch(
        registry_path, hooks=hooks, projection_builder=flaky_builder
    )
    recovered = _dispatch(
        registry_path, hooks=hooks, projection_builder=flaky_builder
    )

    for result in (first_failure, second_failure, recovered):
        assert result["primary_writeback_preserved"] is True
        assert result["external_writes_performed"] is False
    assert primary_effects == ["goal-1:agent-1:todo-1:turn-1"]
    assert len(producer_calls) == 1

    rows = _journal_rows(runtime_root)
    assert len({row["receipt_id"] for row in rows}) == 1
    statuses = [row["status"] for row in rows]
    assert statuses == ["retryable", "retryable", "settled"]
    assert pending_composition_retry_receipts(runtime_root, "goal-1") == []


def test_composition_retry_receipt_id_binds_primary_writeback_identity() -> None:
    base = composition_retry_receipt_id(
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-2",
    )
    assert base.startswith("pwcr_")
    assert base == composition_retry_receipt_id(
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-2",
    )
    assert base != composition_retry_receipt_id(
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-3",
    )
    assert base != composition_retry_receipt_id(
        goal_id="goal-2",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-2",
    )
    assert composition_retry_receipt_ref(base) == (
        f"post-writeback-composition:{base}"
    )


def test_composition_retry_journal_append_is_idempotent_and_terminal(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "goals" / "goal-1" / (
        "post_writeback_hooks"
    ) / "composition-retry-receipts.jsonl"
    receipt = build_composition_retry_receipt(
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-2",
        committed_at="2026-09-06T00:00:00Z",
        hook_identities=[
            {"hook_id": "periodic_report.stage_completion", "capability_id": "periodic-report"}
        ],
        error_code="source_projection_failed",
    )

    appended_first, appended_flag_first = append_composition_retry_receipt(
        journal_path, receipt
    )
    appended_again, appended_flag_again = append_composition_retry_receipt(
        journal_path, receipt
    )
    assert appended_flag_first is True
    assert appended_flag_again is True

    settled, settled_flag = settle_composition_retry_receipt(
        journal_path,
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-2",
        committed_at="2026-09-06T00:00:00Z",
        hook_identities=[
            {"hook_id": "periodic_report.stage_completion", "capability_id": "periodic-report"}
        ],
    )
    assert settled_flag is True
    assert settled["status"] == "settled"
    assert settled["error_code"] is None

    regressed, regressed_flag = append_composition_retry_receipt(
        journal_path, receipt
    )
    assert regressed_flag is False
    assert regressed["status"] == "settled"
    rows = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["status"] for row in rows] == ["retryable", "retryable", "settled"]

    resettle, resettle_flag = settle_composition_retry_receipt(
        journal_path,
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-2",
        committed_at="2026-09-06T00:00:00Z",
        hook_identities=[],
    )
    assert resettle_flag is False
    assert resettle["status"] == "settled"
    assert len(rows) == 3


def test_settle_without_pending_receipt_is_a_noop(tmp_path: Path) -> None:
    journal_path = composition_retry_receipt_log_path(tmp_path, "goal-1")
    settled, appended = settle_composition_retry_receipt(
        journal_path,
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-2",
        committed_at="2026-09-06T00:00:00Z",
        hook_identities=[],
    )
    assert appended is False
    assert settled == {}
    assert not journal_path.exists()


def test_pending_receipts_skip_foreign_and_malformed_rows(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path
    journal_path = composition_retry_receipt_log_path(runtime_root, "goal-1")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    pending_receipt = build_composition_retry_receipt(
        goal_id="goal-1",
        event_kind="todo_complete",
        identity=_identity(),
        state_version="vision-revision-2",
        committed_at="2026-09-06T00:00:00Z",
        hook_identities=[{"hook_id": "h.one", "capability_id": "cap-one"}],
        error_code="source_projection_failed",
    )
    journal_path.write_text(
        "\n".join(
            [
                "not-json",
                json.dumps({"schema_version": "unrelated_v0"}),
                json.dumps(pending_receipt),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    pending = pending_composition_retry_receipts(runtime_root, "goal-1")
    assert [receipt["receipt_id"] for receipt in pending] == [
        pending_receipt["receipt_id"]
    ]
