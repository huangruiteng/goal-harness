from __future__ import annotations

import json

import pytest

from loopx.control_plane.runtime.agent_scoped_evidence_log import (
    build_agent_scoped_evidence_log,
)


@pytest.mark.parametrize(
    "unsafe_summary",
    [
        "access_key=should-not-surface",
        "secret-key:should-not-surface",
        "sk=should-not-surface",
        "/private/tmp/owner-only/evidence.json",
    ],
)
def test_evidence_log_reuses_the_shared_public_safety_boundary(
    unsafe_summary: str,
) -> None:
    payload = build_agent_scoped_evidence_log(
        goal_id="public-goal",
        agent_id="codex-agent",
        rollout_events=[
            {
                "agent_id": "codex-agent",
                "event_kind": "validation",
                "recorded_at": "2026-08-12T00:00:00Z",
                "summary": unsafe_summary,
            }
        ],
        history_runs=[],
    )

    assert unsafe_summary not in json.dumps(payload)
    assert payload["ledger"] == [
        {
            "source": "rollout_event_log",
            "recorded_at": "2026-08-12T00:00:00Z",
            "event_id": None,
            "event_kind": "validation",
            "agent_id": "codex-agent",
        }
    ]


def test_evidence_log_keeps_safe_compact_prose() -> None:
    payload = build_agent_scoped_evidence_log(
        goal_id="public-goal",
        agent_id="codex-agent",
        rollout_events=[
            {
                "agent_id": "codex-agent",
                "event_kind": "validation",
                "recorded_at": "2026-08-12T00:00:00Z",
                "summary": "authorization token label is safe as prose",
            }
        ],
        history_runs=[],
    )

    assert payload["ledger"][0]["summary"] == (
        "authorization token label is safe as prose"
    )
