from __future__ import annotations

from pathlib import Path

from loopx.agent_onboarding import (
    REQUIRED_HOST_SKILL_IDS,
    _skill_delivery_contract,
)
from loopx.control_plane.testing.canary_harness import (
    run_json_cli,
    write_fixture_registry,
)
from loopx.doctor import collect_doctor
from loopx.heartbeat_prompt import build_heartbeat_prompt
from loopx.host_loop_activation import (
    agent_type_uses_host_managed_skills,
    build_host_loop_activation_packet,
)


CONTINUITY_GOAL_ID = "managed-agent-continuity-fixture"
CONTINUITY_AGENT_ID = "managed-agent"
CONTINUITY_TODO_ID = "todo_aaaaaaaaaaaa"


def _goal_prompt() -> dict:
    return build_heartbeat_prompt(
        goal_id="managed-agent-fixture",
        active_state=Path("/workspace/ACTIVE_GOAL_STATE.md"),
        thin=True,
        runtime_profile="ark_managed_agent_goal",
    )


def test_goal_prompt_is_one_transport_independent_activation() -> None:
    local_development = _goal_prompt()
    cloud = _goal_prompt()
    normalized = " ".join(local_development["task_body"].split())

    assert local_development["task_body"] == cloud["task_body"]
    assert len(local_development["task_body"]) <= 4_000
    assert "in one Goal activation" in normalized
    assert "Goal runtime owns continuation and inner iterations" in normalized
    assert "goal loop, not automation" in normalized
    assert "invoke LoopX Turn" in normalized
    assert "choose the highest-priority in-scope unblocked agent todo" in normalized
    assert "Honor claims/leases, blocker-push and recovery obligations" in normalized
    assert "refresh the accountable progress record before spending" in normalized


def test_goal_prompt_projects_goal_only_host_contract() -> None:
    payload = _goal_prompt()

    assert payload["runtime_profile"] == "ark_managed_agent_goal"
    assert payload["host_contract"] == {
        "schema_version": "loopx_ark_managed_agent_goal_host_v0",
        "host_kind": "ark-managed-agent",
        "activation_mode": "goal_once",
        "prompt_family": "loopx_goal_prompt_v0",
        "policy_source": "quota_should_run.interaction_contract",
        "transport_contract": "goal_prompt_v0",
        "goal_runtime_owns_continuation": True,
        "loopx_turn_driver_required": False,
        "session_state_authoritative": False,
        "runtime_capability_reentry": {
            "source_ref": (
                "quota_should_run.interaction_contract.cli_channel."
                "runtime_capability_reentry"
            ),
            "cli_projection_ref": "quota_should_run.runtime_capability_reentry",
            "packet_schema_version": "runtime_capability_reentry_v0",
            "delivery_channel": "quota_tool_result",
            "goal_prompt_mutated": False,
            "session_scoped": True,
            "durable_grant_written": False,
        },
    }
    assert "--runtime-profile ark_managed_agent_goal" in payload["task_body"]
    assert "runtime_capability_reentry_v0" not in payload["task_body"]
    assert "Before the first quota guard" not in payload["task_body"]
    assert "--available-capability <name>" not in payload["task_body"]


def test_host_activation_submits_one_goal_without_turn_or_automation() -> None:
    packet = build_host_loop_activation_packet(
        agent_type="ark-managed-agent",
        goal_id="managed-agent-fixture",
        agent_id="managed-agent",
        registered_agents=["managed-agent"],
    )

    assert packet["activation_method"] == "submit_goal_once"
    assert packet["host_surface"] == "ark_managed_agent_goal_mode"
    assert packet["host_mutation"]["transport_contract"] == "goal_prompt_v0"
    assert packet["host_mutation"]["prompt_field"] == "task_body"
    assert any(
        "runtime_capability_reentry_v0" in step and "do not rewrite task_body" in step
        for step in packet["activation_steps"]
    )
    assert packet["commands"]["heartbeat_prompt"].endswith(
        "--runtime-profile ark_managed_agent_goal"
    )
    assert "automation_update" not in str(packet)
    assert "loopx turn run-once" not in str(packet).lower()


