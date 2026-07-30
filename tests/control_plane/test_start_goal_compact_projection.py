from __future__ import annotations

import contextlib
import io
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from loopx.bootstrap_command_pack import (
    GUIDED_COMMAND_PACK_PROJECTION_SCHEMA_VERSION,
    build_start_goal_guided_packet,
    render_start_goal_guided_markdown,
)
from loopx.cli import main as cli_main

GOAL_ID = "guided-projection-goal"
AGENT_ID = "codex-guided-projection"
GOAL_TEXT = "Ship a bounded public issue triage workflow."


def _write_connected_project(root: Path) -> Path:
    project = root / "project"
    state_file = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("# Active Goal State\n", encoding="utf-8")
    registry = project / ".loopx" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state_file.relative_to(project)),
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return project


def _build(project: Path, *, include_detail: bool) -> dict[str, Any]:
    return build_start_goal_guided_packet(
        project=project,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        cli_bin="loopx",
        host_surface="codex-app",
        goal_text=GOAL_TEXT,
        available_capabilities=["network"],
        include_command_pack_detail=include_detail,
    )


def _host_shadow_document(payload: dict[str, Any]) -> dict[str, Any]:
    command_pack = payload["command_pack"]
    transaction = payload["guided_transaction"]
    return {
        "schema_version": payload["schema_version"],
        "project": payload["project"],
        "command_cwd_source": transaction["command_cwd_source"],
        "goal_id": payload["goal_id"],
        "agent_id": payload["agent_id"],
        "host_surface": payload["host_surface"],
        "goal_text": payload["goal_text"],
        "recommended_next_step": payload["recommended_next_step"],
        "ordered_steps": transaction["ordered_steps"],
        "idempotency_policy": transaction["idempotency_policy"],
        "preserve_todos_policy": transaction["preserve_todos_policy"],
        "goal_start_contract": command_pack["goal_start_contract"],
        "commands": command_pack["commands"],
        "host_loop_activation": command_pack["host_loop_activation"],
        "safety_contract": payload["safety_contract"],
    }


def _resolve_pointer(payload: Any, pointer: str) -> Any:
    assert pointer.startswith("#/")
    current = payload
    for escaped_part in pointer[2:].split("/"):
        part = escaped_part.replace("~1", "/").replace("~0", "~")
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _invoke_detail_command(command: str) -> dict[str, Any]:
    argv = shlex.split(command)
    assert argv[0] == "loopx"
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = cli_main(argv[1:])
    assert exit_code == 0
    payload = json.loads(output.getvalue())
    assert isinstance(payload, dict)
    return payload


def test_default_projection_preserves_host_actions_and_json_anchors(
    tmp_path: Path,
) -> None:
    project = _write_connected_project(tmp_path)
    compact = _build(project, include_detail=False)
    detailed = _build(project, include_detail=True)

    assert set(compact) == set(detailed)
    assert _host_shadow_document(compact) == _host_shadow_document(detailed)
    assert compact["command_pack_detail_included"] is False
    assert detailed["command_pack_detail_included"] is True
    assert compact["guided_transaction"]["ordered_steps"][-1]["id"] == (
        "scheduler_ack_when_needed"
    )

    projection = compact["command_pack"]
    assert projection["schema_version"] == "loopx_bootstrap_command_pack_v0"
    assert (
        projection["projection_schema_version"]
        == GUIDED_COMMAND_PACK_PROJECTION_SCHEMA_VERSION
    )
    assert projection["projection_mode"] == "guided_start_compatibility"
    assert projection["commands"] == detailed["command_pack"]["commands"]
    assert (
        projection["host_loop_activation"]
        == detailed["command_pack"]["host_loop_activation"]
    )
    assert "message" not in projection
    assert "available_slash_commands" not in projection
    assert (
        projection["goal_start_contract"]
        == detailed["command_pack"]["goal_start_contract"]
    )
    assert projection["safety_contract"] == detailed["command_pack"]["safety_contract"]

    compatibility = compact["packet_summary"]["compatibility"]
    assert compatibility == {
        "legacy_fields_retained": False,
        "compact_projection_default": True,
        "removal_gate": "explicit_host_shadow_parity",
    }
    for ref in compact["packet_summary"]["detail_refs"].values():
        _resolve_pointer(compact, ref["json_pointer"])
    for ref in projection["packet_summary"]["detail_refs"].values():
        _resolve_pointer(projection, ref["json_pointer"])


