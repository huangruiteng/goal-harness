from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...control_plane.goals.collaboration_status import (
    COLLABORATION_STATUS_SCHEMA_VERSION,
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _todo_line(label: str, summary: Mapping[str, Any]) -> str:
    open_count = int(summary.get("open_count") or 0)
    visible_count = int(summary.get("visible_count") or 0)
    suffix = f"，展示 {visible_count}" if summary.get("truncated") else ""
    return f"- {label} Todo：{open_count} 个开放{suffix}"


def render_collaboration_status_markdown(payload: dict[str, object]) -> str:
    """Render a concise status suitable for an authorized peer channel."""

    if payload.get("schema_version") != COLLABORATION_STATUS_SCHEMA_VERSION:
        raise ValueError("unsupported collaboration status schema_version")
    goal = _mapping(payload.get("goal"))
    freshness = _mapping(payload.get("freshness"))
    if payload.get("publishable") is not True:
        blockers = payload.get("blockers")
        blocker_rows = blockers if isinstance(blockers, list) else []
        codes = [
            str(item.get("code"))
            for item in blocker_rows
            if isinstance(item, Mapping) and item.get("code")
        ]
        reason = "、".join(codes[:4]) or "projection_unavailable"
        return "\n".join(
            [
                "# LoopX 协作状态",
                "",
                f"- 目标：{goal.get('display_name') or goal.get('goal_id') or 'goal'}",
                "- 当前状态投影不可用，请刷新 LoopX 状态后重试。",
                f"- 原因：{reason}",
            ]
        )

    state = _mapping(payload.get("state"))
    todos = _mapping(payload.get("todos"))
    user_todos = _mapping(todos.get("user"))
    agent_todos = _mapping(todos.get("agent"))
    owner_gate = _mapping(payload.get("owner_gate"))
    truth = _mapping(payload.get("truth_contract"))
    lines = [
        "# LoopX 协作状态",
        "",
        f"- 目标：{goal.get('display_name') or goal.get('goal_id') or 'goal'}",
        f"- 状态：{state.get('status') or 'unknown'}",
        f"- 当前焦点：{state.get('focus') or '暂无可显示焦点'}",
        f"- 下一步：{state.get('next_action') or '暂无可显示下一步'}",
        _todo_line("Agent", agent_todos),
        _todo_line("Owner", user_todos),
        (
            f"- Owner gate：开放（{owner_gate.get('summary') or '需要 owner 处理'}）"
            if owner_gate.get("open")
            else "- Owner gate：无"
        ),
        (
            "- 快照："
            f"{freshness.get('state') or 'unknown'} · "
            f"{freshness.get('generated_at') or 'unknown'}"
        ),
        (f"- 真相源：{truth.get('source') or 'LoopX'}；该投影只读，不接受状态写回。"),
    ]
    for role, summary in (("Agent", agent_todos), ("Owner", user_todos)):
        items = summary.get("items")
        if not isinstance(items, list) or not items:
            continue
        lines.extend(["", f"## {role} Todo"])
        for item in items:
            if not isinstance(item, Mapping):
                continue
            prefix = f"[{item.get('priority')}] " if item.get("priority") else ""
            owner = item.get("claimed_by") or item.get("bound_agent")
            suffix = f"（{owner}）" if owner else ""
            lines.append(f"- {prefix}{item.get('title')}{suffix}")
            references = [
                str(item.get(key))
                for key in ("todo_id", "task_repository")
                if item.get(key)
            ]
            if references:
                lines.append(f"  - ref：{' · '.join(references)}")
    if payload.get("redacted_fields"):
        lines.extend(["", "- 注：检测到鉴权材料或本机信息，相关字段已省略。"])
    return "\n".join(lines)
