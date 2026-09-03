from __future__ import annotations

from loopx.control_plane.todos.resume_condition import (
    evaluate_todo_resume_conditions,
)


def test_large_unrelated_rollout_history_does_not_expand_resume_request() -> None:
    noisy_events = [
        {
            "event_id": f"event-{index}",
            "event_kind": "refresh_state",
            "recorded_at": "2026-09-03T00:00:00Z",
            "details": {"payload": "x" * 2_000},
        }
        for index in range(2_000)
    ]
    merge_event = {
        "event_id": "event-merge-42",
        "event_kind": "pr_merge",
        "code_refs": {"pr_ref": "example/loopx#42", "unused": "x" * 2_000},
        "recorded_at": "2026-09-03T01:00:00Z",
        "details": {"unused": "x" * 2_000},
    }

    conditions = evaluate_todo_resume_conditions(
        [
            {
                "todo_id": "todo_wait_pr",
                "role": "agent",
                "status": "deferred",
                "task_class": "advancement_task",
                "task_repository": "git:github.com/example/loopx",
                "resume_when": "pr_merged:#42",
            }
        ],
        source_items=[],
        rollout_events=[*noisy_events, merge_event],
    )

    condition = conditions["todo_wait_pr"]
    assert condition["satisfied"] is True
    assert condition["matched_event_id"] == "event-merge-42"
    assert condition["matched_pr_ref"] == "example/loopx#42"