def test_issue_fix_goal_projects_capability_guard_without_todo_fields(
    tmp_path: Path,
) -> None:
    project = _write_connected_project(tmp_path)
    payload = build_start_goal_guided_packet(
        project=project,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        cli_bin="loopx",
        host_surface="ark-managed-agent",
        goal_text=(
            "Autonomously deliver review-ready fixes for two distinct open "
            "repository issues in one long-running Goal."
        ),
        available_capabilities=["network"],
    )

    transaction = payload["guided_transaction"]
    assert transaction["command_cwd_source"] == "#/project"
    assert payload["project"] == str(project)
    route = transaction["selected_capability_route"]
    assert route == {
        "schema_version": "loopx_goal_capability_route_v0",
        "capability_id": "issue-fix",
        "selection_source": "explicit_goal_text",
        "selection_reason_code": "issue_fix_intent",
        "entry_command_key": "issue_fix_workflow_plan_template",
        "admission_command_key": "issue_fix_feasibility_template",
        "candidate_authority": "public_open_tracker_issue",
        "implementation_admission": {
            "status": "qualification_required",
            "state_owner": "issue_fix",
            "route_scope": "start_goal_bootstrap_only",
            "durable_reentry_fields": ["action_kind", "target_key"],
        },
        "activation_condition": (
            "after selecting a public issue candidate and before substantive "
            "implementation"
        ),
    }
    guard = transaction["ordered_steps"][2]
    assert guard["id"] == "qualify_selected_capability"
    assert guard["candidate_discovery_command_template"].startswith(
        "gh issue list "
    )
    assert guard["command_source"].endswith(
        "/commands/issue_fix_workflow_plan_template"
    )
    assert guard["admission_command_source"].endswith(
        "/commands/issue_fix_feasibility_template"
    )
    assert guard["durable_successor_source"] == (
        "admission_result.transition.projected_todo"
    )
    assert "exact successor Todo" in guard["completion_condition"]
    assert "command_template" not in guard
    assert "admission_command_template" not in guard
    commands = payload["command_pack"]["commands"]
    assert commands[route["entry_command_key"]].startswith(
        "loopx issue-fix workflow-plan "
    )
    assert commands[route["admission_command_key"]].startswith(
        "loopx issue-fix feasibility "
    )
    rendered = render_start_goal_guided_markdown(payload)
    assert "authority: open public issue; source clues are evidence only" in rendered
    assert "discover: `gh issue list " in rendered
    assert "loopx issue-fix workflow-plan " in rendered
    assert "loopx issue-fix feasibility " in rendered
    assert len(rendered.replace(str(project), "<project>")) <= 3_200
    todo_command = next(
        step["command_template"]
        for step in transaction["ordered_steps"]
        if step["id"] == "write_ordered_todos"
    )
    assert "--project ." in todo_command
    assert "--action-kind <action_kind>" in todo_command
    assert "[--target-key <target_key>]" in todo_command
    refresh_command = next(
        step["command"]
        for step in transaction["ordered_steps"]
        if step["id"] == "refresh_state"
    )
    assert "--project ." in refresh_command
    assert all(
        field not in todo_command
        for field in ("issue_url", "issue_number", "base_sha", "acceptance")
    )


