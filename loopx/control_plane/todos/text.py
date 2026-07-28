from __future__ import annotations

import re


TODO_PRIORITY_PREFIX_PATTERN = re.compile(r"^\[(P[0-4])\]\s+", re.IGNORECASE)


def normalize_new_todo(text: str) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        raise ValueError("todo text must not be empty")
    return compact


def todo_priority_prefix(text: str | None) -> str | None:
    match = TODO_PRIORITY_PREFIX_PATTERN.match(str(text or "").strip())
    if not match:
        return None
    return match.group(1).upper()


def inherit_todo_priority(next_text: str, source_text: str | None) -> str:
    normalized = normalize_new_todo(next_text)
    if todo_priority_prefix(normalized):
        return normalized
    source_priority = todo_priority_prefix(source_text)
    if not source_priority:
        return normalized
    return f"[{source_priority}] {normalized}"
