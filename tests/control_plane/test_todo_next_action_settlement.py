from __future__ import annotations

import json
from pathlib import Path

from loopx.bootstrap import render_state_markdown
from loopx.state_projection import active_state_next_action_entries
from loopx.state_refresh import build_state_refresh_record
from loopx.todos import add_goal_todo, complete_goal_todo, supersede_goal_todo

GOAL_ID = "todo-next-action-settlement"
AGENT_ID = "codex-next-action"


def _write_fixture(tmp_path: Path, *, next_action: str) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "\n".join(
            [
                "---",
                f"goal_id: {GOAL_ID}",
                "updated_at: 2026-08-21T00:00:00+08:00",
                "---",
                "",
                "## Agent Todo",
                "",
                "## Next Action",
                "",
                f"- {next_action}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "registry.global.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(tmp_path / "runtime"),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "harness_self_improvement",
                        "status": "active",
                        "repo": str(repo),
                        "state_file": state.name,
                        "adapter": {"kind": "harness_self_improvement"},
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry, state


def test_bootstrap_binds_generated_connection_validation_next_action(
    tmp_path: Path,
) -> None:
    state_text = render_state_markdown(
        project=tmp_path,
        goal_id=GOAL_ID,
        adapter_kind="read_only_project_map_v0",
        objective="Implement and validate the task.",
        updated_at="2026-08-21T00:00:00+08:00",
        goal_doc=None,
        execution_profile=None,
    )

    assert "<!-- loopx:next-action schema=loopx_next_action_binding_v0" in state_text
    assert "todo_id=todo_" in state_text
    assert active_state_next_action_entries(state_text) == [
        (
            "[P1] Run `loopx check` against the project registry and record the first "
            "project-specific adapter signal or an explicit no-follow-up rationale."
        )
    ]
    record = build_state_refresh_record(
        goal_id=GOAL_ID,
        state_file=tmp_path / "ACTIVE_GOAL_STATE.md",
        state_text=state_text,
        classification="state_refreshed",
        recommended_action="Continue the selected task.",
        recommended_action_source="test",
        generated_at="2026-08-21T00:01:00+08:00",
        registry_goal=None,
    )
    assert record["state"]["next_action"] == active_state_next_action_entries(
        state_text
    )
    assert "loopx:next-action" not in json.dumps(record)


def test_refresh_record_preserves_a_long_wrapped_next_action_losslessly(
    tmp_path: Path,
) -> None:
    prefix = "Run one bounded settlement check and preserve its durable context"
    tail = "through the final public-safe boundary sentence without truncation."
    state_text = "\n".join(
        [
            "---",
            f"goal_id: {GOAL_ID}",
            "---",
            "",
            "## Next Action",
            "",
            f"- {prefix} " + ("across related control-plane state " * 8),
            f"  {tail}",
            "",
        ]
    )

    assert active_state_next_action_entries(state_text)[0].endswith("…")
    record = build_state_refresh_record(
        goal_id=GOAL_ID,
        state_file=tmp_path / "ACTIVE_GOAL_STATE.md",
        state_text=state_text,
        classification="state_refreshed",
        recommended_action=prefix,
        recommended_action_source="test",
        generated_at="2026-08-21T00:01:00+08:00",
        registry_goal=None,
    )

    assert record["state"]["next_action"][0].endswith(tail)
    assert "…" not in record["state"]["next_action"][0]


def test_complete_reprojects_typed_next_action_to_open_successor(
    tmp_path: Path,
) -> None:
    completed_text = "[P1] Validate the project connection."
    registry, state = _write_fixture(tmp_path, next_action=completed_text)
    completed = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=completed_text,
        task_class="advancement_task",
        action_kind="onboarding_connection_validation",
        claimed_by=AGENT_ID,
    )
    successor = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="[P0] Implement and validate the requested behavior.",
        task_class="advancement_task",
        action_kind="implementation",
        claimed_by=AGENT_ID,
    )
    state.write_text(
        state.read_text(encoding="utf-8").replace(
            f"- {completed_text}\n",
            f"- {completed_text}\n"
            "<!-- loopx:next-action schema=loopx_next_action_binding_v0 "
            f"todo_id={completed['todo_id']} -->\n",
            1,
        ),
        encoding="utf-8",
    )

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(completed["todo_id"]),
        successor_todo_ids=[str(successor["todo_id"])],
        agent_id=AGENT_ID,
        evidence="connection preflight passed",
    )

    assert result["changed"] is True
    assert active_state_next_action_entries(state.read_text(encoding="utf-8")) == [
        "[P0] Implement and validate the requested behavior."
    ]


