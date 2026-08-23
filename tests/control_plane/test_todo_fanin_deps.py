from __future__ import annotations

import json
from pathlib import Path

from loopx.control_plane.testing.canary_harness import run_json_cli, write_fixture_registry
from loopx.control_plane.todos.active_state_todo_parser import parse_active_state_todos
from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path
from loopx.todos import add_goal_todo, complete_goal_todo, update_goal_todo


GOAL_ID = "todo-fanin-deps"
AGENT_ID = "codex-delivery"
OTHER_AGENT_ID = "codex-review"


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "\n".join(
            [
                "---",
                f"goal_id: {GOAL_ID}",
                "updated_at: 2026-08-23T00:00:00+00:00",
                "---",
                "",
                "## Agent Todo",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.global.json"
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "harness_self_improvement",
                        "status": "active",
                        "repo": str(repo),
                        "state_file": "ACTIVE_GOAL_STATE.md",
                        "adapter": {"kind": "harness_self_improvement"},
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID, OTHER_AGENT_ID],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return repo, state, registry


def _todo(state: Path, todo_id: str) -> dict:
    todos = parse_active_state_todos(state.read_text(encoding="utf-8"))
    return next(
        item
        for role in ("agent_todos", "user_todos")
        for item in todos[role]["items"]
        if item["todo_id"] == todo_id
    )


def _add_open_agent(registry: Path, *, text: str) -> dict:
    return add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=text,
        task_class="advancement_task",
        claimed_by=AGENT_ID,
    )


def _complete_agent(registry: Path, todo_id: str) -> dict:
    return complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=todo_id,
        role="agent",
        agent_id=AGENT_ID,
        no_followup=True,
        evidence="prerequisite finished",
    )


def test_todo_add_and_update_write_depends_on_todo_ids(tmp_path: Path) -> None:
    _repo, state, registry = _write_fixture(tmp_path)
    first = _add_open_agent(registry, text="Finish the first prerequisite.")
    second = _add_open_agent(registry, text="Finish the second prerequisite.")
    waiter = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Start only after both prerequisites.",
        status="blocked",
        task_class="advancement_task",
        claimed_by=AGENT_ID,
        depends_on_todo_ids=[first["todo_id"], second["todo_id"]],
    )

    assert waiter["depends_on_todo_ids"] == [first["todo_id"], second["todo_id"]]
    assert _todo(state, waiter["todo_id"])["depends_on_todo_ids"] == [
        first["todo_id"],
        second["todo_id"],
    ]

    extra = _add_open_agent(registry, text="Finish a later third prerequisite.")
    updated = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=waiter["todo_id"],
        depends_on_todo_ids=[first["todo_id"], extra["todo_id"]],
        agent_id=AGENT_ID,
        authority_reason="owner-approved fan-in rewrite",
    )
    assert updated["depends_on_todo_ids"] == [first["todo_id"], extra["todo_id"]]
    assert _todo(state, waiter["todo_id"])["depends_on_todo_ids"] == [
        first["todo_id"],
        extra["todo_id"],
    ]


def test_two_prerequisites_stay_blocked_until_both_complete(tmp_path: Path) -> None:
    _repo, state, registry = _write_fixture(tmp_path)
    first = _add_open_agent(registry, text="Finish the first prerequisite.")
    second = _add_open_agent(registry, text="Finish the second prerequisite.")
    waiter = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Start only after both prerequisites.",
        status="blocked",
        task_class="advancement_task",
        claimed_by=AGENT_ID,
        depends_on_todo_ids=[first["todo_id"], second["todo_id"]],
    )

    first_done = _complete_agent(registry, first["todo_id"])
    first_receipts = first_done["dependency_resumes"]
    assert first_receipts == [
        {
            "schema_version": "todo_dependency_resume_v0",
            "source_todo_id": first["todo_id"],
            "target_todo_id": waiter["todo_id"],
            "target_role": "agent",
            "previous_status": "blocked",
            "status": "blocked",
            "changed": False,
            "state": "other_dependencies_active",
            "remaining_todo_ids": [second["todo_id"]],
        }
    ]
    assert _todo(state, waiter["todo_id"])["status"] == "blocked"

    second_done = _complete_agent(registry, second["todo_id"])
    second_receipts = second_done["dependency_resumes"]
    assert second_receipts[0]["state"] == "resumed"
    assert second_receipts[0]["changed"] is True
    assert second_receipts[0]["status"] == "open"
    assert second_receipts[0]["target_todo_id"] == waiter["todo_id"]
    assert second_receipts[0]["previous_status"] == "blocked"
    assert _todo(state, waiter["todo_id"])["status"] == "open"


def test_agent_completion_resumes_deferred_peer_waiter(tmp_path: Path) -> None:
    _repo, state, registry = _write_fixture(tmp_path)
    source = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Produce the review packet.",
        task_class="advancement_task",
        claimed_by=AGENT_ID,
    )
    waiter = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Review after the packet exists.",
        status="deferred",
        task_class="advancement_task",
        claimed_by=OTHER_AGENT_ID,
        resume_when=f"todo_done:{source['todo_id']}",
        depends_on_todo_ids=[source["todo_id"]],
    )

    completed = _complete_agent(registry, source["todo_id"])
    assert completed["dependency_resumes"][0]["state"] == "resumed"
    assert completed["dependency_resumes"][0]["previous_status"] == "deferred"
    assert _todo(state, waiter["todo_id"])["status"] == "open"


