from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .feedback import validate_public_safe_text
from .global_registry import sync_project_registry_to_global
from .history import load_registry
from .paths import resolve_runtime_root
from .registry import registry_goals
from .runtime import validate_goal_id_path_segment
from .state_refresh import now_local, run_file_stem


OPERATOR_GATE_DECISIONS = {"approve", "reject", "defer"}
DEFAULT_OPERATOR_GATE = "read_only_map_opt_in"


def find_registry_goal(registry: dict[str, Any], goal_id: str) -> dict[str, Any] | None:
    for goal in registry_goals(registry):
        if str(goal.get("id") or "") == goal_id:
            return goal
    return None


def default_operator_question(goal_id: str, gate: str) -> str:
    if gate == DEFAULT_OPERATOR_GATE:
        return f"是否同意 `{goal_id}` 先执行 read-only map opt-in？"
    return f"是否同意 `{goal_id}` 的 operator gate `{gate}`？"


def normalize_operator_question(question: str | None, *, goal_id: str, gate: str) -> str | None:
    if not question:
        return question
    legacy_defaults = {
        f"Approve a read-only map opt-in for `{goal_id}`?",
        f"Approve operator gate `{gate}` for `{goal_id}`?",
    }
    if question in legacy_defaults:
        return default_operator_question(goal_id, gate)
    return question


def default_agent_command(goal_id: str, gate: str) -> str | None:
    if gate == DEFAULT_OPERATOR_GATE:
        return f"goal-harness read-only-map --goal-id {goal_id} --dry-run"
    return None


def classification_for_decision(decision: str) -> str:
    if decision == "approve":
        return "operator_gate_approved"
    if decision == "reject":
        return "operator_gate_rejected"
    if decision == "defer":
        return "operator_gate_deferred"
    raise ValueError(f"decision must be one of: {', '.join(sorted(OPERATOR_GATE_DECISIONS))}")


def default_recommended_action(*, decision: str, agent_command: str | None) -> str:
    if decision == "approve":
        if agent_command:
            return "把已批准的 agent_command 发给目标项目 agent；这不是写权限授权"
        return "继续执行已批准的 operator gate；这不是写权限授权"
    if decision == "reject":
        return "保持 goal 在 gate 状态，修改 handoff 后再请求 operator 判断"
    if decision == "defer":
        return "保持 goal 在 gate 状态，先补齐要求的证据后再请求判断"
    raise ValueError(f"decision must be one of: {', '.join(sorted(OPERATOR_GATE_DECISIONS))}")


def compact_operator_gate(
    *,
    recorded_at: str | None,
    gate: str,
    decision: str,
    operator_question: str,
    reason_summary: str,
    follow_up: str | None,
    agent_command: str | None,
) -> dict[str, Any]:
    if decision not in OPERATOR_GATE_DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(OPERATOR_GATE_DECISIONS))}")
    for label, value in (
        ("gate", gate),
        ("operator_question", operator_question),
        ("reason_summary", reason_summary),
        ("follow_up", follow_up),
        ("agent_command", agent_command),
    ):
        validate_public_safe_text(label, value)
    payload: dict[str, Any] = {
        "recorded_at": recorded_at or now_local(),
        "gate": gate,
        "decision": decision,
        "operator_question": operator_question,
        "reason_summary": reason_summary,
    }
    if follow_up:
        payload["follow_up"] = follow_up
    if agent_command:
        payload["agent_command"] = agent_command
    return payload


def build_operator_gate_record(
    *,
    goal_id: str,
    registry_goal: dict[str, Any] | None,
    classification: str,
    recommended_action: str,
    generated_at: str,
    operator_gate: dict[str, Any],
) -> dict[str, Any]:
    adapter = registry_goal.get("adapter") if isinstance(registry_goal, dict) and isinstance(registry_goal.get("adapter"), dict) else {}
    health_check = (
        f"operator_gate decision={operator_gate.get('decision')}; "
        f"registry_goal {1 if registry_goal else 0}/1; "
        f"agent_command {1 if operator_gate.get('agent_command') else 0}/1"
    )
    return {
        "generated_at": generated_at,
        "goal_id": goal_id,
        "classification": classification,
        "recommended_action": recommended_action,
        "health_check": health_check,
        "operator_gate": operator_gate,
        "registry_goal": {
            "present": bool(registry_goal),
            "domain": registry_goal.get("domain") if registry_goal else None,
            "status": registry_goal.get("status") if registry_goal else None,
            "adapter": {
                "kind": adapter.get("kind"),
                "status": adapter.get("status"),
            },
        },
    }