def test_host_requires_host_managed_loopx_skill_delivery() -> None:
    contract = _skill_delivery_contract("ark-managed-agent")

    assert contract["mode"] == "host_managed"
    assert contract["owner"] == "loopx_install_script"
    assert contract["required_skill_ids"] == REQUIRED_HOST_SKILL_IDS
    assert contract["host_readback_required"] is True
    assert contract["codex_skills_root_required"] is False
    assert contract["preferred_delivery"] == "fixed_install_script"
    assert contract["install_script"] == "scripts/install-local.sh"
    assert contract["skills_dir_env"] == "LOOPX_SKILLS_DIR"
    assert contract["target_layout"] == "./.agents/skills"
    assert agent_type_uses_host_managed_skills("ark-managed-agent") is True


def test_doctor_checks_host_readback_instead_of_codex_skill_root() -> None:
    payload = collect_doctor(agent_type="ark-managed-agent")

    assert payload["skill_delivery"]["mode"] == "host_managed"
    assert payload["skill_delivery"]["owner"] == "loopx_install_script"
    assert payload["skill_delivery"]["codex_skills_root_applicable"] is False
    skill_checks = {
        item["id"]: item for item in payload["checks"] if item["id"].startswith("installed_")
    }
    assert skill_checks
    assert all(item["applicable"] is False for item in skill_checks.values())


def _write_continuity_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    runtime = tmp_path / "runtime"
    state = (
        project
        / ".codex"
        / "goals"
        / CONTINUITY_GOAL_ID
        / "ACTIVE_GOAL_STATE.md"
    )
    state.parent.mkdir(parents=True)
    state.write_text(
        "\n".join(
            [
                "---",
                "status: active",
                "updated_at: 2026-07-29T00:00:00+00:00",
                "---",
                "",
                "# Managed Agent continuity fixture",
                "",
                "## Agent Todo",
                "",
                "- [ ] [P0] Continue the public continuity qualification.",
                (
                    "  <!-- loopx:todo "
                    f"todo_id={CONTINUITY_TODO_ID} "
                    "status=open task_class=advancement_task "
                    "action_kind=qualification "
                    f"claimed_by={CONTINUITY_AGENT_ID} priority=P0 -->"
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    registry = project / ".loopx" / "registry.json"
    write_fixture_registry(
        project=project,
        runtime_root=runtime,
        registry_path=registry,
        goal_id=CONTINUITY_GOAL_ID,
        domain="managed-agent-continuity",
        adapter_kind="harness_self_improvement",
        registered_agents=[CONTINUITY_AGENT_ID],
        quota_allowed_slots=None,
    )
    return project, runtime, registry


def _fresh_host_quota_read(
    *,
    project: Path,
    runtime: Path,
    registry: Path,
) -> dict:
    return run_json_cli(
        "quota",
        "should-run",
        "--goal-id",
        CONTINUITY_GOAL_ID,
        "--agent-id",
        CONTINUITY_AGENT_ID,
        "--runtime-profile",
        "ark_managed_agent_goal",
        "--scan-root",
        str(project),
        registry_path=registry,
        runtime_root=runtime,
    )


def test_fresh_host_reconstructs_frontier_from_durable_loopx_state(
    tmp_path: Path,
) -> None:
    project, runtime, registry = _write_continuity_fixture(tmp_path)

    first_host = _fresh_host_quota_read(
        project=project,
        runtime=runtime,
        registry=registry,
    )
    assert first_host["should_run"] is True
    assert first_host["selected_todo"]["todo_id"] == CONTINUITY_TODO_ID

    run_json_cli(
        "todo",
        "update",
        "--goal-id",
        CONTINUITY_GOAL_ID,
        "--todo-id",
        CONTINUITY_TODO_ID,
        "--agent-id",
        CONTINUITY_AGENT_ID,
        "--note",
        "phase A validated; resume from the durable frontier",
        registry_path=registry,
        runtime_root=runtime,
    )

    # run_json_cli launches a fresh Python process for each read. This models a
    # replacement host session: only the shared registry/runtime/state paths
    # survive, while no in-memory host object or opaque session handle does.
    replacement_host = _fresh_host_quota_read(
        project=project,
        runtime=runtime,
        registry=registry,
    )
    todo_readback = run_json_cli(
        "todo",
        "list",
        "--goal-id",
        CONTINUITY_GOAL_ID,
        "--agent-id",
        CONTINUITY_AGENT_ID,
        registry_path=registry,
        runtime_root=runtime,
    )

    assert replacement_host["should_run"] is True
    assert replacement_host["selected_todo"]["todo_id"] == CONTINUITY_TODO_ID
    selected = next(
        item
        for item in todo_readback["agent_todos"]["items"]
        if item["todo_id"] == CONTINUITY_TODO_ID
    )
    assert selected["note"] == "phase A validated; resume from the durable frontier"
