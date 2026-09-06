"""Deterministic active-Todo Markdown projection.

The user/agent Todo sections are machine-owned after authority promotion.
Everything outside those sections remains opaque human-authored Markdown and
is preserved byte-for-byte. Canonical provider records remain the truth; the
readable Markdown syntax is regenerated and then parsed back for parity.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..coordination.coordination_state_contract import (
    TODO_CANONICAL_READ_RECORD_FIELDS,
    TODO_CANONICAL_REQUIRED_READ_FIELDS,
    canonical_record_fields,
)
from .active_state_editing import TODO_SECTION_HEADINGS
from .machine_region import find_todo_regions, todo_region_marker
from .active_state_todo_parser import parse_active_state_todos
from .contract import (
    TODO_METADATA_FIELDS,
    TODO_STATUS_OPEN,
    format_todo_metadata_line,
    normalize_todo_status,
    todo_marker_for_status,
)
from .todo_summary import canonical_todo_read_record


TODO_SECTION_PROJECTION_SCHEMA_VERSION = "loopx_todo_section_projection_v0"
_MARKER_PATTERN = re.compile(
    r"(?m)^<!-- loopx:todo-section-projection-v0 "
    r"role=(?P<role>user|agent) "
    r"provider_revision=(?P<revision>[A-Za-z0-9_.:-]+) "
    r"records_sha256=(?P<digest>[a-f0-9]{64}) -->\r?$"
)


class TodoSectionProjectionError(ValueError):
    """Canonical records or Markdown violate the projection contract."""


@dataclass(frozen=True)
class TodoSectionProjectionResult:
    markdown: str
    changed: bool
    source_sha256: str
    rendered_sha256: str
    narrative_sha256: str
    provider_revision: str
    todo_count: int
    section_record_sha256: dict[str, str]


@dataclass(frozen=True)
class _SectionSpan:
    role: str
    start: int
    end: int


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_records(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    canonical: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, value in enumerate(records):
        record = canonical_record_fields(
            value,
            fields=TODO_CANONICAL_READ_RECORD_FIELDS,
            required_fields=TODO_CANONICAL_REQUIRED_READ_FIELDS,
            label=f"canonical Todo projection record {index}",
            reject_unknown=True,
        )
        todo_id = str(record.get("todo_id") or "")
        if todo_id in seen:
            raise TodoSectionProjectionError(f"duplicate canonical Todo id: {todo_id}")
        seen.add(todo_id)
        if record.get("role") not in TODO_SECTION_HEADINGS:
            raise TodoSectionProjectionError(f"Todo {todo_id!r} has invalid role")
        if record.get("archive_state") != "active":
            raise TodoSectionProjectionError(
                f"Todo {todo_id!r} is not part of an active Markdown Todo section"
            )
        canonical_todo_read_record(record, reject_unknown=True)
        canonical.append(record)
    return canonical


def _record_sort_key(record: Mapping[str, object]) -> tuple[int, str]:
    raw_index = record.get("index")
    try:
        index = int(raw_index) if isinstance(raw_index, (str, int)) else 2**31 - 1
    except (TypeError, ValueError):
        index = 2**31 - 1
    return index, str(record.get("todo_id") or "")


def _section_spans(markdown: str) -> dict[str, _SectionSpan]:
    lines = markdown.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    spans: dict[str, _SectionSpan] = {}
    for region in find_todo_regions(lines):
        if region.role in spans:
            raise TodoSectionProjectionError(
                f"active Markdown contains multiple {region.role} Todo sections"
            )
        spans[region.role] = _SectionSpan(region.role, offsets[region.start], offsets[region.end])
    return spans


def _narrative_segments(markdown: str) -> list[str]:
    spans = sorted(_section_spans(markdown).values(), key=lambda span: span.start)
    cursor = 0
    parts: list[str] = []
    for span in spans:
        parts.append(markdown[cursor : span.start])
        cursor = span.end
    parts.append(markdown[cursor:])
    return parts


def _render_record(record: Mapping[str, object]) -> list[str]:
    status = normalize_todo_status(record.get("status")) or TODO_STATUS_OPEN
    text = " ".join(str(record.get("text") or "").strip().split())
    if not text:
        raise TodoSectionProjectionError(
            f"Todo {record.get('todo_id')!r} has empty projection text"
        )
    metadata_values = {
        field: record[field]
        for field in TODO_METADATA_FIELDS
        if field in record and record[field] is not None
    }
    metadata = format_todo_metadata_line(**metadata_values)
    return [
        f"- [{todo_marker_for_status(status)}] {text}",
        *([metadata] if metadata else []),
    ]


def _render_section(
    *,
    role: str,
    records: list[dict[str, object]],
    provider_revision: str,
    newline: str,
) -> tuple[str, str]:
    digest = _sha256_text(_canonical_json(records))
    lines = [
        f"## {TODO_SECTION_HEADINGS[role]}",
        todo_region_marker(role, "begin"),
        f"<!-- loopx:todo-section-projection-v0 role={role} "
        f"provider_revision={provider_revision} records_sha256={digest} -->",
        "",
    ]
    for record in records:
        lines.extend(_render_record(record))
    lines.append(todo_region_marker(role, "end"))
    lines.append("")
    return newline.join(lines), digest


def _replace_existing_sections(
    markdown: str,
    *,
    rendered_sections: Mapping[str, str],
) -> str:
    result = markdown
    for span in sorted(
        _section_spans(markdown).values(), key=lambda value: value.start, reverse=True
    ):
        result = result[: span.start] + rendered_sections[span.role] + result[span.end :]
    return result


def _parsed_active_records(markdown: str) -> list[dict[str, Any]]:
    fields = parse_active_state_todos(markdown, item_limit=None)
    records: list[dict[str, Any]] = []
    for role in TODO_SECTION_HEADINGS:
        summary = fields.get(f"{role}_todos")
        items = summary.get("items") if isinstance(summary, dict) else []
        for item in items or []:
            if isinstance(item, dict) and item.get("archive_state") == "active":
                records.append(canonical_todo_read_record(item, reject_unknown=False))
    return records


_DERIVED_READ_MODEL_FIELDS = {
    "created_by",
    "last_actor_agent_id",
    "resume_condition",
    "resume_ready",
    "completion_validation_required",
    "handoff_note",
}


def _parity_records(records: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            field: record[field]
            for field in TODO_CANONICAL_READ_RECORD_FIELDS
            if field in record and field not in _DERIVED_READ_MODEL_FIELDS
        }
        for record in records
    ]


def render_canonical_todo_sections(
    markdown: str,
    records: Sequence[Mapping[str, object]],
    *,
    provider_revision: str,
) -> TodoSectionProjectionResult:
    """Replace only Todo sections and verify deterministic parse/render parity."""

    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", provider_revision):
        raise TodoSectionProjectionError("provider_revision must be a public-safe token")
    canonical = _canonical_records(records)
    source_spans = _section_spans(markdown)
    missing_roles = sorted(set(TODO_SECTION_HEADINGS).difference(source_spans))
    if missing_roles:
        raise TodoSectionProjectionError(
            "active Markdown omits required Todo sections: " + ", ".join(missing_roles)
        )
    lossy_fields = sorted(
        {
            field
            for record in canonical
            for field in _DERIVED_READ_MODEL_FIELDS
            if field in record and record[field] not in (None, False, "", [], {})
        }
    )
    if lossy_fields:
        raise TodoSectionProjectionError(
            "canonical Todo fields are not representable in Markdown: "
            + ", ".join(lossy_fields)
        )
    by_role = {
        role: sorted(
            [record for record in canonical if record.get("role") == role],
            key=_record_sort_key,
        )
        for role in TODO_SECTION_HEADINGS
    }
    newline = "\r\n" if "\r\n" in markdown else "\n"
    rendered_sections: dict[str, str] = {}
    section_digests: dict[str, str] = {}
    for role in TODO_SECTION_HEADINGS:
        rendered_sections[role], section_digests[role] = _render_section(
            role=role,
            records=by_role[role],
            provider_revision=provider_revision,
            newline=newline,
        )

    rendered = _replace_existing_sections(
        markdown,
        rendered_sections=rendered_sections,
    )
    before_narrative = _narrative_segments(markdown)
    after_narrative = _narrative_segments(rendered)
    if before_narrative != after_narrative:
        raise TodoSectionProjectionError("render changed Markdown outside Todo sections")

    expected = _parity_records(
        [*by_role["user"], *by_role["agent"]]
    )
    # Validate the generated payload, independently of unrelated document text.
    actual = _parity_records(_parsed_active_records("\n".join(rendered_sections.values())))
    if _canonical_json(actual) != _canonical_json(expected):
        raise TodoSectionProjectionError("Todo section parse/render parity mismatch")
    second = _replace_existing_sections(rendered, rendered_sections=rendered_sections)
    if second != rendered:
        raise TodoSectionProjectionError("Todo section projection is not idempotent")

    return TodoSectionProjectionResult(
        markdown=rendered,
        changed=rendered != markdown,
        source_sha256=_sha256_text(markdown),
        rendered_sha256=_sha256_text(rendered),
        narrative_sha256=_sha256_text(_canonical_json(after_narrative)),
        provider_revision=provider_revision,
        todo_count=len(canonical),
        section_record_sha256=section_digests,
    )


def inspect_todo_section_projection(markdown: str) -> dict[str, object]:
    """Return compact marker diagnostics without treating Markdown as truth."""

    markers = [match.groupdict() for match in _MARKER_PATTERN.finditer(markdown)]
    return {
        "schema_version": TODO_SECTION_PROJECTION_SCHEMA_VERSION,
        "section_count": len(markers),
        "sections": markers,
    }


__all__ = [
    "TODO_SECTION_PROJECTION_SCHEMA_VERSION",
    "TodoSectionProjectionError",
    "TodoSectionProjectionResult",
    "inspect_todo_section_projection",
    "render_canonical_todo_sections",
]
