from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("registry root must be a JSON object")
    return payload


def resolve_state_file(repo: Path, state_file: str | None) -> Path | None:
    if not state_file:
        return None
    path = Path(state_file).expanduser()
    return path if path.is_absolute() else repo / path


def registry_goals(registry: dict[str, Any]) -> list[dict[str, Any]]:
    goals = registry.get("goals")
    if not isinstance(goals, list):
        return []
    return [goal for goal in goals if isinstance(goal, dict) and goal.get("id")]


def inspect_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "ok": False,
            "registry": str(path),
            "error": "registry file does not exist",
        }

    payload = read_json(path)
    goals = payload.get("goals") or []
    if not isinstance(goals, list):
        raise ValueError("goals must be a list")

    inspected_goals: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    problems: list[str] = []
    seen_ids: set[str] = set()

    for raw_goal in goals:
        if not isinstance(raw_goal, dict):
            problems.append("non-object goal entry")
            continue

        goal_id = str(raw_goal.get("id") or "")
        status = str(raw_goal.get("status") or "unknown")
        repo_text = str(raw_goal.get("repo") or "")
        repo = Path(repo_text).expanduser() if repo_text else None
        state_file = resolve_state_file(repo, raw_goal.get("state_file")) if repo else None
        adapter = raw_goal.get("adapter") if isinstance(raw_goal.get("adapter"), dict) else {}
        spawn_policy = raw_goal.get("spawn_policy") if isinstance(raw_goal.get("spawn_policy"), dict) else {}
        authority_sources = raw_goal.get("authority_sources")
        if not isinstance(authority_sources, list):
            authority_sources = []

        status_counts[status] = status_counts.get(status, 0) + 1
        if not goal_id:
            problems.append("goal entry missing id")
        elif goal_id in seen_ids:
            problems.append(f"duplicate goal id: {goal_id}")
        seen_ids.add(goal_id)

        if not repo:
            problems.append(f"{goal_id or '<missing>'}: missing repo")
        if not raw_goal.get("domain"):
            problems.append(f"{goal_id or '<missing>'}: missing domain")
        if not raw_goal.get("state_file"):
            problems.append(f"{goal_id or '<missing>'}: missing state_file")
        if not adapter.get("kind"):
            problems.append(f"{goal_id or '<missing>'}: missing adapter.kind")

        inspected_goals.append(
            {
                "id": goal_id,
                "domain": raw_goal.get("domain"),
                "status": status,
                "role": raw_goal.get("role") or "controller",
                "parent_goal_id": raw_goal.get("parent_goal_id"),
                "repo": repo_text,
                "repo_exists": bool(repo and repo.exists()),
                "state_file": raw_goal.get("state_file"),
                "state_file_exists": bool(state_file and state_file.exists()),
                "adapter_kind": adapter.get("kind"),
                "adapter_status": adapter.get("status"),
                "authority_sources": authority_sources,
                "authority_source_count": len(authority_sources),
                "spawn_allowed": spawn_policy.get("allowed"),
                "max_children": spawn_policy.get("max_children"),
                "next_probe": raw_goal.get("next_probe"),
                "guards": raw_goal.get("guards") or [],
            }
        )

    return {
        "ok": not problems,
        "registry": str(path),
        "schema_version": payload.get("schema_version"),
        "updated_at": payload.get("updated_at"),
        "common_runtime_root": payload.get("common_runtime_root"),
        "goal_count": len(inspected_goals),
        "status_counts": status_counts,
        "problems": problems,
        "goals": inspected_goals,
    }


def render_registry_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Goal Harness Registry",
        "",
        f"- registry: `{payload.get('registry')}`",
        f"- ok: `{payload.get('ok')}`",
    ]
    if payload.get("error"):
        lines.append(f"- error: {payload.get('error')}")
        return "\n".join(lines)

    lines.extend(
        [
            f"- schema_version: `{payload.get('schema_version')}`",
            f"- updated_at: `{payload.get('updated_at')}`",
            f"- common_runtime_root: `{payload.get('common_runtime_root')}`",
            f"- goals: `{payload.get('goal_count')}`",
            "",
            "| goal | role | parent | domain | status | repo_exists | state_exists | spawn | adapter | next_probe |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for goal in payload.get("goals") or []:
        adapter = f"{goal.get('adapter_kind')}:{goal.get('adapter_status')}"
        spawn = f"{goal.get('spawn_allowed')}:{goal.get('max_children')}"
        next_probe = str(goal.get("next_probe") or "").replace("|", "\\|")
        authority_suffix = ""
        if goal.get("authority_source_count"):
            authority_suffix = f" authorities={goal.get('authority_source_count')}"
        lines.append(
            "| "
            f"`{goal.get('id')}` | "
            f"{goal.get('role')} | "
            f"{goal.get('parent_goal_id') or ''} | "
            f"{goal.get('domain')} | "
            f"{goal.get('status')} | "
            f"{goal.get('repo_exists')} | "
            f"{goal.get('state_file_exists')} | "
            f"{spawn} | "
            f"{adapter}{authority_suffix} | "
            f"{next_probe} |"
        )

    problems = payload.get("problems") or []
    if problems:
        lines.extend(["", "## Problems"])
        lines.extend(f"- {item}" for item in problems)
    return "\n".join(lines)
