from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_registry import registered_agent_ids_from_registry
from .bootstrap_command_pack import inspect_bootstrap_connection
from .capabilities.change_quality.policy import change_quality_goal_policy
from .host_loop_activation import (
    agent_type_uses_host_managed_skills,
    build_host_loop_activation_packet,
    normalize_agent_type,
    render_agent_type_catalog_markdown,
    scheduler_command_binding_for_agent_type,
)
from .project_prompt import (
    render_available_capability_args,
    render_codex_cli_no_clone_preflight,
    render_quota_guard_command,
    shell_arg,
)
from .registry import read_json, registry_goals


SCHEMA_VERSION = "loopx_agent_onboarding_v0"
HOST_SKILL_DELIVERY_SCHEMA_VERSION = "loopx_host_skill_delivery_v0"
REQUIRED_HOST_SKILL_IDS = [
    "loopx-project",
    "loopx-pr-review",
    "loopx-doc-registry",
    "loopx-self-repair",
]
CHANGE_QUALITY_SKILL_ID = "loopx-change-quality"


def _surface_install_command(agent_type: str, cli_bin: str) -> str | None:
    if agent_type in {"codex-app", "codex-app-ssh", "codex-ide-plugin", "codex-cli"}:
        return f"{shell_arg(cli_bin)} slash-commands --install --surface codex"
    if agent_type == "claude-code":
        return f"{shell_arg(cli_bin)} slash-commands --install --surface claude-code"
    if agent_type == "opencode":
        return (
            f"{shell_arg(cli_bin)} slash-commands --install --surface opencode "
            "--with-goal-bridge"
        )
    return None


def _project_skill_surface(agent_type: str) -> str | None:
    if agent_type in {
        "codex-app",
        "codex-app-ssh",
        "codex-ide-plugin",
        "codex-cli",
    }:
        return "codex"
    if agent_type == "claude-code":
        return "claude-code"
    if agent_type == "opencode":
        return "opencode"
    return None


def _project_skill_command(
    command: str,
    *,
    project: str,
    skill_id: str,
    surface: str,
    cli_bin: str,
    execute: bool = False,
) -> str:
    parts = [
        shell_arg(cli_bin),
        "project-skill",
        command,
        "--project",
        shell_arg(project),
        "--skill",
        shell_arg(skill_id),
        "--surface",
        shell_arg(surface),
    ]
    if execute:
        parts.append("--execute")
    return " ".join(parts)


def _skill_delivery_contract(
    agent_type: str,
    *,
    project: str = ".",
    cli_bin: str = "loopx",
    active_project_skill_ids: list[str] | None = None,
) -> dict[str, Any]:
    active_project_skills = list(dict.fromkeys(active_project_skill_ids or []))
    project_surface = _project_skill_surface(agent_type)
    project_skill_commands = []
    if project_surface:
        for skill_id in active_project_skills:
            project_skill_commands.append(
                {
                    "skill_id": skill_id,
                    "surface": project_surface,
                    "status": _project_skill_command(
                        "status",
                        project=project,
                        skill_id=skill_id,
                        surface=project_surface,
                        cli_bin=cli_bin,
                    ),
                    "preview_install": _project_skill_command(
                        "install",
                        project=project,
                        skill_id=skill_id,
                        surface=project_surface,
                        cli_bin=cli_bin,
                    ),
                    "apply_install": _project_skill_command(
                        "install",
                        project=project,
                        skill_id=skill_id,
                        surface=project_surface,
                        cli_bin=cli_bin,
                        execute=True,
                    ),
                }
            )
    if not agent_type_uses_host_managed_skills(agent_type):
        return {
            "schema_version": HOST_SKILL_DELIVERY_SCHEMA_VERSION,
            "mode": "surface_managed",
            "owner": "loopx_surface_installer",
            "codex_skills_root_required": agent_type.startswith("codex-"),
            "host_readback_required": False,
            "active_project_skill_ids": active_project_skills,
            "project_skill_commands": project_skill_commands,
        }
    required_skill_ids = [
        *REQUIRED_HOST_SKILL_IDS,
        *active_project_skills,
    ]
    ark_managed_agent = agent_type == "ark-managed-agent"
    return {
        "schema_version": HOST_SKILL_DELIVERY_SCHEMA_VERSION,
        "mode": "host_managed",
        "owner": "loopx_install_script" if ark_managed_agent else "custom_agent_host",
        "status": "pending_host_readback",
        "codex_skills_root_required": False,
        "required_for_cli_health": False,
        "required_for_loopx_workflow": True,
        "required_skill_ids": required_skill_ids,
        "active_project_skill_ids": active_project_skills,
        "delivery_options": [
            *(["fixed_install_script"] if ark_managed_agent else []),
            "host_skill_manifest",
            "prompt_injection",
        ],
        **(
            {
                "preferred_delivery": "fixed_install_script",
                "install_script": "scripts/install-local.sh",
                "skills_dir_env": "LOOPX_SKILLS_DIR",
                "target_layout": f"{project}/.agents/skills",
            }
            if ark_managed_agent
            else {}
        ),
        "source_repository": "https://github.com/huangruiteng/loopx",
        "source_directories": [
            f"skills/{skill_id}" for skill_id in required_skill_ids
        ],
        "source_contract": (
            "Use the same LoopX release or repository revision as the CLI when "
            "materializing skills or injecting equivalent SKILL.md instructions "
            "through the custom host."
        ),
        "host_readback_required": True,
        "readback_fields": [
            "integration_mode",
            "loaded_skill_ids",
            "source_revision",
        ],
        "success_criteria": [
            "the host reports which integration mode it selected",
            "the host reports every required LoopX skill id as loaded",
            "the host reports every active project skill id as loaded or injects its equivalent instructions",
            "the host reports the source revision or digest used for delivery",
            "no Codex-specific skill directory is assumed",
        ],
    }


