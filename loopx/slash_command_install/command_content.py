from __future__ import annotations

from pathlib import Path
from typing import Any

from .managed_files import MANAGED_MARKER_PREFIX, _target_status


def _managed_marker(*, command: str, surface: str) -> str:
    return f"{MANAGED_MARKER_PREFIX} command={command} surface={surface} -->"


def _front_matter(*, fields: dict[str, str]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        escaped = value.replace('"', '\\"')
        lines.append(f'{key}: "{escaped}"')
    lines.append("---")
    return "\n".join(lines)


def _skill_body(
    *,
    command: str,
    title: str,
    description: str,
    argument_hint: str,
    instructions: list[str],
    surface: str,
    front_matter_name: str | None = None,
) -> str:
    fields = {
        "description": description,
        "argument-hint": argument_hint,
    }
    if front_matter_name:
        fields = {"name": front_matter_name, **fields}
    surface_label = (
        "slash command"
        if surface == "claude-skills"
        else "explicit LoopX command skill"
    )
    return (
        "\n\n".join(
            [
                _front_matter(fields=fields),
                _managed_marker(command=command, surface=surface),
                f"# {title}",
                f"Treat this as the LoopX `{command}` {surface_label}.",
                "\n".join(instructions),
                "Keep public/private boundaries intact and do not perform external writes unless the active LoopX state or owner explicitly authorizes them.",
            ]
        )
        + "\n"
    )


def _openai_skill_metadata(
    *, command: str, display_name: str, short_description: str
) -> str:
    return "\n".join(
        [
            f"# {_managed_marker(command=command, surface='codex-skill-metadata')}",
            "interface:",
            f'  display_name: "{display_name}"',
            f'  short_description: "{short_description}"',
            "policy:",
            "  allow_implicit_invocation: false",
            "",
        ]
    )


def _opencode_command_body(spec: dict[str, Any]) -> str:
    return (
        "\n\n".join(
            [
                _front_matter(
                    fields={
                        "description": str(spec["description"]),
                        "agent": "build",
                    }
                ),
                _managed_marker(
                    command=str(spec["command"]), surface="opencode-command"
                ),
                f"Treat this as the LoopX `{spec['command']}` OpenCode command.",
                (
                    "The exact current host is OpenCode. For goal start, pass "
                    "`--host-surface opencode` and use `loopx_goal_activate` from the "
                    "returned host-loop activation packet."
                ),
                "\n".join(str(item) for item in spec["instructions"]),
                (
                    "Keep public/private boundaries intact and do not perform external "
                    "writes unless the active LoopX state or owner explicitly authorizes them."
                ),
            ]
        )
        + "\n"
    )


def _command_prompt_specs(
    *, cli_bin: str, include_legacy_aliases: bool
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {
            "command": "/loopx",
            "name": "loopx",
            "description": "Inspect LoopX state, or start concrete project work when arguments are provided.",
            "argument_hint": "[--capability-route issue-fix] [task text]",
            "instructions": [
                "Visible command arguments: `$ARGUMENTS`.",
                "Before start-goal, identify the exact current host: use `codex-app` for the desktop app with automation tools, `codex-app-ssh` for the desktop app over SSH without automation tools, `codex-ide-plugin` only for the IDE plugin, `codex-cli-tui` for the terminal TUI, `opencode` for OpenCode, `traex-cli` for the TraeX terminal TUI, `pi` for Pi, or `ark-managed-agent` for Ark Managed Agent.",
                f'If arguments are present, parse only an optional leading `--capability-route issue-fix` as an explicit product-route switch, remove that prefix from the task text, and pass it to `{cli_bin} start-goal --guided --project . --goal-text "<remaining exact arguments>" --host-surface <exact-current-host>`. Without that switch, preserve all arguments as task text and do not add a capability route. Never infer a route from issue/PR wording or URLs. If the host is unclear, omit the host flag once and follow the returned host-surface selection gate.',
                f"Treat the returned `ordered_steps` as a required transaction. On first connection, run its bootstrap command, resolve the fresh-agent identity gate before planning, then plan and execute at least one business `{cli_bin} todo add` derived from `$ARGUMENTS` before substantive task work. Encode priority in the todo text such as `[P0]`; `{cli_bin} todo add` has no `--priority` flag. Do not continue until LoopX status shows that business Agent Todo.",
                f"If `selected_capability_route` is present, run its entry and admission commands before substantive implementation, and treat `{cli_bin} capability show <capability-id> --format json` as the authoritative later-transition command surface. Use capability-owned commands for listed external transitions instead of substituting provider CLIs. Keep capability facts in capability-owned state; generic Todos remain scheduling records.",
                f"Before dependent work, persist material scope, acceptance, or non-goal changes in current Todo evidence and the next executable Todo; then run `{cli_bin} refresh-state` and verify quota readback. Chat/model summaries are not durable state.",
                f"If that packet exposes a goal-selection gate, rerun one exact choice before any mutation. For an argument-bearing task with no active agent interaction contract, treat this invocation as a new agent connection by default: choose a new public-safe agent id and preview `{cli_bin} register-agent --goal-id <selected-goal-id> --agent-id <new-agent-id> --require-new`. Treat preview as advisory; apply with `--execute` and continue only when that result reports `ok=true`, `changed=true`, `written=true`, successful global sync, and verified registration readback. Then rerun start-goal with explicit `--goal-id` and `--agent-id` before todo writeback. Only reuse an existing registered identity when the user explicitly asks to take over that exact agent's work; never infer takeover from a single registered agent or registry order.",
                f"If arguments are empty and the host task already identifies an active LoopX goal, run its exact CLI `interaction_contract` or quota command first; do not call `start-goal` or bootstrap another goal. Only when no active goal contract is present, inspect `{cli_bin} bootstrap-command-pack --project .`, `{cli_bin} status`, and `{cli_bin} slash-commands` before changing files.",
                f"Use `{cli_bin} agent-onboard --list-agent-types` when the host runtime is unclear; pass an exact type such as `codex-app`, `codex-app-ssh`, `codex-ide-plugin`, `codex-cli`, `claude-code`, `opencode`, `traex-cli`, `pi`, or `ark-managed-agent`, never ambiguous `codex`.",
                f"Do not configure optional features during first-run. Only when the task needs bounded child agents or Explore, inspect `{cli_bin} configure-goal --goal-id <resolved-goal-id>` and its `configuration_catalog`; preview before explicit apply and never auto-enable a feature merely because it exists.",
                "When project work is started, plan ordered P0/P1/P2 todos, write them through LoopX todo state, refresh state, activate the host loop if missing/stale, run quota, and complete one bounded delivery segment through validation plus LoopX writeback or an exact blocker; do not return merely after setup, planning, or claim.",
                "Host loop activation means Codex App heartbeat automation; Codex App over SSH, the Codex IDE plugin, or CLI visible `/goal <task_body>`; Claude Code native `/loop`; OpenCode `loopx_goal_activate`; TraeX visible `/goal <task_body>`; Ark Managed Agent one-shot Goal submission; or a custom host-loop gate from `loopx agent-onboard`.",
                "If this session cannot mutate the host loop surface, surface the exact pasteable gate instead of saying LoopX is autonomously connected.",
            ],
        },
        {
            "command": "/loopx-global-summary",
            "name": "loopx-global-summary",
            "description": "Read the compact global LoopX progress digest.",
            "argument_hint": "[optional focus]",
            "instructions": [
                "Visible command arguments: `$ARGUMENTS`.",
                f"Run `{cli_bin} global-summary` first and summarize visible projects, gates, monitor status, and next safe actions.",
                "This command is read-only unless the user explicitly asks for a state update.",
            ],
        },
        {
            "command": "/loopx-global-gates",
            "name": "loopx-global-gates",
            "description": "List open LoopX user/controller gates and what each blocks.",
            "argument_hint": "[optional focus]",
            "instructions": [
                "Visible command arguments: `$ARGUMENTS`.",
                f"Run `{cli_bin} global-summary` first, then focus the answer on open gates, blocked work, owner decisions, and exact next questions.",
                "This command is read-only unless the user explicitly asks for a state update.",
            ],
        },
        {
            "command": "/loopx-global-todos",
            "name": "loopx-global-todos",
            "description": "List runnable, blocked, deferred-ready, and review LoopX todos across visible projects.",
            "argument_hint": "[optional focus]",
            "instructions": [
                "Visible command arguments: `$ARGUMENTS`.",
                f"Run `{cli_bin} global-summary` first, then focus the answer on prioritized todos and ownership across visible projects.",
                "This command is read-only unless the user explicitly asks for a state update.",
            ],
        },
        {
            "command": "/loopx-global-risks",
            "name": "loopx-global-risks",
            "description": "Show stale LoopX runs, boundary risks, failing checks, and rollback candidates.",
            "argument_hint": "[optional focus]",
            "instructions": [
                "Visible command arguments: `$ARGUMENTS`.",
                f"Run `{cli_bin} global-summary` first, then focus the answer on stale work, public/private boundary risks, failing checks, and rollback candidates.",
                "This command is read-only unless the user explicitly asks for a state update.",
            ],
        },
        {
            "command": "/loopx-pr-review",
            "name": "loopx-pr-review",
            "description": "Run the LoopX PR-review packet first, then review selected PR groups with evidence.",
            "argument_hint": "[--repo owner/repo] [--state open|merged|all] [--since ISO]",
            "instructions": [
                "Visible command arguments: `$ARGUMENTS`.",
                "Use the installed `loopx-pr-review` skill when available.",
                f"Run `{cli_bin} --format json pr-review $ARGUMENTS` first and keep `agent_response_contract`, `review_groups`, `pull_requests[].review_template`, and `pull_requests[].evidence_commands` visible.",
                "Do not reconstruct the PR queue manually from ad hoc GitHub calls before reading the LoopX packet.",
                "This command is read-only; do not comment, approve, merge, rerun CI, or spend quota unless separately authorized.",
            ],
        },
    ]
    if include_legacy_aliases:
        legacy_specs = []
        for canonical in specs:
            name = canonical["name"]
            if not str(name).startswith("loopx-global-"):
                continue
            legacy_name = str(name).replace("loopx-global-", "loop-global-", 1)
            legacy_specs.append(
                {
                    **canonical,
                    "command": "/" + legacy_name,
                    "name": legacy_name,
                    "description": canonical["description"]
                    + " Legacy alias for the canonical /loopx-global-* command.",
                }
            )
        specs.extend(legacy_specs)
    return specs


def _command_skill_content(spec: dict[str, Any], *, surface: str) -> str:
    return _skill_body(
        command=str(spec["command"]),
        title=f"LoopX {spec['command']}",
        description=str(spec["description"]),
        argument_hint=str(spec["argument_hint"]),
        instructions=list(spec["instructions"]),
        surface=surface,
        front_matter_name=str(spec["name"]),
    )


def materialize_loopx_entry_skill(
    *,
    skills_dir: Path,
    execute: bool,
    cli_bin: str = "loopx",
    host_surface: str | None = None,
) -> dict[str, Any]:
    """Materialize the generated ``$loopx`` entry skill into a host skill root."""

    if host_surface not in {None, "ark-managed-agent"}:
        raise ValueError(f"unsupported fixed LoopX entry host surface: {host_surface}")
    spec = next(
        item
        for item in _command_prompt_specs(
            cli_bin=cli_bin,
            include_legacy_aliases=False,
        )
        if item["name"] == "loopx"
    )
    if host_surface:
        instructions = list(spec["instructions"])
        instructions[1] = (
            "This entry skill is installed for the exact current host "
            f"`{host_surface}`; do not infer or substitute another host surface."
        )
        instructions[2] = (
            f"If arguments are present, parse only an optional leading "
            "`--capability-route issue-fix` as an explicit product-route switch, "
            "remove that prefix from the task text, and pass it to "
            f'`{cli_bin} start-goal --guided --project . --goal-text "<remaining exact arguments>" '
            f"--host-surface {host_surface}`. Without that switch, preserve all "
            "arguments as task text and do not add a capability route. Never infer "
            "a route from issue/PR wording or URLs."
        )
        spec = {**spec, "instructions": instructions}
    skill_path = skills_dir / "loopx" / "SKILL.md"
    content = _command_skill_content(spec, surface="codex-skills")
    return {
        "skill_id": "loopx",
        "path": str(skill_path),
        "status": _target_status(skill_path, content, execute=execute),
    }
