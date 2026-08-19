from __future__ import annotations

import re
from typing import Any

from ..runtime.time import parse_timestamp
from .contract import (
    TODO_MONITOR_METADATA_FIELDS,
    TODO_TASK_CLASS_MONITOR,
    normalize_todo_watch_only,
)


MONITOR_CADENCE_PATTERN = re.compile(
    r"^\s*(?P<count>[1-9][0-9]{0,4})\s*"
    r"(?P<unit>s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\s*$",
    re.IGNORECASE,
)


def normalize_monitor_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key not in TODO_MONITOR_METADATA_FIELDS:
            continue
        if value is None:
            normalized[key] = None
            continue
        candidate = str(value or "").strip()
        if candidate:
            normalized[key] = candidate
    if normalized.get("cadence") is not None and not MONITOR_CADENCE_PATTERN.match(normalized["cadence"]):
        raise ValueError("--cadence must look like 30m, 2h, or 1d")
    if normalized.get("next_due_at") is not None and parse_timestamp(normalized["next_due_at"]) is None:
        raise ValueError("--next-due-at must be an ISO timestamp")
    if normalized.get("expires_at") is not None and parse_timestamp(normalized["expires_at"]) is None:
        raise ValueError("--expires-at must be an ISO timestamp")
    if normalized.get("last_checked_at") is not None and parse_timestamp(normalized["last_checked_at"]) is None:
        raise ValueError("--last-checked-at must be an ISO timestamp")
    if normalized.get("consecutive_no_change") is not None:
        try:
            int(normalized["consecutive_no_change"])
        except ValueError as exc:
            raise ValueError("--consecutive-no-change must be an integer") from exc
    if normalized.get("material_change") is not None and normalized["material_change"] not in {"true", "false"}:
        raise ValueError("--material-change metadata must be true or false")
    if normalized.get("watch_only") is not None and normalize_todo_watch_only(
        normalized["watch_only"]
    ) is None:
        raise ValueError("--watch-only metadata must be true or false")
    return normalized


def require_continuous_monitor_boundedness(
    *,
    task_class: str | None,
    resume_when: str | None,
    monitor_metadata: dict[str, Any] | None,
) -> None:
    if task_class != TODO_TASK_CLASS_MONITOR:
        return
    metadata = monitor_metadata or {}
    if (
        str(metadata.get("expires_at") or "").strip()
        or str(resume_when or "").strip()
        or normalize_todo_watch_only(metadata.get("watch_only")) is True
    ):
        return
    raise ValueError(
        "continuous_monitor requires one of: --expires-at, --resume-when, "
        "or --watch-only"
    )


def require_monitor_metadata_scope(
    *,
    monitor_metadata: dict[str, Any] | None,
    role: str,
    task_class: str | None,
) -> dict[str, Any]:
    normalized = normalize_monitor_metadata(monitor_metadata)
    if not normalized:
        return {}
    schedule_fields = {k for k, v in normalized.items() if v is not None and k != "target_key"}
    if schedule_fields and (role != "agent" or task_class != "continuous_monitor"):
        raise ValueError(
            "monitor schedule metadata requires --role agent --task-class continuous_monitor"
        )
    if normalized.get("target_key") is not None and role != "agent":
        raise ValueError("target_key requires --role agent")
    return normalized