def _bootstrap_pack_command(
    *,
    project: str,
    goal_id: str,
    agent_id: str | None,
    agent_type: str,
    cli_bin: str,
    task_text: str | None,
    available_capabilities: list[str] | None,
) -> str:
    surface_by_type = {
        "codex-app": "codex-app",
        "codex-app-ssh": "codex-app-ssh",
        "codex-ide-plugin": "codex-ide-plugin",
        "codex-cli": "codex-cli-tui",
        "claude-code": "claude-code",
        "opencode": "opencode",
        "manual": "shell",
        "other-agent": "worker-bridge",
    }
    parts = [
        shell_arg(cli_bin),
        "bootstrap-command-pack",
        "--project",
        shell_arg(project),
        "--goal-id",
        shell_arg(goal_id),
        "--host-surface",
        shell_arg(surface_by_type.get(agent_type, "worker-bridge")),
    ]
    if agent_id:
        parts.extend(["--agent-id", shell_arg(agent_id)])
    if task_text:
        parts.extend(["--goal-text", shell_arg(task_text)])
    for capability in available_capabilities or []:
        parts.extend(["--available-capability", shell_arg(capability)])
    return " ".join(parts)


def _start_instruction(agent_type: str) -> str:
    if agent_type == "codex-app":
        return "Use `$loopx <task>` or select the LoopX skill from `/skills`; Codex App should then create/update the heartbeat automation."
    if agent_type == "codex-app-ssh":
        return "Use `$loopx <task>` or select the LoopX skill from `/skills`; after todos are written, set `/goal <task_body>` in the visible Codex App task."
    if agent_type == "codex-ide-plugin":
        return "Use `$loopx <task>` or select the LoopX skill from `/skills`; after todos are written, set `/goal <task_body>` in the visible IDE plugin."
    if agent_type == "codex-cli":
        return "Use `$loopx <task>` or select the LoopX skill from `/skills`; after todos are written, set `/goal <task_body>` in the visible TUI."
    if agent_type == "claude-code":
        return "Run `/loopx <task>` to arm LoopX, then run native `/loop`."
    if agent_type == "opencode":
        return "Run `/loopx <task>`; after todo writeback, call `loopx_goal_activate` with the generated heartbeat task body."
    if agent_type == "manual":
        return "Use the CLI packet and wire an external scheduler, or run quota/status/todo commands manually."
    return (
        "Deliver the required LoopX skills through the custom host and verify its "
        "loaded-skill readback; then use the host's explicit LoopX command facade "
        "and wire its scheduler through this packet."
    )


