from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import Event, Lock
from typing import Any

import pytest

from loopx.capabilities.periodic_report import incremental
from loopx.capabilities.periodic_report.incremental import (
    build_periodic_report_publication_candidate,
    commit_periodic_report_publication_cursor,
    periodic_report_incremental_baseline,
    read_periodic_report_publication_cursor,
    select_incremental_project_progress,
)
from loopx.capabilities.periodic_report.post_writeback_hook import (
    evaluate_periodic_report_trigger_evaluation_intent,
    periodic_report_post_writeback_hook,
)
from loopx.capabilities.periodic_report.project_progress_snapshot import (
    build_project_progress_snapshot_from_state,
)


GOAL_ID = "example-goal"
AGENT_ID = "example-agent"


def _item(
    source_ref: str,
    *,
    title: str,
    summary: str,
    content_kind: str = "outcome",
) -> dict[str, object]:
    return {
        "item_id": source_ref.replace(":", "_"),
        "title": title,
        "summary": summary,
        "content_kind": content_kind,
        "source_ref": source_ref,
        "completed_at": "2026-08-01T08:00:00Z",
    }


def _snapshot(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "periodic_report_project_progress_projection_v0",
        "goal_id": GOAL_ID,
        "observed_at": "2026-08-01T08:00:00Z",
        "language": "zh-CN",
        "items": items,
    }


def _trigger(trigger_id: str) -> dict[str, object]:
    return {
        "coalesced_trigger_ids": [trigger_id],
    }


