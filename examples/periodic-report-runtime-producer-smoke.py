#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.periodic_report import build_periodic_report_run  # noqa: E402
from loopx.capabilities.periodic_report.runtime_producer import (  # noqa: E402
    build_periodic_report_runtime_trigger_decision,
)
from loopx.rollout_event_log import build_rollout_event  # noqa: E402


def main() -> None:
    events = [
        build_rollout_event(
            goal_id="sample-long-goal",
            event_kind="refresh_state",
            recorded_at="2026-08-22T09:00:00Z",
            status="appended",
            details={
                "stage_completion_schema": (
                    "periodic_report_stage_completion_receipt_v0"
                ),
                "stage_identity": "stage-sample-closed-vision",
                "closed_vision_revision": "2026-08-22T08:59:00Z",
                "frontier_identity": "frontier-sample-successor",
                "stage_transition": "successor_frontier_settled",
                "stage_acceptance": "validated",
                "stage_outcome_checkpoint_satisfied": True,
                "stage_durable_writeback_required": True,
            },
        )
    ]
    decision = build_periodic_report_runtime_trigger_decision(
        {
            "schema_version": "periodic_report_runtime_trigger_request_v0",
            "evaluated_at": "2026-08-24T12:00:00Z",
            "goal_id": "sample-long-goal",
            "profile": {"profile_id": "weekly_progress", "profile_version": "v1"},
            "trigger_policy": {
                "enabled_kinds": ["bounded_segment_milestone"],
                "minimum_interval_seconds": 0,
                "aggregation": {
                    "window_seconds": 604800,
                    "todo_completed_threshold": 3,
                    "promote_replan": False,
                    "stage_completion_required": True,
                },
            },
            "segment": {
                "segment_ref": "week-2026-w34",
                "start_at": "2026-08-18T12:00:00Z",
                "end_at": "2026-08-24T12:00:00Z",
                "remaining_todo_count": 8,
            },
        },
        rollout_events=events,
    )
    run = build_periodic_report_run(
        {
            "schema_version": "periodic_report_run_request_v0",
            "generated_at": "2026-08-24T12:05:00Z",
            "period_window": {
                "start_at": "2026-08-18T12:00:00Z",
                "end_at": "2026-08-24T12:00:00Z",
            },
            "profile": {"profile_id": "weekly_progress", "profile_version": "v1"},
            "trigger_receipt": decision,
            "source_snapshots": [
                {
                    "source_id": "project_progress",
                    "source_kind": "validated_project_progress",
                    "status": "complete",
                    "observed_at": "2026-08-24T12:00:00Z",
                    "snapshot_digest": "sha256:sample-progress",
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
    )
    assert decision["producer_receipt"]["status"] == "promoted"
    assert decision["producer_receipt"]["reason"] == (
        "authoritative_stage_completion_observed"
    )
    assert run["trigger_receipt"]["report_kind"] == "milestone_update"
    assert run["boundary"]["external_writes_performed"] is False
    print("periodic-report-runtime-producer-smoke: ok")


if __name__ == "__main__":
    main()