def test_user_action_completion_also_resumes_waiter(tmp_path: Path) -> None:
    _repo, state, registry = _write_fixture(tmp_path)
    source = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="user",
        text="Provide the missing owner artifact.",
        task_class="user_action",
        bound_agent=AGENT_ID,
    )
    waiter = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Continue after the owner artifact exists.",
        status="blocked",
        task_class="advancement_task",
        claimed_by=AGENT_ID,
        depends_on_todo_ids=[source["todo_id"]],
    )

    completed = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=source["todo_id"],
        role="user",
        agent_id=AGENT_ID,
        evidence="owner supplied the artifact",
        no_followup=True,
    )
    assert completed["dependency_resumes"][0]["state"] == "resumed"
    assert _todo(state, waiter["todo_id"])["status"] == "open"


def test_explicit_blocker_is_not_auto_resumed(tmp_path: Path) -> None:
    _repo, state, registry = _write_fixture(tmp_path)
    source = _add_open_agent(registry, text="Attempt the blocked repair.")
    waiter = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Repair the explicit blocker after the attempt.",
        status="blocked",
        task_class="blocker",
        claimed_by=AGENT_ID,
        depends_on_todo_ids=[source["todo_id"]],
    )

    completed = _complete_agent(registry, source["todo_id"])
    assert completed["dependency_resumes"] == [
        {
            "schema_version": "todo_dependency_resume_v0",
            "source_todo_id": source["todo_id"],
            "target_todo_id": waiter["todo_id"],
            "target_role": "agent",
            "previous_status": "blocked",
            "status": "blocked",
            "changed": False,
            "state": "explicit_blocker_repair_required",
        }
    ]
    assert _todo(state, waiter["todo_id"])["status"] == "blocked"


def test_cli_complete_records_dependency_resume_in_rollout_log(tmp_path: Path) -> None:
    project = tmp_path / "project"
    runtime = tmp_path / "runtime"
    state_file = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    registry_path = project / ".loopx" / "registry.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        "---\nstatus: active\n---\n\n# Active Goal State\n\n## Objective\n\n"
        "Prove fan-in resume writes a rollout event.\n\n## Next Action\n\n"
        "- Complete the last remaining prerequisite.\n",
        encoding="utf-8",
    )
    write_fixture_registry(
        project=project,
        runtime_root=runtime,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        domain="todo-fanin-deps",
        adapter_kind="generic_project_goal_v0",
        registered_agents=[AGENT_ID, OTHER_AGENT_ID],
    )

    first = run_json_cli(
        "todo",
        "add",
        "--goal-id",
        GOAL_ID,
        "--role",
        "agent",
        "--text",
        "Finish the first prerequisite.",
        "--task-class",
        "advancement_task",
        "--claimed-by",
        AGENT_ID,
        registry_path=registry_path,
    )
    second = run_json_cli(
        "todo",
        "add",
        "--goal-id",
        GOAL_ID,
        "--role",
        "agent",
        "--text",
        "Finish the second prerequisite.",
        "--task-class",
        "advancement_task",
        "--claimed-by",
        AGENT_ID,
        registry_path=registry_path,
    )
    waiter = run_json_cli(
        "todo",
        "add",
        "--goal-id",
        GOAL_ID,
        "--role",
        "agent",
        "--text",
        "Start only after both prerequisites.",
        "--status",
        "blocked",
        "--task-class",
        "advancement_task",
        "--claimed-by",
        AGENT_ID,
        "--depends-on-todo-id",
        first["todo_id"],
        "--depends-on-todo-id",
        second["todo_id"],
        registry_path=registry_path,
    )
    assert waiter["depends_on_todo_ids"] == [first["todo_id"], second["todo_id"]]

    first_complete = run_json_cli(
        "todo",
        "complete",
        "--goal-id",
        GOAL_ID,
        "--todo-id",
        first["todo_id"],
        "--role",
        "agent",
        "--agent-id",
        AGENT_ID,
        "--no-follow-up",
        "--evidence",
        "first prerequisite finished",
        registry_path=registry_path,
    )
    assert first_complete["dependency_resumes"][0]["state"] == "other_dependencies_active"
    assert _todo(state_file, waiter["todo_id"])["status"] == "blocked"

    second_complete = run_json_cli(
        "todo",
        "complete",
        "--goal-id",
        GOAL_ID,
        "--todo-id",
        second["todo_id"],
        "--role",
        "agent",
        "--agent-id",
        AGENT_ID,
        "--no-follow-up",
        "--evidence",
        "second prerequisite finished",
        registry_path=registry_path,
    )
    assert second_complete["dependency_resumes"][0]["state"] == "resumed"
    assert second_complete["dependency_resume_events"]
    assert _todo(state_file, waiter["todo_id"])["status"] == "open"

    events = load_rollout_events(rollout_event_log_path(runtime, GOAL_ID))
    resume_events = [
        event for event in events if event.get("event_kind") == "todo_dependency_resume"
    ]
    assert len(resume_events) == 1
    assert resume_events[0]["todo_id"] == waiter["todo_id"]
    assert resume_events[0]["details"]["source_todo_id"] == second["todo_id"]
    assert resume_events[0]["details"]["state"] == "resumed"
    assert resume_events[0]["details"]["status"] == "open"
