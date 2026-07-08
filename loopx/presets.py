from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any


PRESET_PICKER_SCHEMA_VERSION = "loopx_beginner_preset_picker_v0"


@dataclass(frozen=True)
class BeginnerPreset:
    preset_id: str
    title: str
    maturity: str
    cadence: str
    default_mode: str
    summary: str
    goal_text: str
    capability_path: tuple[str, ...]
    safety_defaults: tuple[str, ...]
    useful_when: tuple[str, ...]


BEGINNER_PRESETS: tuple[BeginnerPreset, ...] = (
    BeginnerPreset(
        preset_id="daily-triage",
        title="Daily Triage L1",
        maturity="L1 report-only",
        cadence="daily or weekday morning",
        default_mode="report_only",
        summary=(
            "Inspect LoopX status, active todos, open gates, stale signals, and the "
            "single next action so the owner gets a useful project digest."
        ),
        goal_text=(
            "Run Daily Triage L1 for this repository: inspect LoopX status, active "
            "todos, open gates, stale signals, and next actions; write a compact "
            "report and ask before code edits or external writes."
        ),
        capability_path=(
            "status",
            "todo projection",
            "quota should-run",
            "thin evidence log",
        ),
        safety_defaults=(
            "No code edits by default.",
            "No external writes by default.",
            "Human review before changing project files, publishing, or closing gates.",
        ),
        useful_when=(
            "You want LoopX to keep a long-running repo goal warm.",
            "You need a low-risk first demo that still uses real LoopX state.",
        ),
    ),
    BeginnerPreset(
        preset_id="changelog-draft",
        title="Changelog Draft L1",
        maturity="L1 draft-only",
        cadence="per release, or daily during release week",
        default_mode="draft_only",
        summary=(
            "Turn recent merged work and LoopX run history into a release-note draft "
            "with PR links when available."
        ),
        goal_text=(
            "Run Changelog Draft L1 for this repository: summarize recent merged "
            "work and LoopX run history into a human-reviewed release-note draft "
            "with PR links when available; do not publish."
        ),
        capability_path=(
            "history",
            "release notes draft",
            "PR link evidence",
            "human review gate",
        ),
        safety_defaults=(
            "Draft only; no release creation or publish action.",
            "Prefer PR links and compact public evidence over raw logs.",
            "Human review before tagging, announcing, or editing canonical docs.",
        ),
        useful_when=(
            "You want visible maintainer value without granting write authority.",
            "You need release copy that is grounded in recent work instead of memory.",
        ),
    ),
    BeginnerPreset(
        preset_id="pr-watch",
        title="PR Watch L1",
        maturity="L1 watch-only",
        cadence="every 10-30 minutes while the PR is active",
        default_mode="watch_only",
        summary=(
            "Watch review, CI, and merge blockers for a PR, then report what changed "
            "and what needs a human decision."
        ),
        goal_text=(
            "Run PR Watch L1 for this repository: watch review, CI, and merge "
            "blockers for the target PR; report material changes, blockers, and "
            "next human decisions; do not auto-merge."
        ),
        capability_path=(
            "continuous monitor todo",
            "quota monitor-poll",
            "CI/review blocker summary",
            "human merge gate",
        ),
        safety_defaults=(
            "No auto-merge.",
            "No code edits unless the owner upgrades the preset to an explicit L2 fix lane.",
            "Quiet unchanged polls should not spend quota.",
        ),
        useful_when=(
            "You want fewer manual PR refreshes while keeping merge authority human.",
            "You need an automation-friendly monitor that still produces concrete blockers.",
        ),
    ),
)

PRESET_IDS = tuple(preset.preset_id for preset in BEGINNER_PRESETS)


def _shell(value: str) -> str:
    return shlex.quote(value)


def _preset_commands(
    preset: BeginnerPreset,
    *,
    cli_bin: str,
    project: str,
    goal_id: str,
    agent_id: str,
    agent_scope: str,
) -> dict[str, str]:
    return {
        "slash_start": f"/loopx {preset.goal_text}",
        "cli_start": (
            f"{cli_bin} start-goal --guided --project {_shell(project)} "
            f"--goal-text {_shell(preset.goal_text)}"
        ),
        "quota_guard": (
            f"{cli_bin} --format json quota should-run "
            f"--goal-id {_shell(goal_id)} --agent-id {_shell(agent_id)}"
        ),
        "heartbeat_prompt": (
            f"{cli_bin} heartbeat-prompt --thin --goal-id {_shell(goal_id)} "
            f"--agent-id {_shell(agent_id)} --agent-scope {_shell(agent_scope)}"
        ),
    }