def test_two_cycle_increment_reports_only_new_and_changed_facts(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    first = select_incremental_project_progress(
        _snapshot(
            [
                _item("todo:a", title="A completed", summary="A is done."),
                _item(
                    "todo:b",
                    title="B started",
                    summary="B is open.",
                    content_kind="next_action",
                ),
            ]
        ),
        cursor=None,
    )
    assert first is not None
    candidate_one = build_periodic_report_publication_candidate(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        generation_id="report_generation_first",
        trigger_receipt=_trigger("trigger_first"),
        facts=first["items"],
        baseline=None,
    )
    cursor_one = commit_periodic_report_publication_cursor(
        runtime_root=runtime,
        candidate=candidate_one,
        publication_id="goal-channel:first",
        delivered_at="2026-08-01T09:00:00Z",
        covered_until="2026-08-01T08:00:00Z",
    )
    replayed_cursor_one = commit_periodic_report_publication_cursor(
        runtime_root=runtime,
        candidate=candidate_one,
        publication_id="goal-channel:first",
        delivered_at="2026-08-01T10:00:00Z",
        covered_until="2026-08-01T08:00:00Z",
    )
    assert replayed_cursor_one == cursor_one

    second = select_incremental_project_progress(
        _snapshot(
            [
                _item("todo:a", title="A completed", summary="A is done."),
                _item("todo:b", title="B completed", summary="B is now done."),
                _item("todo:c", title="C completed", summary="C is new."),
            ]
        ),
        cursor=cursor_one,
    )
    assert second is not None
    by_ref = {item["source_ref"]: item for item in second["items"]}
    assert "todo:a" not in by_ref
    assert by_ref["todo:b"]["change_kind"] == "changed"
    assert by_ref["todo:b"]["previous_status"] == "open"
    assert by_ref["todo:c"]["change_kind"] == "added"
    assert second["incremental_baseline"] == periodic_report_incremental_baseline(
        cursor_one
    )

    candidate_two = build_periodic_report_publication_candidate(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        generation_id="report_generation_second",
        trigger_receipt=_trigger("trigger_second"),
        facts=second["items"],
        baseline=second["incremental_baseline"],
    )
    cursor_two = commit_periodic_report_publication_cursor(
        runtime_root=runtime,
        candidate=candidate_two,
        publication_id="goal-channel:second",
        delivered_at="2026-08-08T09:00:00Z",
        covered_until="2026-08-08T08:00:00Z",
    )
    assert cursor_two["predecessor_publication_id"] == "goal-channel:first"
    assert cursor_two["covered_trigger_ids"] == ["trigger_first", "trigger_second"]
    assert (
        select_incremental_project_progress(
            _snapshot(
                [
                    _item("todo:a", title="A completed", summary="A is done."),
                    _item("todo:b", title="B completed", summary="B is now done."),
                    _item("todo:c", title="C completed", summary="C is new."),
                ]
            ),
            cursor=cursor_two,
        )
        is None
    )


def test_generation_or_failed_delivery_does_not_advance_publication_cursor(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    first = select_incremental_project_progress(
        _snapshot([_item("todo:a", title="A completed", summary="A is done.")]),
        cursor=None,
    )
    assert first is not None
    candidate = build_periodic_report_publication_candidate(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        generation_id="report_generation_unpublished",
        trigger_receipt=_trigger("trigger_unpublished"),
        facts=first["items"],
        baseline=None,
    )

    assert candidate["generation_id"] == "report_generation_unpublished"
    assert (
        read_periodic_report_publication_cursor(
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
        )
        is None
    )
    retry = select_incremental_project_progress(
        deepcopy(_snapshot(first["items"])), cursor=None
    )
    assert retry is not None
    assert [item["source_ref"] for item in retry["items"]] == ["todo:a"]


def test_candidate_rejects_an_untyped_incremental_baseline() -> None:
    with pytest.raises(ValueError, match="incremental baseline must use"):
        build_periodic_report_publication_candidate(
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            generation_id="report_generation_invalid",
            trigger_receipt=_trigger("trigger_invalid"),
            facts=[_item("todo:a", title="A completed", summary="A is done.")],
            baseline={
                "cursor_id": "report_cursor_example",
                "predecessor_generation_id": "report_generation_example",
                "predecessor_publication_id": "goal-channel:example",
                "delivered_at": "2026-08-01T09:00:00Z",
                "covered_until": "2026-08-01T08:00:00Z",
            },
        )


def test_stale_candidate_cannot_overwrite_a_newer_publication_cursor(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    fact = _item("todo:a", title="A completed", summary="A is done.")
    first = select_incremental_project_progress(_snapshot([fact]), cursor=None)
    assert first is not None
    candidate_one = build_periodic_report_publication_candidate(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        generation_id="report_generation_first",
        trigger_receipt=_trigger("trigger_first"),
        facts=first["items"],
        baseline=None,
    )
    cursor = commit_periodic_report_publication_cursor(
        runtime_root=runtime,
        candidate=candidate_one,
        publication_id="goal-channel:first",
        delivered_at="2026-08-01T09:00:00Z",
        covered_until="2026-08-01T08:00:00Z",
    )
    stale = build_periodic_report_publication_candidate(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        generation_id="report_generation_stale",
        trigger_receipt=_trigger("trigger_stale"),
        facts=first["items"],
        baseline=None,
    )
    with pytest.raises(ValueError, match="baseline does not match"):
        commit_periodic_report_publication_cursor(
            runtime_root=runtime,
            candidate=stale,
            publication_id="goal-channel:stale",
            delivered_at="2026-08-01T10:00:00Z",
            covered_until="2026-08-01T08:30:00Z",
        )
    assert (
        read_periodic_report_publication_cursor(
            runtime_root=runtime,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
        )
        == cursor
    )


def test_concurrent_publications_compare_and_swap_under_one_cursor_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    fact = _item("todo:a", title="A completed", summary="A is done.")
    first = select_incremental_project_progress(_snapshot([fact]), cursor=None)
    assert first is not None
    candidates = [
        build_periodic_report_publication_candidate(
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            generation_id=f"report_generation_{suffix}",
            trigger_receipt=_trigger(f"trigger_{suffix}"),
            facts=first["items"],
            baseline=None,
        )
        for suffix in ("one", "two")
    ]
    first_acquired = Event()
    second_attempted = Event()
    counter_lock = Lock()
    attempts = 0
    original_lock = incremental.exclusive_file_lock

    @contextmanager
    def ordered_lock(*args: Any, **kwargs: Any):
        nonlocal attempts
        with counter_lock:
            attempts += 1
            attempt = attempts
        if attempt == 1:
            with original_lock(*args, **kwargs) as lock_path:
                first_acquired.set()
                assert second_attempted.wait(timeout=2)
                yield lock_path
            return
        assert first_acquired.wait(timeout=2)
        second_attempted.set()
        with original_lock(*args, **kwargs) as lock_path:
            yield lock_path

    monkeypatch.setattr(incremental, "exclusive_file_lock", ordered_lock)

    def commit(index: int) -> tuple[str, str]:
        try:
            cursor = commit_periodic_report_publication_cursor(
                runtime_root=runtime,
                candidate=candidates[index],
                publication_id=f"goal-channel:{index}",
                delivered_at=f"2026-08-01T{index + 9:02d}:00:00Z",
                covered_until="2026-08-01T08:00:00Z",
            )
        except ValueError as exc:
            return "rejected", str(exc)
        return "committed", str(cursor["generation_id"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit, (0, 1)))

    assert sorted(result[0] for result in results) == ["committed", "rejected"]
    assert next(value for status, value in results if status == "rejected") == (
        "publication candidate baseline does not match the current cursor"
    )
    cursor = read_periodic_report_publication_cursor(
        runtime_root=runtime,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )
    assert cursor is not None
    assert cursor["generation_id"] == next(
        value for status, value in results if status == "committed"
    )


def test_published_stage_trigger_is_suppressed_until_a_new_stage_exists() -> None:
    hook = periodic_report_post_writeback_hook(
        profile_ref={
            "profile_id": "weekly_progress",
            "profile_version": "v1",
        },
        trigger_policy={
            "enabled_kinds": ["bounded_segment_milestone"],
            "minimum_interval_seconds": 0,
            "aggregation": {
                "window_seconds": 604800,
                "stage_completion_required": True,
            },
        },
    )
    stage = {
        "schema_version": "periodic_report_stage_completion_receipt_v0",
        "stage_identity": "stage-first",
        "agent_id": AGENT_ID,
        "closed_vision_revision": "vision-first",
        "frontier_identity": "frontier-first",
        "transition": "successor_frontier_settled",
        "completed_at": "2026-08-01T08:00:00Z",
        "acceptance": "validated",
        "outcome_checkpoint_satisfied": True,
        "durable_writeback_required": True,
    }
    initial = hook.producer(
        {
            "receipt": {"event_id": "event-first"},
            "projection": {"stage_completion": stage},
        }
    )
    first_decision = evaluate_periodic_report_trigger_evaluation_intent(
        initial["intent"]
    )
    assert first_decision["eligible"] is True

    repeated = hook.producer(
        {
            "receipt": {"event_id": "event-replayed"},
            "projection": {
                "stage_completion": stage,
                "last_report": {
                    "delivered_at": "2026-08-01T09:00:00Z",
                    "covered_trigger_ids": first_decision["coalesced_trigger_ids"],
                },
            },
        }
    )
    repeated_decision = evaluate_periodic_report_trigger_evaluation_intent(
        repeated["intent"]
    )
    assert repeated_decision["eligible"] is False
    assert repeated_decision["suppressed_triggers"][0]["reason"] == "already_covered"


def test_snapshot_applies_cursor_before_the_six_item_report_limit(
    tmp_path: Path,
) -> None:
    state_items = []
    for index in range(7):
        state_items.append(
            "\n".join(
                [
                    f"- [x] Completed item {index}.",
                    "  <!-- loopx:todo "
                    f"todo_id=todo_{index} status=done task_class=advancement_task "
                    f"claimed_by={AGENT_ID} updated_at=2026-08-01T0{index}:00:00Z -->",
                ]
            )
        )
    state = "# Goal\n\n## User Todo\n\n## Agent Todo\n\n" + "\n".join(state_items)
    first = build_project_progress_snapshot_from_state(
        state_text=state,
        goal={"id": GOAL_ID},
        state_path=tmp_path / "goal.md",
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        completed_at="2026-08-01T08:00:00Z",
    )
    assert first is not None
    assert len(first["items"]) == 6
    candidate = build_periodic_report_publication_candidate(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        generation_id="report_generation_first_six",
        trigger_receipt=_trigger("trigger_first_six"),
        facts=first["items"],
        baseline=None,
    )
    cursor = commit_periodic_report_publication_cursor(
        runtime_root=tmp_path / "runtime",
        candidate=candidate,
        publication_id="goal-channel:first-six",
        delivered_at="2026-08-01T09:00:00Z",
        covered_until="2026-08-01T08:00:00Z",
    )
    second = build_project_progress_snapshot_from_state(
        state_text=state,
        goal={"id": GOAL_ID},
        state_path=tmp_path / "goal.md",
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        completed_at="2026-08-01T10:00:00Z",
        publication_cursor=cursor,
    )
    assert second is not None
    assert len(second["items"]) == 1
    assert second["items"][0]["title"] == "Completed item 0."