def test_non_issue_goal_does_not_select_capability_route(tmp_path: Path) -> None:
    project = _write_connected_project(tmp_path)
    payload = build_start_goal_guided_packet(
        project=project,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        cli_bin="loopx",
        host_surface="ark-managed-agent",
        goal_text="Improve the public onboarding documentation.",
    )

    transaction = payload["guided_transaction"]
    assert "selected_capability_route" not in transaction
    assert transaction["ordered_steps"][-1]["id"] == "quota_guard"
    assert all(
        step["id"] != "scheduler_ack_when_needed"
        for step in transaction["ordered_steps"]
    )
    assert (
        payload["command_pack"]["goal_start_contract"]["selected_capability_route"]
        is None
    )
    referenced = build_start_goal_guided_packet(
        project=project,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        cli_bin="loopx",
        host_surface="ark-managed-agent",
        goal_text="Fix https://github.com/owner/repo/pull/42.",
    )
    assert (
        referenced["guided_transaction"]["selected_capability_route"][
            "selection_reason_code"
        ]
        == "public_issue_or_pr_reference"
    )
    for goal_text in (
        "Review https://github.com/owner/repo/pull/42.",
        "Merge https://github.com/owner/repo/pull/42 after checks pass.",
        "Monitor https://github.com/owner/repo/pull/42.",
        "Summarize https://github.com/owner/repo/issues/42.",
    ):
        unrelated = build_start_goal_guided_packet(
            project=project,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            cli_bin="loopx",
            host_surface="ark-managed-agent",
            goal_text=goal_text,
        )
        assert "selected_capability_route" not in unrelated["guided_transaction"]


def test_explicit_cold_path_restores_the_complete_command_pack(tmp_path: Path) -> None:
    project = _write_connected_project(tmp_path)
    compact = _build(project, include_detail=False)
    restored = _invoke_detail_command(compact["command_pack"]["detail_command"])

    assert restored["command_pack_detail_included"] is True
    assert "commands" in restored["command_pack"]
    assert "message" in restored["command_pack"]
    assert "host_loop_activation" in restored["command_pack"]
    assert "available_slash_commands" in restored["command_pack"]
    assert _host_shadow_document(restored) == _host_shadow_document(compact)
    assert restored["packet_summary"]["compatibility"] == {
        "legacy_fields_retained": True,
        "compact_projection_default": False,
        "removal_gate": "explicit_host_shadow_parity",
    }


def test_projection_materially_reduces_repetition_without_hiding_measurement(
    tmp_path: Path,
) -> None:
    project = _write_connected_project(tmp_path)
    compact = _build(project, include_detail=False)
    detailed = _build(project, include_detail=True)
    compact_json = json.dumps(compact, ensure_ascii=False, sort_keys=True)
    detailed_json = json.dumps(detailed, ensure_ascii=False, sort_keys=True)

    assert len(compact_json) <= int(len(detailed_json) * 0.65)
    compact_duplication = compact["packet_summary"]["duplication_measurement"]
    detailed_duplication = detailed["packet_summary"]["duplication_measurement"]
    assert compact_duplication["objective_content"]["duplicate_occurrences"] <= 11
    assert compact_duplication["command_content"]["duplicate_occurrences"] <= 13
    assert (
        compact_duplication["objective_content"]["duplicate_occurrences"]
        < (detailed_duplication["objective_content"]["duplicate_occurrences"])
    )
    assert (
        compact_duplication["command_content"]["duplicate_occurrences"]
        < (detailed_duplication["command_content"]["duplicate_occurrences"])
    )


def test_projection_preserves_agent_identity_gate_actions(tmp_path: Path) -> None:
    project = _write_connected_project(tmp_path)
    registry_path = project / ".loopx" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["goals"][0]["coordination"]["registered_agents"].append(
        "codex-guided-reviewer"
    )
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    common = {
        "project": project,
        "goal_id": GOAL_ID,
        "agent_id": None,
        "cli_bin": "loopx",
        "host_surface": "codex-app",
        "goal_text": GOAL_TEXT,
        "available_capabilities": ["network"],
    }
    compact = build_start_goal_guided_packet(
        **common,
        include_command_pack_detail=False,
    )
    detailed = build_start_goal_guided_packet(
        **common,
        include_command_pack_detail=True,
    )

    assert compact["guided_transaction"]["blocked_by"] == "agent_identity_selection"
    assert _host_shadow_document(compact) == _host_shadow_document(detailed)