def _preset_to_dict(
    preset: BeginnerPreset,
    *,
    cli_bin: str,
    project: str,
    goal_id: str,
    agent_id: str,
    agent_scope: str,
) -> dict[str, Any]:
    return {
        "id": preset.preset_id,
        "title": preset.title,
        "maturity": preset.maturity,
        "cadence": preset.cadence,
        "default_mode": preset.default_mode,
        "summary": preset.summary,
        "goal_text": preset.goal_text,
        "capability_path": list(preset.capability_path),
        "safety_defaults": list(preset.safety_defaults),
        "useful_when": list(preset.useful_when),
        "commands": _preset_commands(
            preset,
            cli_bin=cli_bin,
            project=project,
            goal_id=goal_id,
            agent_id=agent_id,
            agent_scope=agent_scope,
        ),
    }


def build_beginner_preset_packet(
    *,
    preset_id: str | None = None,
    cli_bin: str = "loopx",
    project: str = ".",
    goal_id: str = "<goal-id>",
    agent_id: str = "<agent-id>",
    agent_scope: str = "<agent-scope>",
) -> dict[str, Any]:
    presets = BEGINNER_PRESETS
    if preset_id:
        presets = tuple(preset for preset in BEGINNER_PRESETS if preset.preset_id == preset_id)
        if not presets:
            raise ValueError(f"unknown beginner preset: {preset_id}")
    return {
        "ok": True,
        "schema_version": PRESET_PICKER_SCHEMA_VERSION,
        "summary": (
            "Beginner LoopX presets compile common loop-engineering use cases into "
            "existing LoopX start, quota, heartbeat, and evidence flows."
        ),
        "mutation_policy": "read_only; renders commands only; does not write registry, state, automation, PRs, or docs",
        "recommended_order": list(PRESET_IDS),
        "placeholders": {
            "goal_id": goal_id,
            "agent_id": agent_id,
            "agent_scope": agent_scope,
            "project": project,
        },
        "common_setup": [
            f"{cli_bin} doctor",
            f"{cli_bin} slash-commands --install",
            f"{cli_bin} preset list",
        ],
        "presets": [
            _preset_to_dict(
                preset,
                cli_bin=cli_bin,
                project=project,
                goal_id=goal_id,
                agent_id=agent_id,
                agent_scope=agent_scope,
            )
            for preset in presets
        ],
    }


def render_beginner_preset_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# LoopX beginner preset picker",
        "",
        str(payload.get("summary") or ""),
        "",
        f"Mutation policy: {payload.get('mutation_policy')}",
        "",
        "Common setup:",
    ]
    for command in payload.get("common_setup", []):
        lines.append(f"- `{command}`")
    lines.append("")
    presets = payload.get("presets") if isinstance(payload.get("presets"), list) else []
    for preset in presets:
        if not isinstance(preset, dict):
            continue
        lines.extend(
            [
                f"## {preset.get('title')}",
                "",
                f"- id: `{preset.get('id')}`",
                f"- maturity: {preset.get('maturity')}",
                f"- cadence: {preset.get('cadence')}",
                f"- default mode: `{preset.get('default_mode')}`",
                f"- summary: {preset.get('summary')}",
                "",
                "Useful when:",
            ]
        )
        for item in preset.get("useful_when", []):
            lines.append(f"- {item}")
        lines.extend(["", "Safety defaults:"])
        for item in preset.get("safety_defaults", []):
            lines.append(f"- {item}")
        lines.extend(["", "Commands:", ""])
        commands = preset.get("commands") if isinstance(preset.get("commands"), dict) else {}
        for label in ("slash_start", "cli_start", "quota_guard", "heartbeat_prompt"):
            command = commands.get(label)
            if command:
                lines.extend([f"{label}:", "```bash", str(command), "```", ""])
        lines.append(f"Show only this preset: `loopx preset show {preset.get('id')}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