def build_agent_onboarding_packet(
    *,
    project: Path,
    agent_type: str,
    goal_id: str | None = None,
    agent_id: str | None = None,
    cli_bin: str = "loopx",
    task_text: str | None = None,
    available_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    canonical_agent_type = normalize_agent_type(agent_type)
    inspection = inspect_bootstrap_connection(project, goal_id=goal_id)
    resolved_project = str(inspection["project"])
    resolved_goal_id = str(inspection["goal_id"])
    registry_path = Path(str(inspection["registry"]))
    registry = read_json(registry_path)
    goal = next(
        (
            item
            for item in registry_goals(registry)
            if str(item.get("id") or "") == resolved_goal_id
        ),
        {},
    )
    active_project_skill_ids = (
        [CHANGE_QUALITY_SKILL_ID]
        if change_quality_goal_policy(goal)["enabled"]
        else []
    )
    skill_delivery = _skill_delivery_contract(
        canonical_agent_type,
        project=resolved_project,
        cli_bin=cli_bin,
        active_project_skill_ids=active_project_skill_ids,
    )
    registered_agents = registered_agent_ids_from_registry(
        registry_path,
        resolved_goal_id,
    )
    host_loop_activation = build_host_loop_activation_packet(
        agent_type=canonical_agent_type,
        goal_id=resolved_goal_id,
        cli_bin=cli_bin,
        agent_id=agent_id,
        registered_agents=registered_agents,
        available_capabilities=available_capabilities,
    )
    selected_agent_id = host_loop_activation.get("agent_id")
    activation_allowed = bool(host_loop_activation.get("activation_allowed"))
    normalized_available_capabilities = list(
        host_loop_activation.get("available_capabilities") or []
    )
    install_command = _surface_install_command(canonical_agent_type, cli_bin)
    bootstrap_pack_command = _bootstrap_pack_command(
        project=resolved_project,
        goal_id=resolved_goal_id,
        agent_id=str(selected_agent_id) if selected_agent_id else None,
        agent_type=canonical_agent_type,
        cli_bin=cli_bin,
        task_text=task_text,
        available_capabilities=normalized_available_capabilities,
    )
    commands: dict[str, Any] = {
        "doctor_or_install": render_codex_cli_no_clone_preflight(
            cli_bin=cli_bin,
            doctor_agent_type=canonical_agent_type,
        ),
        "bootstrap_command_pack": bootstrap_pack_command,
        "quota_guard": (
            render_quota_guard_command(
                resolved_goal_id,
                cli_bin=cli_bin,
                agent_id=str(selected_agent_id) if selected_agent_id else None,
                available_capabilities=normalized_available_capabilities,
                **scheduler_command_binding_for_agent_type(canonical_agent_type),
            )
            if activation_allowed
            else None
        ),
        "agent_onboard_recheck": (
            f"{shell_arg(cli_bin)} agent-onboard "
            f"--agent-type {shell_arg(canonical_agent_type)} "
            f"--project {shell_arg(resolved_project)} "
            f"--goal-id {shell_arg(resolved_goal_id)}"
            + (
                f" --agent-id {shell_arg(str(selected_agent_id))}"
                if selected_agent_id
                else ""
            )
            + render_available_capability_args(normalized_available_capabilities)
        ),
    }
    if install_command:
        commands["install_command_facade"] = install_command
    if canonical_agent_type == "codex-cli":
        commands["codex_cli_bootstrap_message"] = (
            f"{shell_arg(cli_bin)} codex-cli-bootstrap-message "
            f"--project {shell_arg(resolved_project)} "
            f"--goal-id {shell_arg(resolved_goal_id)}"
            + (
                f" --agent-id {shell_arg(str(selected_agent_id))}"
                if selected_agent_id
                else ""
            )
        )
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "agent_type": canonical_agent_type,
        "project": resolved_project,
        "goal_id": resolved_goal_id,
        "agent_id": selected_agent_id,
        "requested_agent_id": agent_id,
        "available_capabilities": normalized_available_capabilities,
        "identity_selection_gate": host_loop_activation.get("identity_selection_gate"),
        "task_text": task_text,
        "project_connection": inspection,
        "host_loop_activation": host_loop_activation,
        "skill_delivery": skill_delivery,
        "recommended_start": (
            "Select one registered agent lane from identity_selection_gate, then rerun onboarding."
            if not activation_allowed
            else _start_instruction(canonical_agent_type)
        ),
        "commands": commands,
        "cost_model": {
            "onboarding": "run once during install/connect or when the active host loop is missing/stale",
            "loopx_task_start": (
                "`/loopx <task>` or the explicit skill should call this packet only when "
                "host_loop_activation is missing, unknown, stale, or the agent type changed"
            ),
            "normal_ticks": "read quota/status/state directly; do not recompute onboarding every turn",
        },
        "slash_command_contract": {
            "after_todo_writeback": (
                "refresh state, activate the host loop through host_loop_activation, "
                "or report the concrete host-tool gate; then run quota should-run"
            ),
            "connected_registry_is_not_enough": True,
            "setup_complete_requires": [
                "project-local LoopX state exists or was intentionally previewed",
                "ordered todos are written when task text was supplied",
                *(
                    [
                        "host-managed loaded-skill readback satisfies skill_delivery.success_criteria"
                    ]
                    if skill_delivery.get("host_readback_required") is True
                    else []
                ),
                "host_loop_activation success criteria are satisfied or a concrete gate is reported",
            ],
        },
    }


