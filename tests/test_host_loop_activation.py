from __future__ import annotations

import pytest

from loopx.heartbeat_prompt import (
    build_heartbeat_prompt,
    uses_native_goal_host_loop,
)
from loopx.host_loop_activation import (
    AgentTypeError,
    agent_type_for_host_surface,
    build_host_loop_activation_packet,
    normalize_agent_type,
    scheduler_command_binding_for_agent_type,
)
from loopx.project_prompt import render_accountable_progress_refresh_command


def test_codex_ide_plugin_is_an_exact_host_type_with_visible_goal_activation() -> None:
    assert normalize_agent_type("codex-ide-plugin") == "codex-ide-plugin"
    assert normalize_agent_type("VSCode Codex") == "codex-ide-plugin"
    assert normalize_agent_type("codex-ide") == "codex-ide-plugin"
    assert agent_type_for_host_surface("codex-ide-plugin") == "codex-ide-plugin"
    assert agent_type_for_host_surface("codex-ide") == "codex-ide-plugin"
    assert agent_type_for_host_surface("codex-app") == "codex-app"
    assert agent_type_for_host_surface("codex-cli-tui") == "codex-cli"
    assert normalize_agent_type("Open Code") == "opencode"
    assert agent_type_for_host_surface("opencode") == "opencode"
    assert agent_type_for_host_surface("ark-managed-agent") == "ark-managed-agent"

    packet = build_host_loop_activation_packet(
        agent_type="codex-ide-plugin",
        goal_id="fixture-goal",
        agent_id="codex-fixture",
        registered_agents=["codex-fixture"],
    )

    assert packet["host_surface"] == "codex_ide_visible_goal_mode"
    assert packet["activation_method"] == "set_visible_goal"
    assert packet["host_mutation"]["owner"] == "Codex IDE plugin composer"
    assert packet["host_mutation"]["host_command"] == "/goal <task_body>"
    assert "automation_update" not in str(packet)
    assert (
        "--runtime-profile codex_cli"
        in packet["commands"]["heartbeat_prompt"]
    )
    assert " -H " not in packet["commands"]["heartbeat_prompt"]
    assert " -O " not in packet["commands"]["heartbeat_prompt"]
    assert " -M " not in packet["commands"]["heartbeat_prompt"]


@pytest.mark.parametrize(
    ("agent_type", "runtime_profile"),
    (
        ("ark-managed-agent", "ark_managed_agent_goal"),
        ("codex-app", "codex_app_heartbeat"),
        ("codex-app-ssh", "codex_app_ssh_goal"),
        ("codex-cli", "codex_cli"),
        ("codex-ide-plugin", "codex_cli"),
        ("claude-code", "claude_code"),
        ("opencode", "generic_cli"),
    ),
)
def test_first_class_hosts_bind_one_runtime_profile(
    agent_type: str,
    runtime_profile: str,
) -> None:
    assert scheduler_command_binding_for_agent_type(agent_type) == {
        "runtime_profile": runtime_profile
    }


@pytest.mark.parametrize(
    ("runtime_profile", "expected"),
    (
        ("ark_managed_agent_goal", True),
        ("codex_app_ssh_goal", True),
        ("codex_cli", True),
        ("codex_app_heartbeat", False),
        ("claude_code", False),
    ),
)
def test_native_goal_host_family_is_profile_driven(
    runtime_profile: str,
    expected: bool,
) -> None:
    assert uses_native_goal_host_loop(
        runtime_profile=runtime_profile,
        scheduler_execution_context=None,
    ) is expected


@pytest.mark.parametrize(
    "runtime_profile",
    ("ark_managed_agent_goal", "codex_app_ssh_goal"),
)
def test_goal_hosts_attribute_spend_to_current_progress_refresh(
    runtime_profile: str,
) -> None:
    payload = build_heartbeat_prompt(
        goal_id="goal-spend-attribution-fixture",
        thin=True,
        runtime_profile=runtime_profile,
    )
    task_body = payload["task_body"]
    refresh_command = f"`{payload['progress_refresh_state_command']}`"
    spend_command = f"`{payload['quota_spend_command']}`"

    assert task_body.index(refresh_command) < task_body.index(spend_command)
    assert "<PUBLIC_SAFE_PROGRESS_CLASSIFICATION>" in refresh_command
    assert "<ACTUAL_DELIVERY_BATCH_SCALE>" in refresh_command
    assert "<ACTUAL_DELIVERY_OUTCOME>" in refresh_command
    assert "--delivery-batch-scale multi_surface" not in refresh_command
    assert "--delivery-outcome outcome_progress" not in refresh_command
    normalized_task_body = " ".join(task_body.split())
    assert (
        "never default or upgrade them to `multi_surface` / `outcome_progress`"
        in normalized_task_body
    )


