from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .history import load_registry
from .state_refresh import now_local, resolve_goal_state
from .status import TODO_TASK_PATTERN, normalize_todo_text, todo_role_for_heading


TODO_SECTION_HEADINGS = {
    "user": "User Todo / Owner Review Reading Queue",
    "agent": "Agent Todo",
}


def normalize_new_todo(text: str) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        raise ValueError("todo text must not be empty")
    return compact


def section_bounds(lines: list[str], role: str) -> tuple[int, int, str] | None:
    for index, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        heading = line.lstrip("#").strip()
        if todo_role_for_heading(heading) != role:
            continue
        end = len(lines)
        for next_index in range(index + 1, len(lines)):
            if lines[next_index].startswith("## "):
                end = next_index
                break
        return index, end, heading
    return None


def heading_index(lines: list[str], heading: str) -> int | None:
    needle = f"## {heading}"
    for index, line in enumerate(lines):
        if line.strip() == needle:
            return index
    return None


def section_has_todo(lines: list[str], start: int, end: int, text: str) -> bool:
    expected = normalize_todo_text(text)
    for line in lines[start + 1 : end]:
        match = TODO_TASK_PATTERN.match(line)
        if not match:
            continue
        if normalize_todo_text(match.group(2)) == expected:
            return True
    return False


def insert_into_existing_section(lines: list[str], start: int, end: int, todo_line: str) -> None:
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    new_lines = [todo_line]
    if insert_at == start + 1:
        new_lines.insert(0, "")
    if insert_at == end and end < len(lines) and lines[end].startswith("## "):
        new_lines.append("")
    lines[insert_at:insert_at] = new_lines


def insertion_anchor(lines: list[str], role: str) -> int:
    if role == "user":
        agent_bounds = section_bounds(lines, "agent")
        if agent_bounds:
            return agent_bounds[0]
    next_action = heading_index(lines, "Next Action")
    if next_action is not None:
        return next_action
    return len(lines)


def insert_new_section(lines: list[str], role: str, todo_line: str) -> None:
    anchor = insertion_anchor(lines, role)
    heading = TODO_SECTION_HEADINGS[role]
    section = [f"## {heading}", "", todo_line, ""]
    if anchor > 0 and lines[anchor - 1].strip():
        section.insert(0, "")
    lines[anchor:anchor] = section


def replace_updated_at(text: str, updated_at: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    frontmatter = parts[1]
    body = parts[2]
    if re.search(r"(?m)^updated_at:\s*.+$", frontmatter):
        frontmatter = re.sub(r"(?m)^updated_at:\s*.+$", f"updated_at: {updated_at}", frontmatter, count=1)
    else:
        frontmatter = frontmatter.rstrip("\n") + f"\nupdated_at: {updated_at}\n"
    return "---" + frontmatter + "---" + body


def add_goal_todo(
    *,
    registry_path: Path,
    goal_id: str,
    role: str,
    text: str,
    project: Path | None = None,
    state_file: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if role not in TODO_SECTION_HEADINGS:
        raise ValueError("todo role must be one of: user, agent")
    todo_text = normalize_new_todo(text)
    registry = load_registry(registry_path)
    goal, resolved_project, resolved_state_file = resolve_goal_state(
        registry=registry,
        goal_id=goal_id,
        project_override=project,
        state_file_override=state_file,
    )
    if goal is None:
        raise ValueError(f"goal {goal_id!r} is not present in the registry")
    if not resolved_state_file.exists():
        raise ValueError(f"active state file does not exist: {resolved_state_file}")

    original = resolved_state_file.read_text(encoding="utf-8")
    lines = original.splitlines()
    bounds = section_bounds(lines, role)
    section = bounds[2] if bounds else TODO_SECTION_HEADINGS[role]
    todo_line = f"- [ ] {todo_text}"
    already_exists = bool(bounds and section_has_todo(lines, bounds[0], bounds[1], todo_text))
    added = not already_exists

    if added:
        if bounds:
            insert_into_existing_section(lines, bounds[0], bounds[1], todo_line)
        else:
            insert_new_section(lines, role, todo_line)

    updated_at = now_local()
    new_text = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
    if added:
        new_text = replace_updated_at(new_text, updated_at)
    if added and not dry_run:
        resolved_state_file.write_text(new_text, encoding="utf-8")

    return {
        "ok": True,
        "dry_run": dry_run,
        "added": added,
        "already_exists": already_exists,
        "goal_id": goal_id,
        "role": role,
        "section": section,
        "todo": todo_text,
        "state_file": str(resolved_state_file),
        "project": str(resolved_project) if resolved_project else None,
        "updated_at": updated_at if added else None,
    }


def render_todo_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Goal Harness Todo",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- dry_run: `{payload.get('dry_run')}`",
        f"- added: `{payload.get('added')}`",
        f"- already_exists: `{payload.get('already_exists')}`",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- role: `{payload.get('role')}`",
        f"- section: `{payload.get('section')}`",
        f"- state_file: `{payload.get('state_file')}`",
    ]
    if payload.get("error"):
        lines.append(f"- error: {payload.get('error')}")
    else:
        lines.extend(["", "## Todo", "", f"- [ ] {payload.get('todo')}"])
    return "\n".join(lines)
