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


def test_no_followup_claim_requires_validated_terminal_closure() -> None:
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
        "no validated terminal todo no-follow-up closure exists"
    )

    summary = {
        "schema_version": "todo_summary_v0",
        "source_section": "Agent Todo",
        "total_count": 1,
        "open_count": 0,
        "done_count": 1,
        "deferred_count": 0,
        "items": [item],
        "monitor_open_items": [],
        "deferred_items": [],
        "deferred_resume_candidates": [],
        "monitor_due_count": 0,
        "monitor_schedule_gap_count": 0,
        "source_proof": {
            "schema_version": "todo_source_proof_v0",
            "role": "agent",
            "item_count": 1,
            "derived": True,
        },
        "terminal_closure_proof": {
            "schema_version": "todo_terminal_closure_proof_v0",
            "role": "agent",
            "source_section": "Agent Todo",
            "item_count": 1,
            "all_todos_done": True,
            "monitor_open_count": 0,
            "successor_gap_count": 0,
            "route_replan_count": 0,
            "no_followup_count": 1,
            "derived": True,
        },
        "closure_intent": {
            "schema_version": "todo_closure_intent_v0",
            "kind": "no_followup",
            "derived": True,
            "count": 1,
        },
    }
    accepted, evidence, rejected = _validate(
        "no_followup",
        items=(item,),
        summary=summary,
    )

    assert accepted == ["no_followup"]
    assert evidence[0]["todo_ids"] == [item["todo_id"]]
    assert rejected == []
