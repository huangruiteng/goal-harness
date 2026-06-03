from __future__ import annotations

from pathlib import Path
from typing import Any

AUTHORITY_REGISTRY_SUMMARY_FIELDS = (
    "declared",
    "required",
    "path",
    "path_exists",
    "read_status",
    "default_entry_count",
    "default_entries_checked",
    "default_entries_present",
    "topic_authority_count",
    "project_material_count",
    "project_material_repository_count",
    "project_material_owner_review_required_count",
    "project_material_stale_count",
    "project_material_current_authority_count",
    "deprecated_source_count",
    "conflict_risk",
)


def _path_text(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text or None


def _resolve_project_path(project: Path | None, path_text: str | None) -> Path | None:
    if not path_text or project is None:
        return None
    path = Path(path_text).expanduser()
    return path if path.is_absolute() else project / path


def _entry_path(value: Any) -> str | None:
    if isinstance(value, str):
        return _path_text(value)
    if isinstance(value, dict):
        return _path_text(value.get("path") or value.get("doc") or value.get("file"))
    return None


def authority_registry_required(goal: dict[str, Any] | None) -> bool:
    if not goal:
        return False
    return bool(goal.get("requires_authority_registry") or goal.get("authority_registry_required"))


def authority_registry_default_entries(raw_entries: Any) -> list[str]:
    entries: list[str] = []
    if isinstance(raw_entries, list):
        for item in raw_entries:
            path = _entry_path(item)
            if path:
                entries.append(path)
    elif isinstance(raw_entries, dict):
        for item in raw_entries.values():
            path = _entry_path(item)
            if path:
                entries.append(path)
    return entries


def authority_registry_topic_count(raw_topics: Any) -> int:
    if isinstance(raw_topics, dict):
        return len(raw_topics)
    if isinstance(raw_topics, list):
        return len(raw_topics)
    return 0


def authority_registry_project_material_stats(raw_materials: Any) -> dict[str, int]:
    if isinstance(raw_materials, dict):
        items = [item for item in raw_materials.values() if isinstance(item, dict)]
    elif isinstance(raw_materials, list):
        items = [item for item in raw_materials if isinstance(item, dict)]
    else:
        items = []

    repository_kinds = {"repository", "repo", "git_repo", "source_repo", "target_repo"}
    owner_review_freshness = {
        "owner_review_required",
        "owner_review_pending",
        "owner_evidence_missing",
        "missing_owner_evidence",
    }
    stale_freshness = {"stale", "outdated", "needs_refresh", "unknown"}
    stats = {
        "project_material_count": len(items),
        "project_material_repository_count": 0,
        "project_material_owner_review_required_count": 0,
        "project_material_stale_count": 0,
        "project_material_current_authority_count": 0,
    }
    for item in items:
        source_kind = str(item.get("source_kind") or item.get("kind") or "").lower()
        role = str(item.get("role") or "").lower()
        freshness = str(item.get("freshness") or item.get("status") or "").lower()
        if source_kind in repository_kinds or source_kind.endswith("_repository"):
            stats["project_material_repository_count"] += 1
        if freshness in owner_review_freshness or item.get("missing_owner_evidence") is True:
            stats["project_material_owner_review_required_count"] += 1
        if freshness in stale_freshness:
            stats["project_material_stale_count"] += 1
        if role == "current_authority" or role.endswith("_authority"):
            stats["project_material_current_authority_count"] += 1
    return stats


def authority_registry_deprecated_count(raw: dict[str, Any]) -> int:
    for key in ("deprecated_source_count", "deprecated_sources_seen"):
        value = raw.get(key)
        if isinstance(value, int):
            return value
    deprecated_sources = raw.get("deprecated_sources")
    if isinstance(deprecated_sources, list):
        return len(deprecated_sources)
    return 0


def compact_authority_registry(goal: dict[str, Any] | None, *, project: Path | None = None) -> dict[str, Any]:
    raw = goal.get("authority_registry") if goal and isinstance(goal.get("authority_registry"), dict) else {}
    if not raw:
        return {
            "declared": False,
            "required": authority_registry_required(goal),
            "path": None,
            "path_exists": None,
            "read_status": None,
            "default_entry_count": 0,
            "default_entries_checked": 0,
            "default_entries_present": 0,
            "topic_authority_count": 0,
            "project_material_count": 0,
            "project_material_repository_count": 0,
            "project_material_owner_review_required_count": 0,
            "project_material_stale_count": 0,
            "project_material_current_authority_count": 0,
            "deprecated_source_count": 0,
            "conflict_risk": "unknown",
            "default_entries": [],
        }

    compact = authority_registry_from_compact(raw)
    if compact:
        path_text = _path_text(compact.get("path"))
        resolved_path = _resolve_project_path(project, path_text)
        if resolved_path:
            compact["path_exists"] = resolved_path.exists()
        compact["default_entries"] = []
        return compact

    path_text = _path_text(raw.get("path"))
    resolved_path = _resolve_project_path(project, path_text)
    default_entries = authority_registry_default_entries(raw.get("default_entry_docs"))
    checked_entries: list[dict[str, Any]] = []
    present = 0
    checked = 0
    for entry_path in default_entries:
        resolved_entry = _resolve_project_path(project, entry_path)
        exists = resolved_entry.exists() if resolved_entry else None
        if exists is not None:
            checked += 1
        if exists:
            present += 1
        checked_entries.append({"path": entry_path, "exists": exists})

    return {
        "declared": True,
        "required": authority_registry_required(goal),
        "path": path_text,
        "path_exists": resolved_path.exists() if resolved_path else None,
        "read_status": raw.get("read_status"),
        "default_entry_count": len(default_entries),
        "default_entries_checked": checked,
        "default_entries_present": present,
        "topic_authority_count": authority_registry_topic_count(raw.get("topic_authority")),
        **authority_registry_project_material_stats(raw.get("project_materials")),
        "deprecated_source_count": authority_registry_deprecated_count(raw),
        "conflict_risk": str(raw.get("conflict_risk") or "unknown"),
        "default_entries": checked_entries,
    }


def authority_registry_summary(goal: dict[str, Any] | None) -> dict[str, Any]:
    compact = compact_authority_registry(goal, project=None)
    compact.pop("default_entries", None)
    return compact


def authority_registry_from_compact(raw: dict[str, Any]) -> dict[str, Any] | None:
    if "declared" not in raw or "default_entry_count" not in raw:
        return None
    return {
        "declared": bool(raw.get("declared")),
        "required": bool(raw.get("required")),
        "path": raw.get("path"),
        "path_exists": raw.get("path_exists"),
        "read_status": raw.get("read_status"),
        "default_entry_count": int(raw.get("default_entry_count") or 0),
        "default_entries_checked": int(raw.get("default_entries_checked") or 0),
        "default_entries_present": int(raw.get("default_entries_present") or 0),
        "topic_authority_count": int(raw.get("topic_authority_count") or 0),
        "project_material_count": int(raw.get("project_material_count") or 0),
        "project_material_repository_count": int(raw.get("project_material_repository_count") or 0),
        "project_material_owner_review_required_count": int(
            raw.get("project_material_owner_review_required_count") or 0
        ),
        "project_material_stale_count": int(raw.get("project_material_stale_count") or 0),
        "project_material_current_authority_count": int(
            raw.get("project_material_current_authority_count") or 0
        ),
        "deprecated_source_count": int(raw.get("deprecated_source_count") or 0),
        "conflict_risk": str(raw.get("conflict_risk") or "unknown"),
    }


def goal_authority_registry_summary(goal: dict[str, Any] | None) -> dict[str, Any]:
    raw = goal.get("authority_registry") if goal and isinstance(goal.get("authority_registry"), dict) else {}
    compact = authority_registry_from_compact(raw) if raw else None
    return compact or authority_registry_summary(goal)
