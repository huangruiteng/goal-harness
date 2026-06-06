#!/usr/bin/env python3
"""Guard the project-asset "next eye" operator contract.

The first screen should let an operator decide where to look next without
reading old threads: project identity, waiting owner/gate, next action, stop
condition, todo ownership, quota, and latest validation must stay visible from
the shared project_asset contract.
"""

from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from goal_harness.status import (  # noqa: E402
    build_project_asset,
    enrich_project_asset,
    project_asset_summary_is_public_safe,
)


USER_TODO = "Review the owner decision before approving delivery."
AGENT_TODO = "Run the read-only map after the owner decision is recorded."
NEXT_ACTION = "Use the current project asset to choose one bounded delivery step."
STOP_CONDITION = "stop until the user or controller decision is recorded"
VALIDATION_SUMMARY = "fixture validation passed; authority_sources 1"


def assert_status_project_asset_next_eye() -> None:
    item = {
        "goal_id": "next-eye-fixture",
        "recommended_action": NEXT_ACTION,
        "project_asset": build_project_asset(
            status="operator_gate",
            waiting_on="user_or_controller",
            recommended_action=NEXT_ACTION,
            operator_question="Should this project proceed?",
            agent_command=None,
            missing_gates=None,
            next_handoff_condition=None,
        ),
    }
    user_todos = {
        "open_count": 1,
        "done_count": 0,
        "total_count": 1,
        "items": [{"index": 1, "done": False, "text": USER_TODO}],
    }
    agent_todos = {
        "open_count": 1,
        "done_count": 0,
        "total_count": 1,
        "items": [{"index": 1, "done": False, "text": AGENT_TODO}],
    }
    quota = {
        "compute": 0.5,
        "state": "operator_gate",
        "spent_slots": 2,
        "allowed_slots": 10,
        "reason": "waiting for owner decision",
    }
    latest_validation = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "classification": "next_eye_fixture",
        "summary": VALIDATION_SUMMARY,
    }

    enrich_project_asset(
        item,
        user_todos=user_todos,
        agent_todos=agent_todos,
        quota=quota,
        latest_validation=latest_validation,
        execution_profile={"minimum_scale": "implementation"},
        orchestration={"mode": "default", "allowed": False, "max_children": 3},
    )

    asset = item["project_asset"]
    for field in ("owner", "gate", "next_action", "stop_condition"):
        assert asset.get(field), asset
    assert asset["owner"] == "user_or_controller", asset
    assert asset["gate"] == "operator_question", asset
    assert asset["next_action"] == NEXT_ACTION, asset
    assert asset["stop_condition"] == STOP_CONDITION, asset
    assert asset["user_todos"]["open"] == 1, asset
    assert asset["user_todos"]["next"] == USER_TODO, asset
    assert asset["agent_todos"]["open"] == 1, asset
    assert asset["agent_todos"]["next"] == AGENT_TODO, asset
    assert asset["quota"]["state"] == "operator_gate", asset
    assert asset["latest_validation"]["classification"] == "next_eye_fixture", asset
    assert asset["latest_validation"]["summary"] == VALIDATION_SUMMARY, asset
    assert project_asset_summary_is_public_safe(asset), asset


def assert_dashboard_first_screen_render_contract() -> None:
    dashboard = (REPO_ROOT / "apps/dashboard/src/views/dashboard-page.tsx").read_text(
        encoding="utf-8"
    )
    for marker in (
        "Project asset",
        "Owner {item.projectOwner}",
        "Gate {item.projectGate}",
        "Next:",
        "Stop:",
        "UserTodoCallout",
        "Agent todo",
        "Validation",
        "Quota",
    ):
        assert marker in dashboard, marker


def main() -> int:
    assert_status_project_asset_next_eye()
    assert_dashboard_first_screen_render_contract()
    print("project-asset-next-eye-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
