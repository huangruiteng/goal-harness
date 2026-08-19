"""Hermetic fake dsh runner for the goal-mode adapter tests.

Exposes the ``run_dsh_turn`` keyword contract of
``loopx.dsh_goal_mode.turn_host_adapter`` without a real DeepSeek Harness
SDK/runtime or network access. Not a pytest module (no ``test_`` prefix).
"""

from __future__ import annotations

import json


def run_dsh_turn(
    *,
    prompt: str,
    session_id: str,
    workspace: str,
    session_root: str,
    provider: str,
    model: str,
    max_tokens: int | None,
    cordis: str | None,
    runtime_bin: str | None,
    request_timeout_seconds: float | None,
) -> str:
    assert prompt, "the adapter must deliver the bounded task body"
    assert session_id, "the adapter must key the dsh session"
    return json.dumps(
        {
            "result_kind": "validated_progress",
            "classification": "fake dsh typed result",
            "summary": "one bounded fake work segment",
            "recommended_action": "validate the fake typed result",
            "next_action": "run the LoopX validator",
            "vision_unchanged_reason": "the fake runner never replans",
        }
    )
