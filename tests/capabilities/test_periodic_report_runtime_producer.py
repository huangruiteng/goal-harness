from __future__ import annotations

import json

import pytest

from loopx.capabilities.periodic_report import build_periodic_report_run
from loopx.capabilities.periodic_report.runtime_producer import (
    build_periodic_report_runtime_trigger_decision,
)
from loopx.cli import main
from loopx.rollout_event_log import append_rollout_event, build_rollout_event


def _request(*, threshold: int = 2, promote_replan: bool = True) -> dict[str, object]:
    return {
        "schema_version": "periodic_report_runtime_trigger_request_v0",
        "evaluated_at": "2026-08-24T12:00:00Z",
        "goal_id": "long-research",
        "profile": {
            "profile_id": "weekly_progress",
            "profile_version": "v1",
        },
        "trigger_policy": {
            "enabled_kinds": ["bounded_segment_milestone"],
            "minimum_interval_seconds": 0,
            "aggregation": {
                "window_seconds": 604800,
                "todo_completed_threshold": threshold,
                "promote_replan": promote_replan,
            },
        },
        "segment": {
            "segment_ref": "week-2026-w34",
            "start_at": "2026-08-18T12:00:00Z",
            "end_at": "2026-08-24T12:00:00Z",
            "remaining_todo_count": 12,
        },
    }


def _event(
    kind: str,
    *,
    event_at: str,
    todo_id: str | None = None,
    replan: bool = False,
) -> dict[str, object]:
    return build_rollout_event(
        goal_id="long-research",
        event_kind=kind,
        todo_id=todo_id,
        recorded_at=event_at,
        details={"autonomous_replan_recorded": replan},
    )


def _run_request(trigger: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "periodic_report_run_request_v0",
        "generated_at": "2026-08-24T12:05:00Z",
        "period_window": {
            "start_at": "2026-08-18T12:00:00Z",
            "end_at": "2026-08-24T12:00:00Z",
        },
        "profile": {
            "profile_id": "weekly_progress",
            "profile_version": "v1",
        },
        "trigger_receipt": trigger,
        "source_snapshots": [
            {
                "source_id": "project_progress",
                "source_kind": "validated_project_progress",
                "status": "complete",
                "observed_at": "2026-08-24T12:00:00Z",
                "snapshot_digest": "sha256:progress",
            }
        ],
        "artifact_receipt": {
            "artifact_id": "weekly_progress",
            "renderer_id": "markdown_v0",
            "renderer_kind": "markdown",
            "status": "pending",
        },
        "sink_receipts": [
            {
                "sink_id": "archive",
                "sink_kind": "resource_store",
                "sink_role": "archive",
                "status": "pending",
            },
            {
                "sink_id": "delivery",
                "sink_kind": "message_channel",
                "sink_role": "delivery",
                "status": "pending",
            },
        ],
    }


def test_todo_threshold_promotes_durable_window_and_composes_run() -> None:
    events = [
        _event("todo_complete", event_at="2026-08-20T09:00:00Z", todo_id="todo-a"),
        _event("todo_complete", event_at="2026-08-21T09:00:00Z", todo_id="todo-b"),
        _event("todo_complete", event_at="2026-08-22T09:00:00Z", todo_id="todo-c"),
    ]

    decision = build_periodic_report_runtime_trigger_decision(
        _request(), rollout_events=events
    )
    run = build_periodic_report_run(_run_request(decision))

    assert decision["eligible"] is True
    assert decision["selected_trigger_kind"] == "bounded_segment_milestone"
    assert decision["producer_receipt"]["reason"] == "todo_completion_threshold_reached"
    assert len(decision["producer_receipt"]["contributing_event_ids"]) == 2
    assert run["trigger_receipt"]["trigger_policy"]["aggregation"] == {
        "window_seconds": 604800,
        "promote_replan": True,
        "todo_completed_threshold": 2,
    }


def test_durable_replan_precedes_threshold_and_deduplicates_todos() -> None:
    duplicate = _event(
        "todo_complete", event_at="2026-08-20T09:00:00Z", todo_id="todo-a"
    )
    events = [
        duplicate,
        dict(duplicate),
        _event(
            "refresh_state",
            event_at="2026-08-21T10:00:00Z",
            replan=True,
        ),
    ]

    decision = build_periodic_report_runtime_trigger_decision(
        _request(threshold=4), rollout_events=events
    )

    assert decision["eligible"] is True
    assert decision["producer_receipt"]["transition"] == "replan_entered"
    assert decision["producer_receipt"]["todo_completed_count"] == 1
    assert decision["producer_receipt"]["replan_event_count"] == 1


