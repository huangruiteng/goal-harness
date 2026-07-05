from __future__ import annotations

from typing import Any

from .contract import TODO_TASK_CLASS_USER_GATE
from .projection import todo_item_task_class


USER_GATE_ACTION_KIND_HINTS = (
    "approval",
    "approve",
    "boundary",
    "gate",
    "blocker",
    "credential",
    "private",
    "production",
    "leaderboard",
    "submission",
    "public_claim",
)


def open_todo_count(summary: dict[str, Any] | None) -> int:
    if not isinstance(summary, dict):
        return 0
    try:
        return max(0, int(summary.get("open_count") or 0))
    except (TypeError, ValueError):
        return 0


def is_user_gate_todo_item(item: dict[str, Any]) -> bool:
    if todo_item_task_class(item) == TODO_TASK_CLASS_USER_GATE:
        return True
    action_kind = str(item.get("action_kind") or "").strip().lower()
    if not action_kind:
        return False
    return any(hint in action_kind for hint in USER_GATE_ACTION_KIND_HINTS)


def open_user_gate_todo_items(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(summary, dict):
        return []
    candidates: list[dict[str, Any]] = []
    for key in ("gate_open_items", "first_open_items"):
        values = summary.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict) or item.get("done") is True:
                continue
            if not is_user_gate_todo_item(item):
                continue
            item_key = (item.get("todo_id"), item.get("index"), item.get("text"))
            if any(
                (existing.get("todo_id"), existing.get("index"), existing.get("text"))
                == item_key
                for existing in candidates
            ):
                continue
            candidates.append(item)
    return candidates


def has_open_user_gate_todo(summary: dict[str, Any] | None) -> bool:
    return bool(open_user_gate_todo_items(summary))


def user_gate_todo_notify_reason(summary: dict[str, Any] | None) -> str:
    items = open_user_gate_todo_items(summary)
    if not items:
        return "open user todo can resolve the current gate"
    first = items[0]
    action_kind = str(first.get("action_kind") or "").strip()
    if action_kind:
        return f"open user_gate todo requires owner decision before {action_kind}"
    return "open user_gate todo requires owner decision before agent execution"


def should_notify_user_on_open_todo(
    *,
    state: str,
    waiting_on: str,
    user_todo_summary: dict[str, Any] | None,
) -> bool:
    if state == "operator_gate":
        return False
    if open_todo_count(user_todo_summary) <= 0:
        return False
    if state in {"focus_wait", "waiting"}:
        return True
    return waiting_on in {"user_or_controller", "controller", "external_evidence"}


def build_gate_prompt(
    item: dict[str, Any],
    *,
    user_todo_summary: dict[str, Any] | None = None,
) -> str | None:
    question = str(item.get("operator_question") or "").strip()
    recommended_action = str(item.get("recommended_action") or "").strip()
    next_handoff_condition = str(item.get("next_handoff_condition") or "").strip()
    missing_gates = [
        str(gate).strip()
        for gate in (item.get("missing_gates") if isinstance(item.get("missing_gates"), list) else [])
        if str(gate).strip()
    ]
    if user_todo_summary is None:
        from .quota_summary import summarize_user_todos_for_quota

        user_todo_summary = summarize_user_todos_for_quota(item.get("user_todos"))
    first_open = (
        user_todo_summary.get("first_open_items")
        if isinstance(user_todo_summary, dict)
        and isinstance(user_todo_summary.get("first_open_items"), list)
        else []
    )
    other_agent_scoped_items = (
        user_todo_summary.get("other_agent_scoped_items")
        if isinstance(user_todo_summary, dict)
        and isinstance(user_todo_summary.get("other_agent_scoped_items"), list)
        else []
    )

    if not any(
        [
            question,
            recommended_action,
            next_handoff_condition,
            missing_gates,
            first_open,
            other_agent_scoped_items,
        ]
    ):
        return None

    lines = ["请用户/控制器确认当前 gate："]
    if question:
        lines.append(f"- 问题：{question}")
    if recommended_action:
        lines.append(f"- 当前建议：{recommended_action}")
    if next_handoff_condition:
        lines.append(f"- 放行条件：{next_handoff_condition}")
    if missing_gates:
        lines.append(f"- 缺失 gate：{', '.join(missing_gates)}")
    if isinstance(user_todo_summary, dict) and first_open:
        open_count = user_todo_summary.get("open_count")
        lines.append(f"- 用户待办：{open_count} 项未完成，优先确认：")
        for todo in first_open:
            index = todo.get("index")
            prefix = f"  {index}. " if index is not None else "  - "
            lines.append(f"{prefix}{todo.get('text')}")
    elif isinstance(user_todo_summary, dict) and other_agent_scoped_items:
        scoped_count = user_todo_summary.get("other_agent_scoped_open_count")
        all_open_count = user_todo_summary.get("all_open_count")
        count = scoped_count if scoped_count is not None else len(other_agent_scoped_items)
        suffix = f"（全局共 {all_open_count} 项）" if all_open_count is not None else ""
        lines.append(f"- 当前 agent 无阻塞用户待办；其他 agent/global 用户待办：{count} 项{suffix}，优先确认：")
        for todo in other_agent_scoped_items[:3]:
            index = todo.get("index")
            prefix = f"  {index}. " if index is not None else "  - "
            lines.append(f"{prefix}{todo.get('text')}")
    lines.append("- 建议回复格式：同意 / 不同意 / 已完成 / 仍待确认 + 一句话原因。")
    return "\n".join(lines)
