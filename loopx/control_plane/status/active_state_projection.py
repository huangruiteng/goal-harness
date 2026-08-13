"""Active-state status projections inside the `status` bounded context."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..goals.active_state_event_projection import (
    active_state_event_projection_fields as _active_state_event_projection_fields,
    state_event_log_candidates as _state_event_log_candidates,
)
from ..goals.active_state_sections import (
    active_state_section_entries as _active_state_section_entries,
    active_state_sections as _active_state_sections,
)
from ..goals.path_resolution import resolve_goal_local_path
from ..runtime.public_safety import public_safe_compact_text
from ..todos.active_state_todo_parser import parse_active_state_todos
from ..todos.todo_summary import (
    MAX_STATUS_TODOS_PER_ROLE,
    normalize_todo_text,
)
from ..work_items.backlog_hygiene import (
    MAX_BACKLOG_HYGIENE_EVIDENCE_ITEMS,
    backlog_hygiene_warning as _backlog_hygiene_warning,
)
from ..work_items.issue_meta_surface import (
    parse_issue_meta_surface as _parse_issue_meta_surface,
)


STATE_EVENT_LOG_BASENAME = "events.jsonl"
SECTION_HEADING_PATTERN = re.compile(r"^##+\s+(.+?)\s*$")
BACKLOG_HYGIENE_SECTION_HEADINGS = ("Next Action", "Operating Lessons")
BACKLOG_HYGIENE_BULLET_PATTERN = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$")
BACKLOG_HYGIENE_HINT_PATTERN = re.compile(
    r"(?i)(?:\[p[0-4]\]|todo|backlog|follow[- ]?up|queue|audit|regression|smoke|cadence|mirror|monitor|sub-?agent|待办|回归|审计|修复|检查|推进)"
)


def state_event_log_candidates(goal: dict[str, Any], *, state_path: Path) -> list[Path]:
    return _state_event_log_candidates(
        goal,
        state_path=state_path,
        resolve_goal_local_path=resolve_goal_local_path,
        event_log_basename=STATE_EVENT_LOG_BASENAME,
    )


def active_state_event_projection_fields(
    goal: dict[str, Any],
    *,
    state_path: Path,
    preferred_todo_ids: set[str] | None = None,
    rollout_events: list[dict[str, Any]] | None = None,
    item_limit: int | None = MAX_STATUS_TODOS_PER_ROLE,
) -> dict[str, Any]:
    return _active_state_event_projection_fields(
        goal,
        state_path=state_path,
        resolve_goal_local_path=resolve_goal_local_path,
        parse_active_state_todos=parse_active_state_todos,
        preferred_todo_ids=preferred_todo_ids,
        rollout_events=rollout_events,
        item_limit=item_limit,
        event_log_basename=STATE_EVENT_LOG_BASENAME,
    )


def active_state_sections(state_text: str, headings: tuple[str, ...]) -> dict[str, list[str]]:
    return _active_state_sections(
        state_text,
        headings,
        section_heading_pattern=SECTION_HEADING_PATTERN,
    )


def parse_issue_meta_surface(state_text: str) -> dict[str, Any] | None:
    return _parse_issue_meta_surface(
        state_text,
        section_parser=active_state_sections,
        public_safe_compact_text=public_safe_compact_text,
    )


def active_state_section_entries(lines: list[str]) -> list[str]:
    return _active_state_section_entries(
        lines,
        bullet_pattern=BACKLOG_HYGIENE_BULLET_PATTERN,
        normalize_text=normalize_todo_text,
    )


def backlog_hygiene_warning(state_text: str, *, agent_todos: dict[str, Any] | None) -> dict[str, Any] | None:
    return _backlog_hygiene_warning(
        state_text,
        agent_todos=agent_todos,
        section_headings=BACKLOG_HYGIENE_SECTION_HEADINGS,
        section_parser=active_state_sections,
        bullet_pattern=BACKLOG_HYGIENE_BULLET_PATTERN,
        hint_pattern=BACKLOG_HYGIENE_HINT_PATTERN,
        public_safe_compact_text=public_safe_compact_text,
        max_evidence_items=MAX_BACKLOG_HYGIENE_EVIDENCE_ITEMS,
    )
