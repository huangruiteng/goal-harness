from __future__ import annotations

import pytest

from loopx.control_plane.heartbeat.agent import (
    agent_prompt_command_args,
    agent_profile_scopes,
    normalize_agent_scopes,
)
from loopx.control_plane.heartbeat.budget import (
    build_interface_budget,
    heartbeat_prompt_mode,
    prompt_budget_text,
)
from loopx.control_plane.heartbeat.host import (
    uses_ark_managed_agent_goal_host,
    uses_native_goal_host_loop,
)
from loopx.control_plane.heartbeat.visible_goal import (
    build_visible_goal_initial_runtime_capability_projection,
    validate_visible_goal_policy_rule,
)
from loopx.heartbeat_prompt import (
    build_heartbeat_prompt,
    render_heartbeat_prompt_markdown,
)


def test_heartbeat_prompt_mode_defaults_to_thin() -> None:
    assert heartbeat_prompt_mode() == "thin"
    assert heartbeat_prompt_mode(full=True) == "full"
    assert heartbeat_prompt_mode(compact=True) == "compact"
    assert heartbeat_prompt_mode(brief=True) == "brief"
    assert heartbeat_prompt_mode(thin=True) == "thin"


def test_prompt_budget_text_redacts_goal_and_active_state() -> None:
    rendered = prompt_budget_text(
        "goal loopx-meta at state file",
        goal_id="loopx-meta",
        active_state="file",
    )
    assert "<GOAL_ID>" in rendered
    assert "<ACTIVE_STATE>" in rendered
    assert "loopx-meta" not in rendered
    assert "file" not in rendered


def test_interface_budget_uses_visible_goal_mode() -> None:
    budget = build_interface_budget(
        task_body="short task body",
        goal_id="loopx-meta",
        active_state="active",
        native_goal_host=True,
    )
    assert budget["mode"] == "visible_goal"
    assert budget["max_chars"] == 4000
    assert budget["within_budget"] is True


def test_agent_scope_normalization_dedupes_and_rejects_angle_brackets() -> None:
    assert normalize_agent_scopes(["a b", "a  b", "c"]) == ["a b", "c"]
    with pytest.raises(ValueError, match="angle brackets"):
        normalize_agent_scopes(["bad<scope>"])


def test_agent_profile_scopes_reads_common_profile_keys() -> None:
    profile = {"scope_summary": "one", "default_scopes": ["two three"]}
    assert agent_profile_scopes(profile) == ["one", "two three"]


def test_agent_prompt_command_args_quotes_scopes() -> None:
    args = agent_prompt_command_args(
        agent_id="codex-main-control",
        agent_scopes=["peer task claims"],
    )
    assert "--agent-id codex-main-control" in args
    assert "--agent-scope 'peer task claims'" in args


def test_host_detection_prefers_runtime_profile() -> None:
    assert (
        uses_native_goal_host_loop(
            runtime_profile="codex_cli",
            scheduler_execution_context=None,
        )
        is True
    )
    assert (
        uses_native_goal_host_loop(
            runtime_profile="generic_cli",
            scheduler_execution_context=None,
        )
        is False
    )
    assert (
        uses_ark_managed_agent_goal_host(
            runtime_profile="ark_managed_agent_goal",
            scheduler_execution_context=None,
        )
        is True
    )


def test_visible_goal_capability_projection_filters_control_vocabulary() -> None:
    projection = build_visible_goal_initial_runtime_capability_projection(
        ["loop", "network", "external_evidence_poll"]
    )
    assert projection is not None
    assert "loop" not in projection["capabilities"]
    assert projection["capabilities"] == ["network", "external_evidence_poll"]
    assert projection["scope"] == "visible_goal_session"


def test_visible_goal_policy_rejects_heartbeat_only_vocabulary() -> None:
    with pytest.raises(ValueError, match="heartbeat-only"):
        validate_visible_goal_policy_rule(
            field="permission_rule",
            value="use rrule now",
        )


def test_public_facade_still_builds_and_renders_prompts() -> None:
    payload = build_heartbeat_prompt(goal_id="loopx-meta")
    assert payload["ok"] is True
    assert payload["goal_id"] == "loopx-meta"
    assert payload["task_body"]
    assert render_heartbeat_prompt_markdown(payload)
