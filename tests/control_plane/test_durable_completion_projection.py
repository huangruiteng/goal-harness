from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.todos.durable_completion import (
    project_durable_completion_intent,
    project_durable_completion_outcome,
    read_persisted_todo_record,
)
from loopx.event_sourced_state import (
    TODO_ADDED,
    TODO_COMPLETED,
    AppendOnlyStateEventStore,
    make_state_event,
)

TODO_DONE = {
    "todo_id": "todo_fixture0001",
    "status": "done",
}


def test_projects_active_goal_when_no_durable_continuation_recorded() -> None:
    outcome = project_durable_completion_outcome(
        todo=TODO_DONE,
        expected_todo_id="todo_fixture0001",
    )
    assert outcome == {
        "todo_id": "todo_fixture0001",
        "continuation": "active_goal",
    }


def test_projects_declared_successor_continuation() -> None:
    todo = {
        **TODO_DONE,
        "successor_todo_ids": ["todo_fixture0002", "todo_fixture0003"],
    }
    outcome = project_durable_completion_outcome(
        todo=todo,
        expected_todo_id="todo_fixture0001",
        existing_todo_ids={"todo_fixture0001", "todo_fixture0002", "todo_fixture0003"},
    )
    assert outcome == {
        "todo_id": "todo_fixture0001",
        "continuation": "successor",
        "successor_todo_ids": ["todo_fixture0002", "todo_fixture0003"],
    }


def test_projects_durable_no_followup_continuation() -> None:
    outcome = project_durable_completion_outcome(
        todo={**TODO_DONE, "no_followup": True},
        expected_todo_id="todo_fixture0001",
    )
    assert outcome == {
        "todo_id": "todo_fixture0001",
        "continuation": "no_followup",
    }


def test_projects_terminal_intent_without_premature_completion() -> None:
    outcome = project_durable_completion_intent(
        todo={
            "todo_id": "todo_fixture0001",
            "status": "open",
            "no_followup": True,
        },
        expected_todo_id="todo_fixture0001",
    )
    assert outcome == {
        "todo_id": "todo_fixture0001",
        "continuation": "no_followup",
    }


def test_no_followup_without_existing_ids_needs_no_successor_verification() -> None:
    outcome = project_durable_completion_outcome(
        todo={**TODO_DONE, "no_followup": True},
        expected_todo_id="todo_fixture0001",
        existing_todo_ids=set(),
    )
    assert outcome["continuation"] == "no_followup"


def test_fails_closed_on_no_followup_and_successor_contradiction() -> None:
    todo = {
        **TODO_DONE,
        "no_followup": True,
        "successor_todo_ids": ["todo_fixture0002"],
    }
    with pytest.raises(
        ValueError,
        match="both no_followup and successor_todo_ids",
    ):
        project_durable_completion_outcome(
            todo=todo,
            expected_todo_id="todo_fixture0001",
            existing_todo_ids={"todo_fixture0002"},
        )


def test_fails_closed_on_dangling_declared_successor() -> None:
    todo = {
        **TODO_DONE,
        "successor_todo_ids": ["todo_fixture0002", "todo_missing999"],
    }
    with pytest.raises(
        ValueError,
        match="declares missing successor Todo ids: todo_missing999",
    ):
        project_durable_completion_outcome(
            todo=todo,
            expected_todo_id="todo_fixture0001",
            existing_todo_ids={"todo_fixture0001", "todo_fixture0002"},
        )


def test_fails_closed_when_durable_todo_id_mismatches_selected() -> None:
    with pytest.raises(
        ValueError,
        match="does not match the selected Todo",
    ):
        project_durable_completion_outcome(
            todo={**TODO_DONE, "todo_id": "todo_fixture0009"},
            expected_todo_id="todo_fixture0001",
        )


def test_fails_closed_when_todo_is_not_durably_done() -> None:
    with pytest.raises(
        ValueError,
        match="durably done",
    ):
        project_durable_completion_outcome(
            todo={"todo_id": "todo_fixture0001", "status": "open"},
            expected_todo_id="todo_fixture0001",
        )


