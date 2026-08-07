from datetime import datetime, timezone

from loopx.control_plane.work_items.repair_delta import (
    repair_delta_kinds_have_accountable_progress,
    validate_repair_delta_claims,
)


def _summary(*items: dict) -> dict:
    return {"items": list(items)}


def _validate(
    kind: str,
    *,
    items: tuple[dict, ...],
    advancement_policy: str = "as_needed",
    summary: dict | None = None,
) -> tuple[list[str], list[dict], list[dict]]:
    return validate_repair_delta_claims(
        [kind],
        agent_todo_summary=summary or _summary(*items),
        agent_id="quality-agent",
        advancement_policy=advancement_policy,
        next_action_changed=False,
        vision_patch_written=False,
        observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


def test_watch_only_replan_delta_is_not_accountable_progress() -> None:
    assert repair_delta_kinds_have_accountable_progress(
        ["user_gate", "monitor_target", "active_state_next_action"]
    ) is False
    assert repair_delta_kinds_have_accountable_progress(
        ["active_state_next_action", "runnable_todo_set"]
    ) is True


def test_runnable_todo_claim_requires_scoped_advancement() -> None:
    accepted, evidence, rejected = _validate(
        "runnable_todo_set",
        items=(
            {
                "todo_id": "todo_123456789abc",
                "status": "open",
                "task_class": "advancement_task",
                "claimed_by": "other-agent",
            },
            {
                "todo_id": "todo_deferred12345",
                "status": "open",
                "task_class": "advancement_task",
                "claimed_by": "quality-agent",
                "resume_when": "todo_done:todo_dependency123",
                "resume_ready": False,
            },
        ),
    )

    assert accepted == []
    assert evidence == []
    assert rejected[0]["reason"] == "no scoped open advancement todo exists"


def test_runnable_todo_claim_records_todo_evidence() -> None:
    accepted, evidence, rejected = _validate(
        "runnable_todo_set",
        items=(
            {
                "todo_id": "todo_123456789abc",
                "status": "open",
                "task_class": "advancement_task",
                "claimed_by": "quality-agent",
            },
        ),
    )

    assert accepted == ["runnable_todo_set"]
    assert evidence[0]["todo_ids"] == ["todo_123456789abc"]
    assert rejected == []


def test_runnable_todo_claim_rejects_excluded_agent() -> None:
    accepted, evidence, rejected = _validate(
        "runnable_todo_set",
        items=(
            {
                "todo_id": "todo_123456789abc",
                "status": "open",
                "task_class": "advancement_task",
                "excluded_agents": ["quality-agent"],
            },
        ),
    )

    assert accepted == []
    assert evidence == []
    assert rejected[0]["reason"] == "no scoped open advancement todo exists"


def test_runnable_todo_claim_rejects_removed_continuation_policy() -> None:
    accepted, evidence, rejected = _validate(
        "runnable_todo_set",
        items=(
            {
                "todo_id": "todo_123456789abc",
                "status": "open",
                "task_class": "advancement_task",
                "removed_continuation_policy": "review_handoff",
            },
        ),
    )

    assert accepted == []
    assert evidence == []
    assert rejected[0]["reason"] == "no scoped open advancement todo exists"


def test_watch_claim_requires_bounded_schedule() -> None:
    accepted, evidence, rejected = _validate(
        "watch_lane_continuation",
        items=(
            {
                "todo_id": "todo_123456789abc",
                "status": "open",
                "task_class": "continuous_monitor",
                "claimed_by": "quality-agent",
                "target_key": "review",
                "cadence": "30m",
                "next_due_at": "2026-08-01T13:00:00Z",
            },
        ),
    )

    assert accepted == []
    assert evidence == []
    assert "expiry or unresolved resume condition" in rejected[0]["reason"]


def test_watch_claim_requires_non_repeating_vision_and_records_evidence() -> None:
    monitor = {
        "todo_id": "todo_123456789abc",
        "status": "open",
        "task_class": "continuous_monitor",
        "claimed_by": "quality-agent",
        "target_key": "review",
        "cadence": "30m",
        "next_due_at": "2026-08-01T13:00:00Z",
        "expires_at": "2026-08-02T13:00:00Z",
    }

    accepted, evidence, rejected = _validate(
        "watch_lane_continuation",
        items=(monitor,),
    )
    repeat_accepted, _, repeat_rejected = _validate(
        "watch_lane_continuation",
        items=(monitor,),
        advancement_policy="repeat_until_closed",
    )

    assert accepted == ["watch_lane_continuation"]
    assert evidence[0]["todo_ids"] == ["todo_123456789abc"]
    assert rejected == []
    assert repeat_accepted == []
    assert repeat_rejected[0]["reason"] == (
        "repeat_until_closed vision requires advancement"
    )


def test_watch_claim_rejects_malformed_or_expired_schedule() -> None:
    for monitor in (
        {
            "cadence": "whenever",
            "next_due_at": "not-a-time",
            "expires_at": "also-not-a-time",
        },
        {
            "cadence": "30m",
            "next_due_at": "2020-01-01T00:00:00Z",
            "expires_at": "2020-01-02T00:00:00Z",
        },
    ):
        accepted, evidence, rejected = _validate(
            "watch_lane_continuation",
            items=(
                {
                    "todo_id": "todo_123456789abc",
                    "status": "open",
                    "task_class": "continuous_monitor",
                    "claimed_by": "quality-agent",
                    "target_key": "review",
                    **monitor,
                },
            ),
        )

        assert accepted == []
        assert evidence == []
        assert rejected


def test_watch_claim_rejects_satisfied_resume_condition() -> None:
    accepted, evidence, rejected = _validate(
        "watch_lane_continuation",
        items=(
            {
                "todo_id": "todo_123456789abc",
                "status": "open",
                "task_class": "continuous_monitor",
                "claimed_by": "quality-agent",
                "target_key": "review",
                "cadence": "30m",
                "next_due_at": "2026-08-01T13:00:00Z",
                "resume_when": "todo_done:todo_dependency123",
                "resume_ready": True,
            },
        ),
    )

    assert accepted == []
    assert evidence == []
    assert rejected


def test_successor_claim_requires_real_scoped_transition() -> None:
    source = {
        "todo_id": "todo_source123456",
        "status": "done",
        "done": True,
        "task_class": "advancement_task",
    }
    accepted, evidence, rejected = _validate(
        "successor_or_supersede",
        items=(source,),
    )

    assert accepted == []
    assert evidence == []
    assert rejected[0]["reason"] == (
        "no completed todo links a scoped open advancement successor"
    )

    successor = {
        "todo_id": "todo_successor123",
        "status": "open",
        "task_class": "advancement_task",
        "claimed_by": "quality-agent",
    }
    source["successor_todo_ids"] = [successor["todo_id"]]
    accepted, evidence, rejected = _validate(
        "successor_or_supersede",
        items=(source, successor),
    )

    assert accepted == ["successor_or_supersede"]
    assert evidence[0]["todo_ids"] == [source["todo_id"], successor["todo_id"]]
    assert rejected == []


def test_no_followup_claim_requires_complete_source_and_local_closure() -> None:
    item = {
        "todo_id": "todo_source123456",
        "status": "done",
        "done": True,
        "task_class": "advancement_task",
        "action_kind": "finish_slice",
        "no_followup": True,
    }
    accepted, evidence, rejected = _validate("no_followup", items=(item,))

    assert accepted == []
    assert evidence == []
    assert rejected[0]["reason"] == (
        "no scoped completed todo has a validated local no-follow-up closure"
    )

    monitor = {
        "todo_id": "todo_monitor123456",
        "status": "open",
        "done": False,
        "task_class": "continuous_monitor",
        "claimed_by": "quality-agent",
    }
    summary = {
        "schema_version": "todo_summary_v0",
        "source_section": "Agent Todo",
        "total_count": 2,
        "open_count": 1,
        "done_count": 1,
        "deferred_count": 0,
        "items": [item, monitor],
        "monitor_open_items": [monitor],
        "deferred_items": [],
        "deferred_resume_candidates": [],
        "monitor_due_count": 1,
        "monitor_schedule_gap_count": 0,
        "source_proof": {
            "schema_version": "todo_source_proof_v0",
            "role": "agent",
            "item_count": 2,
            "derived": True,
        },
    }
    accepted, evidence, rejected = _validate(
        "no_followup",
        items=(item, monitor),
        summary=summary,
    )

    assert accepted == ["no_followup"]
    assert evidence[0]["todo_ids"] == [item["todo_id"]]
    assert rejected == []


def test_no_followup_claim_rejects_other_agent_or_replan_required_todo() -> None:
    items = (
        {
            "todo_id": "todo_otheragent12",
            "status": "done",
            "done": True,
            "task_class": "advancement_task",
            "claimed_by": "other-agent",
            "no_followup": True,
        },
        {
            "todo_id": "todo_replan123456",
            "status": "done",
            "done": True,
            "task_class": "advancement_task",
            "claimed_by": "quality-agent",
            "no_followup": True,
            "route_continuation_replan_required": True,
        },
    )
    summary = {
        "schema_version": "todo_summary_v0",
        "source_section": "Agent Todo",
        "total_count": 2,
        "open_count": 0,
        "done_count": 2,
        "deferred_count": 0,
        "items": list(items),
        "source_proof": {
            "schema_version": "todo_source_proof_v0",
            "role": "agent",
            "item_count": 2,
            "derived": True,
        },
    }

    accepted, evidence, rejected = _validate(
        "no_followup",
        items=items,
        summary=summary,
    )

    assert accepted == []
    assert evidence == []
    assert rejected[0]["reason"] == (
        "no scoped completed todo has a validated local no-follow-up closure"
    )


def test_no_followup_claim_uses_latest_scoped_local_closure() -> None:
    older = {
        "todo_id": "todo_older1234567",
        "status": "done",
        "done": True,
        "task_class": "advancement_task",
        "claimed_by": "quality-agent",
        "no_followup": True,
        "completed_at": "2026-07-01T00:00:00Z",
    }
    latest = {
        "todo_id": "todo_latest123456",
        "status": "done",
        "done": True,
        "task_class": "advancement_task",
        "claimed_by": "quality-agent",
        "no_followup": True,
        "completed_at": "2026-08-01T00:00:00Z",
    }
    summary = {
        "schema_version": "todo_summary_v0",
        "source_section": "Agent Todo",
        "total_count": 2,
        "open_count": 0,
        "done_count": 2,
        "deferred_count": 0,
        "items": [older, latest],
    }

    accepted, evidence, rejected = _validate(
        "no_followup",
        items=(older, latest),
        summary=summary,
    )

    assert accepted == ["no_followup"]
    assert evidence[0]["todo_ids"] == [latest["todo_id"]]
    assert rejected == []


def test_no_followup_claim_rejects_stale_older_local_closure() -> None:
    older_no_followup = {
        "todo_id": "todo_older1234567",
        "status": "done",
        "done": True,
        "task_class": "advancement_task",
        "claimed_by": "quality-agent",
        "no_followup": True,
        "completed_at": "2026-07-01T00:00:00Z",
    }
    latest_without_closure = {
        "todo_id": "todo_latest123456",
        "status": "done",
        "done": True,
        "task_class": "advancement_task",
        "claimed_by": "quality-agent",
        "completed_at": "2026-08-01T00:00:00Z",
    }
    summary = {
        "schema_version": "todo_summary_v0",
        "source_section": "Agent Todo",
        "total_count": 2,
        "open_count": 0,
        "done_count": 2,
        "deferred_count": 0,
        "items": [older_no_followup, latest_without_closure],
    }

    accepted, evidence, rejected = _validate(
        "no_followup",
        items=(older_no_followup, latest_without_closure),
        summary=summary,
    )

    assert accepted == []
    assert evidence == []
    assert rejected[0]["kind"] == "no_followup"