def test_projection_preserves_multi_goal_selection_actions(tmp_path: Path) -> None:
    project = _write_connected_project(tmp_path)
    registry_path = project / ".loopx" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    second_goal_id = "guided-projection-second-goal"
    second_state = (
        project / ".codex" / "goals" / second_goal_id / "ACTIVE_GOAL_STATE.md"
    )
    second_state.parent.mkdir(parents=True)
    second_state.write_text("# Second Active Goal State\n", encoding="utf-8")
    registry["goals"].append(
        {
            "id": second_goal_id,
            "status": "active",
            "repo": str(project),
            "state_file": str(second_state.relative_to(project)),
            "coordination": {
                "agent_model": "peer_v1",
                "registered_agents": ["codex-guided-second"],
            },
        }
    )
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    common = {
        "project": project,
        "goal_id": None,
        "agent_id": None,
        "cli_bin": "loopx",
        "host_surface": "codex-app",
        "goal_text": GOAL_TEXT,
        "available_capabilities": ["network"],
    }
    compact = build_start_goal_guided_packet(
        **common,
        include_command_pack_detail=False,
    )
    detailed = build_start_goal_guided_packet(
        **common,
        include_command_pack_detail=True,
    )

    assert compact["guided_transaction"]["blocked_by"] == "goal_selection"
    assert [step["id"] for step in compact["guided_transaction"]["ordered_steps"]] == [
        "inspect_connection",
        "select_goal",
    ]
    assert _host_shadow_document(compact) == _host_shadow_document(detailed)


