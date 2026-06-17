#!/usr/bin/env python3
"""Smoke-test quota guard for required write scopes on executable todos."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.quota import build_quota_should_run, render_quota_should_run_markdown  # noqa: E402
from goal_harness.status import compact_todo_group, project_asset_todo_summary  # noqa: E402
from goal_harness.todo_contract import format_todo_metadata_line, parse_todo_metadata_line  # noqa: E402


GOAL_ID = "action-scope-guard-fixture"
TODO_TEXT = "Patch the runner adapter after the checkpointed owner decision is projected."


def status_payload(*, allowed_scopes: list[str]) -> dict:
    todo = {
        "index": 1,
        "done": False,
        "status": "open",
        "text": TODO_TEXT,
        "task_class": "advancement_task",
        "action_kind": "implement",
        "required_write_scopes": ["runners/openviking/**"],
    }
    agent_todos = {
        "schema_version": "todo_summary_v0",
        "source_section": "Agent Todo",
        "open_count": 1,
        "done_count": 0,
        "total_count": 1,
        "first_open_items": [todo],
        "first_executable_items": [todo],
        "items": [todo],
    }
    return {
        "ok": True,
        "goal_count": 1,
        "run_count": 0,
        "attention_queue": {
            "items": [
                {
                    "goal_id": GOAL_ID,
                    "status": "active",
                    "waiting_on": "codex",
                    "severity": "action",
                    "source": "latest_run",
                    "recommended_action": "Execute the first agent todo only if its required scope is inside goal_boundary.",
                    "quota": {
                        "compute": 1.0,
                        "window_hours": 24,
                        "slot_minutes": 1,
                        "allowed_slots": 1440,
                        "spent_slots": 0,
                        "state": "eligible",
                        "reason": "eligible fixture",
                    },
                    "agent_todos": agent_todos,
                }
            ]
        },
        "run_history": {
            "goals": [
                {
                    "id": GOAL_ID,
                    "registry_member": True,
                    "status": "active",
                    "adapter_kind": "fixture_adapter_v0",
                    "adapter_status": "connected",
                    "coordination": {
                        "write_scope": allowed_scopes,
                        "requires_parent_approval": ["publish", "production-action"],
                    },
                    "latest_runs": [],
                }
            ]
        },
    }


def assert_missing_scope_repairs_boundary() -> None:
    payload = build_quota_should_run(
        status_payload(allowed_scopes=["docs/**"]),
        goal_id=GOAL_ID,
    )
    assert payload["should_run"] is True, payload
    assert payload["normal_delivery_allowed"] is False, payload
    assert payload["self_repair_allowed"] is True, payload
    assert payload["effective_action"] == "boundary_projection_repair", payload
    assert payload["blocked_action_scope"] == "boundary_projection", payload
    gap = payload["boundary_projection_gap"]
    assert gap["missing_write_scopes"] == ["runners/openviking/**"], gap
    assert gap["allowed_write_scopes"] == ["docs/**"], gap
    assert payload["heartbeat_recommendation"]["recommended_mode"] == "repair_boundary_projection", payload
    assert payload["execution_obligation"]["kind"] == "boundary_projection_repair", payload
    assert payload["execution_obligation"]["delivery_allowed"] is False, payload
    contract = payload["interaction_contract"]
    assert contract["mode"] == "boundary_projection_repair", contract
    assert contract["agent_channel"]["delivery_allowed"] is False, contract
    assert "goal_boundary.write_scope" in contract["agent_channel"]["primary_action"], contract
    markdown = render_quota_should_run_markdown(payload)
    assert "boundary_missing_write_scopes: runners/openviking/**" in markdown, markdown
    assert "blocked_action_scope: `boundary_projection`" in markdown, markdown


def assert_required_write_scope_metadata_roundtrip() -> None:
    metadata_line = format_todo_metadata_line(
        todo_id="todo_scope123",
        status="open",
        task_class="advancement_task",
        action_kind="implement",
        required_write_scopes=["runners/openviking/**", "docs/**"],
    )
    assert metadata_line is not None
    parsed = parse_todo_metadata_line(metadata_line)
    assert parsed is not None, metadata_line
    assert parsed["required_write_scopes"] == ["runners/openviking/**", "docs/**"], parsed
    group = compact_todo_group(
        [
            {
                "index": 1,
                "done": False,
                "text": TODO_TEXT,
                **parsed,
            }
        ],
        source_section="Agent Todo",
        role="agent",
    )
    assert group is not None, group
    first = group["first_executable_items"][0]
    assert first["required_write_scopes"] == ["runners/openviking/**", "docs/**"], first
    asset_summary = project_asset_todo_summary(group)
    assert asset_summary is not None, group
    assert asset_summary["items"][0]["required_write_scopes"] == [
        "runners/openviking/**",
        "docs/**",
    ], asset_summary


def assert_allowed_scope_remains_runnable() -> None:
    payload = build_quota_should_run(
        status_payload(allowed_scopes=["runners/**", "docs/**"]),
        goal_id=GOAL_ID,
    )
    assert payload["should_run"] is True, payload
    assert payload["normal_delivery_allowed"] is True, payload
    assert payload["self_repair_allowed"] is False, payload
    assert payload["effective_action"] == "normal_run", payload
    assert "boundary_projection_gap" not in payload, payload
    assert payload["goal_boundary"]["write_scope"] == ["runners/**", "docs/**"], payload


def main() -> int:
    assert_required_write_scope_metadata_roundtrip()
    assert_missing_scope_repairs_boundary()
    assert_allowed_scope_remains_runnable()
    print("quota-action-scope-guard-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