@pytest.mark.parametrize(
    "runtime_profile",
    ("ark_managed_agent_goal", "codex_app_ssh_goal"),
)
def test_goal_hosts_share_narrow_runtime_skill_routing(
    runtime_profile: str,
) -> None:
    payload = build_heartbeat_prompt(
        goal_id="goal-runtime-routing-fixture",
        thin=True,
        runtime_profile=runtime_profile,
    )
    task_body = " ".join(payload["task_body"].split())

    assert (
        "Normal turns use CLI `interaction_contract`; use `loopx-project` for "
        "lifecycle/registry and `loopx-self-repair` for runtime/projection drift."
        in task_body
    )
    assert "a segment is progress, not a new Goal boundary" in task_body
    assert "do not create a successor host Goal merely to continue" in task_body


def test_native_codex_goal_wait_rule_matches_blocked_resume_contract() -> None:
    ssh_body = build_heartbeat_prompt(
        goal_id="ssh-wait-fixture",
        thin=True,
        runtime_profile="codex_app_ssh_goal",
    )["task_body"]
    cli_body = build_heartbeat_prompt(
        goal_id="cli-wait-fixture",
        thin=True,
        runtime_profile="codex_cli",
    )["task_body"]
    managed_body = build_heartbeat_prompt(
        goal_id="managed-wait-fixture",
        thin=True,
        runtime_profile="ark_managed_agent_goal",
    )["task_body"]

    for body in (ssh_body, cli_body):
        assert "call `update_goal` with `status=blocked`" in body
        assert "Only user `/goal resume`" in body
        assert "reactivates it; rerun quota after resume" in body
    assert "call `update_goal` with `status=blocked`" not in managed_body


@pytest.mark.parametrize(
    ("runtime_profile", "expected_host"),
    (
        ("ark_managed_agent_goal", "Ark Managed Agent goal prompt"),
        ("codex_app_ssh_goal", "visible Codex /goal task body"),
        ("codex_cli", "visible Codex /goal task body"),
    ),
)
def test_native_goal_budget_error_names_the_actual_host(
    runtime_profile: str,
    expected_host: str,
) -> None:
    with pytest.raises(ValueError, match=expected_host):
        build_heartbeat_prompt(
            goal_id="oversized-native-goal",
            thin=True,
            runtime_profile=runtime_profile,
            permission_rule="x" * 4_000,
        )


def test_accountable_refresh_preserves_explicit_validated_turn_semantics() -> None:
    command = render_accountable_progress_refresh_command(
        "validated-turn-fixture",
        classification="contract_only_preparation",
        delivery_batch_scale="single_surface",
        delivery_outcome="surface_only",
    )

    assert "--classification contract_only_preparation" in command
    assert "--delivery-batch-scale single_surface" in command
    assert "--delivery-outcome surface_only" in command
    assert "multi_surface" not in command
    assert "outcome_progress" not in command


def test_codex_app_activation_uses_narrow_runtime_profile() -> None:
    packet = build_host_loop_activation_packet(
        agent_type="codex-app",
        goal_id="fixture-goal",
        agent_id="codex-fixture",
        registered_agents=["codex-fixture"],
    )

    command = packet["commands"]["heartbeat_prompt"]
    assert "--codex-app" in command
    assert "--runtime-profile" not in command
    assert "--host-surface" not in command
    assert "--scheduler-owner" not in command
    assert "--execution-mode" not in command


def test_codex_app_thin_prompt_embeds_profile_only_in_quota_command() -> None:
    prompt = build_heartbeat_prompt(
        goal_id="fixture-goal",
        thin=True,
        runtime_profile="codex_app_heartbeat",
    )

    assert "--codex-app" in prompt["quota_guard_command"]
    assert "--codex-app" in prompt["task_body"]
    assert "host_surface" not in prompt["task_body"]
    assert "scheduler_owner" not in prompt["task_body"]
    assert "compact_prompt_command" not in prompt
    assert "brief_prompt_command" not in prompt
    assert prompt["interface_budget"]["within_budget"] is True


def test_opencode_activation_uses_bridge_tool_and_generic_cli_quota() -> None:
    packet = build_host_loop_activation_packet(
        agent_type="opencode",
        goal_id="fixture-goal",
        agent_id="opencode-fixture",
        registered_agents=["opencode-fixture"],
    )

    assert packet["host_surface"] == "opencode_visible_goal_mode"
    assert packet["activation_method"] == "activate_loopx_opencode_goal_bridge"
    assert packet["host_mutation"]["host_tool"] == "loopx_goal_activate"
    assert packet["setup_command"].endswith(
        "--surface opencode --with-goal-bridge"
    )
    assert "--runtime-profile generic_cli" in packet["commands"]["heartbeat_prompt"]


def test_ambiguous_codex_requires_app_ide_or_cli_selection() -> None:
    with pytest.raises(AgentTypeError) as caught:
        normalize_agent_type("codex")

    assert caught.value.suggestions == [
        "codex-app",
        "codex-app-ssh",
        "codex-ide-plugin",
        "codex-cli",
    ]
