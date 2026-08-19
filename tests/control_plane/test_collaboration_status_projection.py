from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loopx.cli import build_parser
from loopx.control_plane.goals.collaboration_status import (
    build_collaboration_status,
)
from loopx.presentation.renderers.collaboration_status import (
    render_collaboration_status_markdown,
)

NOW = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)


def _todo(
    index: int,
    *,
    title: str | None = None,
    claimed_by: str = "agent-example",
) -> dict[str, Any]:
    return {
        "todo_id": f"todo_example_{index}",
        "priority": "P0",
        "status": "open",
        "title": title or f"Deliver collaboration milestone {index}",
        "claimed_by": claimed_by,
        "task_repository": "git:example.com/example/project",
    }


def _status_payload(
    *,
    agent_open: int = 3,
    compact_agent_open: int | None = None,
    agent_items: list[dict[str, Any]] | None = None,
    truth_writable: bool = False,
) -> dict[str, Any]:
    items = agent_items if agent_items is not None else [_todo(1), _todo(2)]
    compact_open = agent_open if compact_agent_open is None else compact_agent_open
    return {
        "ok": True,
        "attention_queue": {
            "item_count": 1,
            "items": [
                {
                    "goal_id": "example-goal",
                    "status": "working",
                    "waiting_on": "agent",
                    "recommended_action": "Finish the next verified milestone.",
                    "user_todos": {"open_count": 0},
                    "agent_todos": {"open_count": agent_open},
                    "project_asset": {
                        "user_todos": {"open": 0},
                        "agent_todos": {"open": compact_open},
                    },
                    "goal_channel_projection": {
                        "schema_version": "goal_channel_projection_v0",
                        "goal_id": "example-goal",
                        "mode": "read_only",
                        "display_name": "Example delivery goal",
                        "latest_status": "working",
                        "waiting_on": "agent",
                        "next_action": "Finish the next verified milestone.",
                        "user_todos": [],
                        "agent_todos": items,
                        "open_gates": [],
                        "truth_contract": {
                            "event_ledger_is_source_of_truth": True,
                            "projection_is_writable": truth_writable,
                            "write_authority": "none",
                        },
                    },
                }
            ],
        },
    }


def _build(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return build_collaboration_status(
        payload,
        goal_id="example-goal",
        now=NOW,
        snapshot_generated_at="2026-08-19T09:59:30Z",
        **kwargs,
    )


def test_projection_keeps_peer_context_and_exact_open_counts() -> None:
    packet = _build(_status_payload())

    assert packet["schema_version"] == "loopx_collaboration_status_v0"
    assert packet["visibility"] == "internal_collaboration"
    assert packet["publishable"] is True
    assert packet["freshness"]["state"] == "fresh"
    assert packet["todos"]["agent"] == {
        "open_count": 3,
        "visible_count": 2,
        "truncated": True,
        "items": [_todo(1), _todo(2)],
    }
    rendered = render_collaboration_status_markdown(packet)
    assert "Example delivery goal" in rendered
    assert "Deliver collaboration milestone 1" in rendered
    assert "agent-example" in rendered
    assert "todo_example_1" in rendered
    assert "git:example.com/example/project" in rendered


def test_projection_fails_closed_when_todo_counts_conflict() -> None:
    packet = _build(_status_payload(compact_agent_open=2))

    assert packet["publishable"] is False
    assert {item["code"] for item in packet["blockers"]} == {
        "agent_todo_count_conflict"
    }
    assert "agent_todo_count_conflict" in render_collaboration_status_markdown(packet)


def test_projection_fails_closed_when_snapshot_is_stale() -> None:
    packet = build_collaboration_status(
        _status_payload(),
        goal_id="example-goal",
        now=NOW,
        snapshot_generated_at="2026-08-19T09:00:00Z",
        max_age_seconds=300,
    )

    assert packet["publishable"] is False
    assert packet["freshness"]["state"] == "stale"
    assert [item["code"] for item in packet["blockers"]] == ["snapshot_stale"]


def test_projection_redacts_secrets_and_paths_without_hiding_counts() -> None:
    secret_title = "Rotate app_secret=synthetic-secret-value"
    local_owner = "/" + "home/example/private-agent"
    packet = _build(
        _status_payload(
            agent_open=1,
            agent_items=[_todo(1, title=secret_title, claimed_by=local_owner)],
        )
    )

    assert packet["publishable"] is True
    assert packet["todos"]["agent"]["open_count"] == 1
    assert packet["todos"]["agent"]["visible_count"] == 0
    assert packet["todos"]["agent"]["truncated"] is True
    assert "todos.agent.items[].title" in packet["redacted_fields"]
    serialized = repr(packet)
    assert secret_title not in serialized
    assert local_owner not in serialized


def test_projection_rejects_a_writable_truth_contract() -> None:
    packet = _build(_status_payload(truth_writable=True))

    assert packet["publishable"] is False
    assert [item["code"] for item in packet["blockers"]] == ["truth_contract_invalid"]


def test_status_cli_registers_collaboration_projection_options() -> None:
    args = build_parser().parse_args(
        [
            "status",
            "--goal-id",
            "example-goal",
            "--collaboration",
            "--collaboration-max-age-seconds",
            "90",
        ]
    )

    assert args.collaboration is True
    assert args.goal_id == "example-goal"
    assert args.collaboration_max_age_seconds == 90
