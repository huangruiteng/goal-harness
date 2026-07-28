from __future__ import annotations

import pytest

from loopx.control_plane.todos.contract import (
    format_todo_metadata_line,
    parse_todo_metadata_line,
)


def test_todo_metadata_round_trip_preserves_canonical_values() -> None:
    line = format_todo_metadata_line(
        todo_id="todo_schema001",
        status="open",
        task_class="advancement_task",
        action_kind="run_eval",
        task_repository="git:github.com/owner/repo",
        continuation_policy="same_agent_non_delivery",
        required_write_scopes=["loopx/**", "tests/**"],
        required_capabilities=["network", "filesystem_write"],
        target_capabilities=["quality_receipt"],
        explore_result_node_refs=["result.primary"],
        decision_scope="direction:action:review",
        required_decision_scopes=["write_scope:project:loopx"],
        decision_outcome="approve",
        decision_scope_outcomes=[
            {
                "outcome": "approve",
                "decision_scope": "direction:action:review",
                "source_todo_id": "todo_source001",
            }
        ],
        claimed_by="codex-quality",
        bound_agent="codex-main",
        goal_bound=False,
        blocks_agent="codex-side",
        excluded_agents=["codex-other"],
        global_gate=False,
        unblocks_todo_id="todo_blocked001",
        successor_todo_ids=["todo_next001", "todo_next002"],
        resume_when="todo_done:todo_blocked001",
        no_followup=False,
        target_key="github-pr-1",
        cadence="30m",
        next_due_at="2026-07-28T01:00:00+08:00",
        expires_at="2026-07-29T01:00:00+08:00",
        last_checked_at="2026-07-28T00:30:00+08:00",
        result_hash="abc123",
        consecutive_no_change="2",
        material_change="false",
        max_no_change_before_replan="3",
        note="focused validation passed",
        evidence="receipt cqr_123",
        reason="bounded refactor",
        completed_at="2026-07-28T00:40:00+08:00",
        updated_at="2026-07-28T00:41:00+08:00",
        superseded_by="todo_replacement001",
    )

    assert line is not None
    assert parse_todo_metadata_line(line) == {
        "todo_id": "todo_schema001",
        "status": "open",
        "task_class": "advancement_task",
        "action_kind": "run_eval",
        "task_repository": "git:github.com/owner/repo",
        "continuation_policy": "same_agent_non_delivery",
        "required_write_scopes": ["loopx/**", "tests/**"],
        "required_capabilities": ["network", "filesystem_write"],
        "target_capabilities": ["quality_receipt"],
        "explore_result_node_refs": ["result.primary"],
        "decision_scope": {
            "schema_version": "decision_scope_v0",
            "kind": "direction",
            "granularity": "action",
            "scope_key": "review",
        },
        "required_decision_scopes": [
            {
                "schema_version": "decision_scope_v0",
                "kind": "write_scope",
                "granularity": "project",
                "scope_key": "loopx",
            }
        ],
        "decision_outcome": "approve",
        "decision_scope_outcomes": [
            {
                "schema_version": "todo_decision_scope_outcome_v0",
                "outcome": "approve",
                "decision_scope": {
                    "schema_version": "decision_scope_v0",
                    "kind": "direction",
                    "granularity": "action",
                    "scope_key": "review",
                },
                "source_todo_id": "todo_source001",
            }
        ],
        "claimed_by": "codex-quality",
        "bound_agent": "codex-main",
        "goal_bound": False,
        "blocks_agent": "codex-side",
        "excluded_agents": ["codex-other"],
        "global_gate": False,
        "unblocks_todo_id": "todo_blocked001",
        "successor_todo_ids": ["todo_next001", "todo_next002"],
        "resume_when": "todo_done:todo_blocked001",
        "no_followup": False,
        "target_key": "github-pr-1",
        "cadence": "30m",
        "next_due_at": "2026-07-28T01:00:00+08:00",
        "expires_at": "2026-07-29T01:00:00+08:00",
        "last_checked_at": "2026-07-28T00:30:00+08:00",
        "result_hash": "abc123",
        "consecutive_no_change": "2",
        "material_change": "false",
        "max_no_change_before_replan": "3",
        "note": "focused validation passed",
        "evidence": "receipt cqr_123",
        "reason": "bounded refactor",
        "completed_at": "2026-07-28T00:40:00+08:00",
        "updated_at": "2026-07-28T00:41:00+08:00",
        "superseded_by": "todo_replacement001",
    }


def test_todo_metadata_parser_ignores_noncanonical_field_names() -> None:
    parsed = parse_todo_metadata_line(
        "  <!-- loopx:todo "
        "todo_id=todo_canonical001 "
        "required_write_scope=loopx%2F** "
        "required-capabilities=network "
        "target_capability=quality_receipt "
        "explore_result_node_ref=result.primary "
        "required_decision_scope=direction:action:review "
        "excluded_agent=codex-other "
        "successor_todo_id=todo_next001 "
        "legacy-status=done "
        "continuation_policy=same_agent_non_delivery "
        "-->"
    )

    assert parsed == {
        "todo_id": "todo_canonical001",
        "continuation_policy": "same_agent_non_delivery",
    }


def test_todo_metadata_parser_skips_invalid_canonical_values() -> None:
    assert parse_todo_metadata_line(
        "  <!-- loopx:todo todo_id=todo_valid001 status=unknown "
        "claimed_by=%2Fprivate required_capabilities=network -->"
    ) == {
        "todo_id": "todo_valid001",
        "required_capabilities": ["network"],
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"todo_id": "bad"}, "todo_id must use the public token shape"),
        ({"status": "unknown"}, "todo status must be one of"),
        ({"required_write_scopes": ["/private"]}, "public-safe relative scope"),
        ({"decision_scope": "invalid"}, "decision_scope must use"),
        ({"excluded_agents": ["bad/value"]}, "public-safe agent tokens"),
        ({"successor_todo_ids": ["bad"]}, "successor_todo_ids must contain"),
    ],
)
def test_todo_metadata_formatter_rejects_invalid_canonical_values(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        format_todo_metadata_line(**kwargs)


def test_todo_metadata_formatter_enforces_cross_field_constraints() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        format_todo_metadata_line(
            continuation_policy="independent_handoff",
            removed_continuation_policy="review_handoff",
        )

    with pytest.raises(ValueError, match="cannot also appear in excluded_agents"):
        format_todo_metadata_line(
            claimed_by="codex-quality",
            excluded_agents=["codex-quality"],
        )
