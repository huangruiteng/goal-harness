"""Regression tests for the heartbeat notify/execution-obligation wording.

The short notification rule used to read "DONT_NOTIFY=quiet", which agents can
misread as "do nothing". The rule must qualify DONT_NOTIFY as an output-level
signal only and keep `execution_obligation.must_attempt_work` as the authority
for whether a bounded slice must run.
"""

from __future__ import annotations

from loopx.control_plane.heartbeat.rules import HEARTBEAT_NOTIFICATION_RULE_SHORT
from loopx.control_plane.heartbeat.task_body import (
    render_brief_heartbeat_task_body,
    render_thin_heartbeat_task_body,
)


def test_short_rule_qualifies_dont_notify_as_output_only() -> None:
    rule = HEARTBEAT_NOTIFICATION_RULE_SHORT
    assert "DONT_NOTIFY" in rule
    assert "OUTPUT only" in rule
    # The old ambiguous mapping must be gone.
    assert "DONT_NOTIFY=quiet." not in rule
    assert "execution_obligation.must_attempt_work=true" in rule
    assert "must_attempt_work=false" in rule


def test_rendered_task_bodies_keep_execution_obligation_authority() -> None:
    kwargs = dict(
        goal_id="fixture-goal",
        active_state="active",
        cli_preflight="",
        pr_review_pre_quota_command="",
        quota_guard_command="loopx quota should-run",
        quota_spend_command="",
        refresh_state_command="",
        progress_refresh_state_command="",
        material_queue_rule="",
        permission_rule="",
        cli_bin="loopx",
        agent_scope_instruction="",
        expanded_prompt_command="",
        compact_prompt_command="",
        brief_prompt_command="",
        thin_prompt_command="",
    )
    for renderer in (render_thin_heartbeat_task_body, render_brief_heartbeat_task_body):
        body = renderer(**kwargs)
        assert "execution_obligation.must_attempt_work" in body
        assert "OUTPUT only" in body
        # A bare "DONT_NOTIFY=quiet" no-op mapping must never appear in the prompt.
        assert "DONT_NOTIFY=quiet." not in body