def test_supersede_reprojects_after_generated_successor_is_materialized(
    tmp_path: Path,
) -> None:
    completed_text = "[P1] Replace the obsolete implementation."
    registry, state = _write_fixture(tmp_path, next_action=completed_text)
    completed = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=completed_text,
        task_class="advancement_task",
        action_kind="implementation",
        claimed_by=AGENT_ID,
    )
    state.write_text(
        state.read_text(encoding="utf-8").replace(
            f"- {completed_text}\n",
            f"- {completed_text}\n"
            "<!-- loopx:next-action schema=loopx_next_action_binding_v0 "
            f"todo_id={completed['todo_id']} -->\n",
            1,
        ),
        encoding="utf-8",
    )

    result = supersede_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(completed["todo_id"]),
        reason="replace the obsolete route",
        next_agent_todo="[P1] Implement the corrected route.",
        next_action_kind="implementation",
        next_claimed_by=AGENT_ID,
        agent_id=AGENT_ID,
    )

    successor_id = result["next_todos"][0]["todo_id"]
    state_text = state.read_text(encoding="utf-8")
    assert active_state_next_action_entries(state_text) == [
        "[P1] Implement the corrected route."
    ]
    assert f"todo_id={successor_id} -->" in state_text


def test_complete_preserves_unrelated_owner_next_action(tmp_path: Path) -> None:
    registry, state = _write_fixture(
        tmp_path,
        next_action="Keep the owner-approved release route unchanged.",
    )
    todo = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="[P1] Validate the project connection.",
        task_class="advancement_task",
        action_kind="onboarding_connection_validation",
        claimed_by=AGENT_ID,
    )

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        no_followup=True,
        agent_id=AGENT_ID,
        evidence="connection preflight passed",
    )

    assert result["changed"] is True
    assert active_state_next_action_entries(state.read_text(encoding="utf-8")) == [
        "Keep the owner-approved release route unchanged."
    ]


def test_complete_waits_for_generated_successor_before_reprojecting(
    tmp_path: Path,
) -> None:
    completed_text = "[P0] Finish the bounded implementation."
    registry, state = _write_fixture(tmp_path, next_action=completed_text)
    completed = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=completed_text,
        task_class="advancement_task",
        action_kind="implementation",
        claimed_by=AGENT_ID,
    )
    state.write_text(
        state.read_text(encoding="utf-8").replace(
            f"- {completed_text}\n",
            f"- {completed_text}\n"
            "<!-- loopx:next-action schema=loopx_next_action_binding_v0 "
            f"todo_id={completed['todo_id']} -->\n",
            1,
        ),
        encoding="utf-8",
    )

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(completed["todo_id"]),
        next_agent_todo="[P1] Review and validate the implementation.",
        next_action_kind="validation_review",
        next_claimed_by=AGENT_ID,
        agent_id=AGENT_ID,
        evidence="implementation completed",
    )

    successor_id = result["next_todos"][0]["todo_id"]
    state_text = state.read_text(encoding="utf-8")
    assert active_state_next_action_entries(state_text) == [
        "[P1] Review and validate the implementation."
    ]
    assert f"todo_id={successor_id} -->" in state_text


def test_complete_migrates_legacy_exact_text_next_action(tmp_path: Path) -> None:
    completed_text = "[P1] Validate the legacy project connection."
    registry, state = _write_fixture(tmp_path, next_action=completed_text)
    completed = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=completed_text,
        task_class="advancement_task",
        action_kind="onboarding_connection_validation",
        claimed_by=AGENT_ID,
    )

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(completed["todo_id"]),
        no_followup=True,
        agent_id=AGENT_ID,
        evidence="legacy connection preflight passed",
    )

    assert result["changed"] is True
    assert active_state_next_action_entries(state.read_text(encoding="utf-8")) == []


def test_complete_upgrades_legacy_open_todo_to_typed_binding(
    tmp_path: Path,
) -> None:
    completed_text = "[P0] Finish the bound implementation."
    registry, state = _write_fixture(tmp_path, next_action=completed_text)
    completed = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=completed_text,
        task_class="advancement_task",
        action_kind="implementation",
        claimed_by=AGENT_ID,
    )
    state_text = state.read_text(encoding="utf-8")
    state_text = state_text.replace(
        "## Next Action",
        "- [ ] [P1] Legacy open work without metadata.\n\n## Next Action",
        1,
    ).replace(
        f"- {completed_text}\n",
        f"- {completed_text}\n"
        "<!-- loopx:next-action schema=loopx_next_action_binding_v0 "
        f"todo_id={completed['todo_id']} -->\n",
        1,
    )
    state.write_text(state_text, encoding="utf-8")

    complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(completed["todo_id"]),
        no_followup=True,
        agent_id=AGENT_ID,
        evidence="implementation completed",
    )

    final_text = state.read_text(encoding="utf-8")
    assert active_state_next_action_entries(final_text) == [
        "[P1] Legacy open work without metadata."
    ]
    assert (
        "<!-- loopx:next-action schema=loopx_next_action_binding_v0 todo_id=todo_"
        in final_text
    )
    assert "todo_id=None" not in final_text
