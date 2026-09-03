from __future__ import annotations

from typing import Any

from loopx.control_plane.todos import resume_condition


def test_resume_evaluator_sends_only_matching_compact_merge_evidence(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_runtime(method: str, request: dict[str, Any]) -> dict[str, Any]:
        captured.update(request)
        assert method == "todo.resume_condition.evaluate"
        return {
            "schema_version": "todo_resume_evaluation_v0",
            "conditions": [],
        }

    monkeypatch.setattr(resume_condition, "effect_runtime_result", fake_runtime)
    huge = "x" * 3_000_000
    resume_condition.evaluate_todo_resume_conditions(
        [
            {
                "todo_id": "todo_waiting",
                "status": "deferred",
                "resume_when": "pr_merged:owner/repo#42",
            }
        ],
        source_items=[],
        rollout_events=[
            {
                "event_id": "irrelevant",
                "event_kind": "todo_update",
                "details": huge,
            },
            {
                "event_id": "wrong-pr",
                "event_kind": "pr_merged",
                "code_refs": {"pr_ref": "owner/repo#41", "payload": huge},
                "details": huge,
            },
            {
                "event_id": "matching-pr",
                "event_kind": "pr_merged",
                "recorded_at": "2026-09-03T07:00:00Z",
                "code_refs": {"pr_ref": "owner/repo#42", "payload": huge},
                "details": huge,
            },
        ],
    )

    assert captured["rollout_events"] == [
        {
            "event_kind": "pr_merged",
            "event_id": "matching-pr",
            "recorded_at": "2026-09-03T07:00:00Z",
            "code_refs": {"pr_ref": "owner/repo#42"},
        }
    ]


def test_resume_evaluator_omits_rollout_history_without_pr_waits(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_runtime(method: str, request: dict[str, Any]) -> dict[str, Any]:
        captured.update(request)
        assert method == "todo.resume_condition.evaluate"
        return {
            "schema_version": "todo_resume_evaluation_v0",
            "conditions": [],
        }

    monkeypatch.setattr(resume_condition, "effect_runtime_result", fake_runtime)
    resume_condition.evaluate_todo_resume_conditions(
        [
            {
                "todo_id": "todo_waiting",
                "status": "deferred",
                "resume_when": "todo_done:todo_source",
            }
        ],
        source_items=[{"todo_id": "todo_source", "status": "done"}],
        rollout_events=[
            {
                "event_id": "large-history-row",
                "event_kind": "todo_update",
                "details": "x" * 3_000_000,
            }
        ],
    )

    assert captured["rollout_events"] == []


def test_resume_evaluator_retains_the_latest_bounded_matching_events(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_runtime(method: str, request: dict[str, Any]) -> dict[str, Any]:
        captured.update(request)
        assert method == "todo.resume_condition.evaluate"
        return {
            "schema_version": "todo_resume_evaluation_v0",
            "conditions": [],
        }

    monkeypatch.setattr(resume_condition, "effect_runtime_result", fake_runtime)
    events = [
        {
            "event_id": f"merge-{index}",
            "event_kind": "pr_merge",
            "pr_ref": "owner/repo#42",
        }
        for index in range(300)
    ]
    resume_condition.evaluate_todo_resume_conditions(
        [
            {
                "todo_id": "todo_waiting",
                "status": "deferred",
                "resume_when": "pr_merged:owner/repo#42",
            }
        ],
        source_items=[],
        rollout_events=events,
    )

    compacted = captured["rollout_events"]
    assert len(compacted) == 256
    assert compacted[0]["event_id"] == "merge-44"
    assert compacted[-1]["event_id"] == "merge-299"