def render_agent_onboarding_markdown(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return render_agent_type_catalog_markdown(payload)
    commands = payload.get("commands") if isinstance(payload.get("commands"), dict) else {}
    activation = (
        payload.get("host_loop_activation")
        if isinstance(payload.get("host_loop_activation"), dict)
        else {}
    )
    steps = activation.get("activation_steps") if isinstance(activation.get("activation_steps"), list) else []
    criteria = (
        activation.get("success_criteria")
        if isinstance(activation.get("success_criteria"), list)
        else []
    )
    identity_gate = payload.get("identity_selection_gate")
    identity_gate = identity_gate if isinstance(identity_gate, dict) else {}
    skill_delivery = (
        payload.get("skill_delivery")
        if isinstance(payload.get("skill_delivery"), dict)
        else {}
    )
    lines = [
        "# LoopX Agent Onboarding",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- agent_type: `{payload.get('agent_type')}`",
        f"- project: `{payload.get('project')}`",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- recommended_start: {payload.get('recommended_start')}",
        "",
        "## Commands",
        "",
        "```bash",
        str(commands.get("doctor_or_install") or ""),
        "```",
    ]
    if commands.get("install_command_facade"):
        lines.extend(["", "```bash", str(commands.get("install_command_facade")), "```"])
    project_skill_commands = (
        skill_delivery.get("project_skill_commands")
        if isinstance(skill_delivery.get("project_skill_commands"), list)
        else []
    )
    if project_skill_commands:
        lines.extend(
            [
                "",
                "## Active Project Skills",
                "",
                f"- skill_ids: `{','.join(skill_delivery.get('active_project_skill_ids') or [])}`",
            ]
        )
        for item in project_skill_commands:
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    "",
                    "```bash",
                    str(item.get("status") or ""),
                    str(item.get("preview_install") or ""),
                    str(item.get("apply_install") or ""),
                    "```",
                ]
            )
    if skill_delivery.get("mode") == "host_managed":
        lines.extend(
            [
                "",
                "## Host-Managed Skill Delivery",
                "",
                f"- owner: `{skill_delivery.get('owner')}`",
                f"- required_for_cli_health: `{skill_delivery.get('required_for_cli_health')}`",
                f"- required_for_loopx_workflow: `{skill_delivery.get('required_for_loopx_workflow')}`",
                f"- delivery_options: `{','.join(skill_delivery.get('delivery_options') or [])}`",
                f"- required_skill_ids: `{','.join(skill_delivery.get('required_skill_ids') or [])}`",
                f"- source_repository: `{skill_delivery.get('source_repository')}`",
                f"- source_directories: `{','.join(skill_delivery.get('source_directories') or [])}`",
                f"- host_readback_required: `{skill_delivery.get('host_readback_required')}`",
                f"- readback_fields: `{','.join(skill_delivery.get('readback_fields') or [])}`",
                f"- source_contract: {skill_delivery.get('source_contract')}",
            ]
        )
    lines.extend(["", "```bash", str(commands.get("bootstrap_command_pack") or ""), "```"])
    if commands.get("codex_cli_bootstrap_message"):
        lines.extend(["", "```bash", str(commands.get("codex_cli_bootstrap_message")), "```"])
    lines.extend(
        [
            "",
            "## Host Loop Activation",
            "",
            f"- host_surface: `{activation.get('host_surface')}`",
            f"- activation_method: `{activation.get('activation_method')}`",
            f"- activation_input_command: `{activation.get('activation_input_command')}`",
            "",
            "Steps:",
        ]
    )
    lines.extend(f"- {step}" for step in steps)
    lines.append("")
    lines.append("Success criteria:")
    lines.extend(f"- {item}" for item in criteria)
    if identity_gate:
        lines.extend(["", "## Agent Identity Gate", ""])
        lines.append(f"- reason: {identity_gate.get('reason')}")
        for choice in identity_gate.get("choices") or []:
            if isinstance(choice, dict):
                lines.append(
                    f"- `{choice.get('agent_id')}` ({choice.get('role')}): "
                    f"`{choice.get('heartbeat_prompt_json')}`"
                )
    lines.extend(
        [
            "",
            "## Recheck Policy",
            "",
            f"- {payload.get('cost_model', {}).get('loopx_task_start') if isinstance(payload.get('cost_model'), dict) else ''}",
        ]
    )
    return "\n".join(lines)