def render_operator_gate_markdown(payload: dict[str, Any]) -> str:
    gate = payload.get("operator_gate") if isinstance(payload.get("operator_gate"), dict) else {}
    lines = [
        "# Goal Harness Operator Gate Decision",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- dry_run: `{payload.get('dry_run')}`",
        f"- appended: `{payload.get('appended')}`",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- classification: `{payload.get('classification')}`",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- health_check: `{payload.get('health_check')}`",
    ]
    if payload.get("error"):
        lines.append(f"- error: {payload.get('error')}")
        return "\n".join(lines)

    global_sync = payload.get("global_sync") if isinstance(payload.get("global_sync"), dict) else {}
    if global_sync:
        lines.extend(
            [
                f"- global_registry: `{global_sync.get('global_registry')}`",
                f"- global_sync_wrote: `{global_sync.get('wrote')}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Gate",
            f"- gate: `{gate.get('gate')}`",
            f"- decision: `{gate.get('decision')}`",
            f"- operator_question: {gate.get('operator_question')}",
            f"- reason_summary: {gate.get('reason_summary')}",
        ]
    )
    if gate.get("follow_up"):
        lines.append(f"- follow_up: {gate.get('follow_up')}")
    if gate.get("agent_command"):
        lines.extend(["", "## Agent Command", f"```bash\n{gate.get('agent_command')}\n```"])
    lines.extend(["", "## Recommended Action", str(payload.get("recommended_action") or "")])
    return "\n".join(lines)


def record_operator_gate(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    goal_id: str,
    gate: str,
    decision: str,
    operator_question: str | None,
    reason_summary: str,
    follow_up: str | None,
    agent_command: str | None,
    recommended_action: str | None,
    recorded_at: str | None,
    dry_run: bool,
    sync_global: bool = True,
) -> dict[str, Any]:
    safe_goal_id = validate_goal_id_path_segment(goal_id)
    validate_public_safe_text("gate", gate)
    validate_public_safe_text("reason_summary", reason_summary)
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(registry, runtime_root_override)
    registry_goal = find_registry_goal(registry, safe_goal_id)
    question = operator_question or default_operator_question(safe_goal_id, gate)
    command = agent_command
    if command is None and decision == "approve":
        command = default_agent_command(safe_goal_id, gate)
    operator_gate = compact_operator_gate(
        recorded_at=recorded_at,
        gate=gate,
        decision=decision,
        operator_question=question,
        reason_summary=reason_summary,
        follow_up=follow_up,
        agent_command=command,
    )
    classification = classification_for_decision(decision)
    action = recommended_action or default_recommended_action(decision=decision, agent_command=command)
    validate_public_safe_text("recommended_action", action)
    generated_at = now_local()
    record = build_operator_gate_record(
        goal_id=safe_goal_id,
        registry_goal=registry_goal,
        classification=classification,
        recommended_action=action,
        generated_at=generated_at,
        operator_gate=operator_gate,
    )

    runs_dir = runtime_root / "goals" / safe_goal_id / "runs"
    stem = f"{run_file_stem(generated_at)}-operator-gate"
    json_path = runs_dir / f"{stem}.json"
    markdown_path = runs_dir / f"{stem}.md"
    index_path = runs_dir / "index.jsonl"
    index_record = {
        "generated_at": generated_at,
        "goal_id": safe_goal_id,
        "classification": classification,
        "recommended_action": action,
        "health_check": record["health_check"],
        "operator_gate": operator_gate,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    payload = {
        "ok": True,
        "dry_run": dry_run,
        "appended": not dry_run,
        "registry": str(registry_path),
        "runtime_root": str(runtime_root),
        "goal_id": safe_goal_id,
        "classification": classification,
        "recommended_action": action,
        "generated_at": generated_at,
        "health_check": record["health_check"],
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "index_path": str(index_path),
        **record,
    }
    if not dry_run:
        runs_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(render_operator_gate_markdown(payload) + "\n", encoding="utf-8")
        with index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(index_record, ensure_ascii=False) + "\n")
    if sync_global:
        payload["global_sync"] = sync_project_registry_to_global(
            registry_path=registry_path,
            runtime_root_override=str(runtime_root),
            goal_id=safe_goal_id,
            dry_run=dry_run,
        )
    else:
        payload["global_sync"] = {"enabled": False}
    return payload