def test_start_goal_keeps_the_requested_linked_worktree(
    tmp_path: Path,
    monkeypatch,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    subprocess.run(["git", "init"], cwd=primary, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "loopx@example.invalid"],
        cwd=primary,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "LoopX Test"],
        cwd=primary,
        check=True,
        capture_output=True,
    )
    (primary / "README.md").write_text("# primary\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"], cwd=primary, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=primary,
        check=True,
        capture_output=True,
    )

    worktree = tmp_path / "fresh-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "fresh-worktree", str(worktree)],
        cwd=primary,
        check=True,
        capture_output=True,
    )

    old_goal_id = "old-primary-goal"
    primary_registry = primary / ".loopx" / "registry.json"
    primary_registry.parent.mkdir(parents=True)
    old_goal = {
        "id": old_goal_id,
        "status": "active",
        "repo": str(primary),
        "state_file": f".codex/goals/{old_goal_id}/ACTIVE_GOAL_STATE.md",
    }
    primary_registry.write_text(
        json.dumps({"schema_version": "0.1", "goals": [old_goal]}, indent=2) + "\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "registry.global.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        **old_goal,
                        "source_registry": str(primary_registry),
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOOPX_RUNTIME_ROOT", str(runtime))

    payload = build_start_goal_guided_packet(
        project=worktree,
        goal_id=None,
        agent_id=None,
        cli_bin="loopx",
        host_surface="ark-managed-agent",
        goal_text=GOAL_TEXT,
        available_capabilities=["network"],
    )

    assert Path(payload["project"]).resolve() == worktree.resolve()
    assert payload["goal_id"] == "fresh-worktree-goal"
    alias = payload["project_connection"]["canonical_project_alias"]
    assert alias["applied"] is False
    assert alias["kind"] == "exact_project_route"
    connect_command = payload["command_pack"]["commands"][
        "goal_start_connect_if_needed"
    ]
    assert str(worktree.resolve()) in connect_command
    assert old_goal_id not in json.dumps(payload)


def test_cli_without_host_returns_read_only_host_selection_gate(
    tmp_path: Path,
) -> None:
    project = _write_connected_project(tmp_path)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = cli_main(
            [
                "--format",
                "json",
                "start-goal",
                "--guided",
                "--project",
                str(project),
                "--goal-id",
                GOAL_ID,
                "--agent-id",
                AGENT_ID,
                "--goal-text",
                GOAL_TEXT,
            ]
        )

    assert exit_code == 0
    payload = json.loads(output.getvalue())
    assert payload["guided_transaction"]["blocked_by"] == "host_surface_selection"
    assert payload["safety_contract"]["writes_registry"] is False
    choices = payload["host_surface_selection_gate"]["choices"]
    assert [choice["host_surface"] for choice in choices] == [
        "codex-app",
        "codex-app-ssh",
        "codex-ide-plugin",
        "codex-cli-tui",
        "claude-code",
        "opencode",
        "ark-managed-agent",
        "shell",
        "other-agent",
    ]
    ide = next(choice for choice in choices if choice["host_surface"] == "codex-ide-plugin")
    assert "--host-surface codex-ide-plugin" in ide["rerun_command"]


def test_ark_managed_agent_plans_todos_before_one_shot_goal_activation(
    tmp_path: Path,
) -> None:
    project = _write_connected_project(tmp_path)
    payload = build_start_goal_guided_packet(
        project=project,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        cli_bin="loopx",
        host_surface="ark-managed-agent",
        goal_text=GOAL_TEXT,
        available_capabilities=["network"],
    )

    ordered_step_ids = [
        step["id"] for step in payload["guided_transaction"]["ordered_steps"]
    ]
    activation = payload["command_pack"]["host_loop_activation"]
    inspect_step = payload["guided_transaction"]["ordered_steps"][0]

    assert ordered_step_ids.index("write_ordered_todos") < ordered_step_ids.index(
        "activate_host_loop"
    )
    assert inspect_step["command_source"] == "#/command_pack/canonical_cli_command"
    inspect_command = payload["command_pack"]["canonical_cli_command"]
    assert "--host-surface ark-managed-agent" in inspect_command
    assert "--available-capability network" in inspect_command
    assert f"--goal-text '{GOAL_TEXT}'" in inspect_command
    assert "preview the issue-fix route before todo writeback" not in payload["message"]
    assert activation["agent_type"] == "ark-managed-agent"
    assert activation["host_surface"] == "ark_managed_agent_goal_mode"
    assert activation["activation_method"] == "submit_goal_once"
    assert activation["host_mutation"]["transport_contract"] == "goal_prompt_v0"
    assert activation["host_mutation"]["prompt_field"] == "task_body"
    assert "--runtime-profile ark_managed_agent_goal" in (
        activation["commands"]["heartbeat_prompt"]
    )


def test_codex_ide_plugin_uses_visible_goal_and_preserves_compact_parity(
    tmp_path: Path,
) -> None:
    project = _write_connected_project(tmp_path)
    common = {
        "project": project,
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "cli_bin": "loopx",
        "host_surface": "codex-ide-plugin",
        "goal_text": GOAL_TEXT,
        "available_capabilities": ["network"],
    }
    compact = build_start_goal_guided_packet(
        **common,
        include_command_pack_detail=False,
    )
    detailed = build_start_goal_guided_packet(
        **common,
        include_command_pack_detail=True,
    )

    activation = compact["command_pack"]["host_loop_activation"]
    assert detailed["command_pack"]["agent_type"] == "codex-ide-plugin"
    assert activation["host_surface"] == "codex_ide_visible_goal_mode"
    assert activation["activation_method"] == "set_visible_goal"
    assert activation["host_mutation"]["host_command"] == "/goal <task_body>"
    assert _host_shadow_document(compact) == _host_shadow_document(detailed)

    legacy = build_start_goal_guided_packet(
        **{**common, "host_surface": "codex-ide"},
        include_command_pack_detail=True,
    )
    assert legacy["command_pack"]["agent_type"] == "codex-ide-plugin"
    assert legacy["command_pack"]["host_loop_activation"]["host_surface"] == (
        "codex_ide_visible_goal_mode"
    )