def test_read_persisted_todo_record_projects_declared_successor(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "ACTIVE_GOAL_STATE.md"
    state_file.write_text(
        "\n".join(
            [
                "---",
                "status: active",
                "updated_at: 2026-01-01T00:00:00+00:00",
                "---",
                "",
                "# Fixture",
                "",
                "## Agent Todo",
                "",
                "- [x] Advance one public fixture.",
                "  <!-- loopx:todo todo_id=todo_fixture0001 status=done task_class=advancement_task successor_todo_ids=todo_fixture0002 -->",
                "- [ ] Continue the public fixture.",
                "  <!-- loopx:todo todo_id=todo_fixture0002 status=open task_class=advancement_task -->",
                "",
            ]
        ),
        encoding="utf-8",
    )
    todo, existing_todo_ids = read_persisted_todo_record(
        state_file,
        todo_id="todo_fixture0001",
    )
    assert existing_todo_ids == {"todo_fixture0001", "todo_fixture0002"}
    outcome = project_durable_completion_outcome(
        todo=todo,
        expected_todo_id="todo_fixture0001",
        existing_todo_ids=existing_todo_ids,
    )
    assert outcome == {
        "todo_id": "todo_fixture0001",
        "continuation": "successor",
        "successor_todo_ids": ["todo_fixture0002"],
    }


def test_read_persisted_todo_record_fails_closed_when_todo_is_missing(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "ACTIVE_GOAL_STATE.md"
    state_file.write_text(
        "\n".join(
            [
                "---",
                "status: active",
                "---",
                "",
                "## Agent Todo",
                "",
                "- [x] Some other fixture.",
                "  <!-- loopx:todo todo_id=todo_other0001 status=done -->",
                "",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match="was not found in persisted Todo lifecycle state",
    ):
        read_persisted_todo_record(
            state_file,
            todo_id="todo_fixture0001",
        )


def test_read_persisted_todo_record_falls_back_to_event_projection(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state_file = repo / "ACTIVE_GOAL_STATE.md"
    state_file.write_text(
        "\n".join(
            [
                "---",
                "status: active",
                "updated_at: 2026-01-01T00:00:00+00:00",
                "---",
                "",
                "# Fixture",
                "",
                "## Agent Todo",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    # The event-sourced Todo lives only in the event log, mirroring the
    # completion payload shape written by complete_event_projected_goal_todo.
    goal_id = "fixture-goal"
    events = [
        make_state_event(
            event_id="add-fixture-1",
            goal_id=goal_id,
            event_type=TODO_ADDED,
            refs={"todo_id": "todo_fixture0001"},
            payload={
                "role": "agent",
                "priority": "P0",
                "title": "Advance one public fixture.",
                "text": "Advance one public fixture.",
                "planner_order": 1,
                "task_class": "advancement_task",
            },
        ),
        make_state_event(
            event_id="complete-fixture-1",
            goal_id=goal_id,
            event_type=TODO_COMPLETED,
            refs={"todo_id": "todo_fixture0001"},
            payload={"no_followup": "true"},
        ),
    ]
    AppendOnlyStateEventStore(repo / "events.jsonl").append_many(events)
    registry = tmp_path / "registry.global.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(tmp_path / "runtime"),
                "goals": [
                    {
                        "id": goal_id,
                        "domain": "fixture",
                        "status": "active",
                        "repo": str(repo),
                        "state_file": state_file.name,
                        "adapter": {"kind": "fixture_v0"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    todo, existing_todo_ids = read_persisted_todo_record(
        state_file,
        todo_id="todo_fixture0001",
        registry_path=registry,
        goal_id=goal_id,
    )
    assert existing_todo_ids == {"todo_fixture0001"}
    outcome = project_durable_completion_outcome(
        todo=todo,
        expected_todo_id="todo_fixture0001",
        existing_todo_ids=existing_todo_ids,
    )
    assert outcome == {
        "todo_id": "todo_fixture0001",
        "continuation": "no_followup",
    }