def test_below_threshold_stays_non_reportable() -> None:
    decision = build_periodic_report_runtime_trigger_decision(
        _request(threshold=3, promote_replan=False),
        rollout_events=[
            _event(
                "todo_complete",
                event_at="2026-08-20T09:00:00Z",
                todo_id="todo-a",
            )
        ],
    )

    assert decision["eligible"] is False
    assert decision["producer_receipt"]["status"] == "not_promoted"
    assert decision["suppressed_triggers"][0]["trigger_kind"] == "state_refreshed"


def test_runtime_producer_rejects_unproven_public_boundary() -> None:
    event = _event(
        "todo_complete", event_at="2026-08-20T09:00:00Z", todo_id="todo-a"
    )
    event["boundary"]["raw_logs_recorded"] = True

    with pytest.raises(ValueError, match="public-safe event"):
        build_periodic_report_runtime_trigger_decision(
            _request(threshold=1), rollout_events=[event]
        )


def test_runtime_producer_cli_reads_durable_rollout_log(tmp_path, capsys) -> None:
    request_path = tmp_path / "request.json"
    event_log = tmp_path / "rollout-event-log.jsonl"
    request_path.write_text(json.dumps(_request(threshold=1)), encoding="utf-8")
    append_rollout_event(
        event_log,
        _event(
            "todo_complete",
            event_at="2026-08-20T09:00:00Z",
            todo_id="todo-a",
        ),
    )

    assert main(
        [
            "--format",
            "json",
            "periodic-report",
            "evaluate-runtime-trigger",
            "--request-json",
            str(request_path),
            "--rollout-events-jsonl",
            str(event_log),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["eligible"] is True
    assert payload["producer_receipt"]["status"] == "promoted"


def test_runtime_producer_cli_streams_large_history_before_bounded_window(
    tmp_path, capsys
) -> None:
    request_path = tmp_path / "request.json"
    event_log = tmp_path / "rollout-event-log.jsonl"
    request_path.write_text(json.dumps(_request(threshold=1)), encoding="utf-8")
    old_event = _event(
        "quota_should_run",
        event_at="2026-08-17T09:00:00Z",
    )
    current_event = _event(
        "todo_complete",
        event_at="2026-08-20T09:00:00Z",
        todo_id="todo-current",
    )
    rows = [
        json.dumps({**old_event, "event_id": f"old-{index}"})
        for index in range(4096)
    ]
    rows.append(json.dumps(current_event))
    event_log.write_text("\n".join(rows) + "\n", encoding="utf-8")

    assert main(
        [
            "--format",
            "json",
            "periodic-report",
            "evaluate-runtime-trigger",
            "--request-json",
            str(request_path),
            "--rollout-events-jsonl",
            str(event_log),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["eligible"] is True
    assert payload["producer_receipt"]["todo_completed_count"] == 1


def test_runtime_producer_rejects_relevant_window_over_capacity() -> None:
    event = _event(
        "todo_complete",
        event_at="2026-08-20T09:00:00Z",
        todo_id="todo-template",
    )
    events = (
        {
            **event,
            "event_id": f"current-{index}",
            "todo_id": f"todo-{index}",
        }
        for index in range(4097)
    )

    with pytest.raises(ValueError, match="4096 relevant window items"):
        build_periodic_report_runtime_trigger_decision(
            _request(threshold=1),
            rollout_events=events,
        )


def test_runtime_producer_cli_rejects_malformed_durable_row(tmp_path, capsys) -> None:
    request_path = tmp_path / "request.json"
    event_log = tmp_path / "rollout-event-log.jsonl"
    request_path.write_text(json.dumps(_request(threshold=1)), encoding="utf-8")
    event_log.write_text("{not-json}\n", encoding="utf-8")

    assert main(
        [
            "--format",
            "json",
            "periodic-report",
            "evaluate-runtime-trigger",
            "--request-json",
            str(request_path),
            "--rollout-events-jsonl",
            str(event_log),
        ]
    ) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == "rollout event log line 1 must contain valid JSON"
