from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from ..runtime.public_safety import public_safe_compact_text
from ..runtime.time import parse_timestamp, utc_isoformat
from .goal_channel_projection import GOAL_CHANNEL_PROJECTION_SCHEMA_VERSION

COLLABORATION_STATUS_SCHEMA_VERSION = "loopx_collaboration_status_v0"
COLLABORATION_VISIBILITY = "internal_collaboration"
DEFAULT_MAX_AGE_SECONDS = 300
DEFAULT_TODO_ITEM_LIMIT = 3

_AUTH_MATERIAL_PATTERN = re.compile(
    r"(?i)(?:"
    r"\bauthorization\s*[:=]|"
    r"\bcookie\s*[:=]|"
    r"\b(?:app|client)[_-]?secret\s*[:=]|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r")"
)
_LOCAL_PATH_PATTERN = re.compile(
    r"(?i)(?:^|[\s`'\"(])(?:/(?:home|users|volumes|private|tmp|var/tmp|data\d*)/|[a-z]:\\)"
)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _collaboration_text(value: Any, *, limit: int) -> str | None:
    text = public_safe_compact_text(value, limit=limit)
    if (
        text is None
        or _AUTH_MATERIAL_PATTERN.search(text)
        or _LOCAL_PATH_PATTERN.search(text)
    ):
        return None
    return text


def _first_text(*values: Any, limit: int) -> str | None:
    for value in values:
        text = _collaboration_text(value, limit=limit)
        if text:
            return text
    return None


def _count(summary: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _todo_item(
    item: Mapping[str, Any],
    *,
    role: str,
    redacted_fields: list[str],
) -> dict[str, Any] | None:
    title = _first_text(item.get("title"), item.get("text"), limit=260)
    if not title:
        redacted_fields.append(f"todos.{role}.items[].title")
        return None
    result: dict[str, Any] = {"title": title}
    for key, limit in (
        ("todo_id", 120),
        ("priority", 20),
        ("status", 20),
        ("claimed_by", 120),
        ("bound_agent", 120),
        ("task_repository", 240),
    ):
        value = _collaboration_text(item.get(key), limit=limit)
        if value:
            result[key] = value
        elif item.get(key):
            redacted_fields.append(f"todos.{role}.items[].{key}")
    return result


def _summary_projection(
    *,
    role: str,
    canonical_summary: Mapping[str, Any],
    compact_summary: Mapping[str, Any],
    projected_items: Sequence[Mapping[str, Any]],
    item_limit: int,
    blockers: list[dict[str, str]],
    redacted_fields: list[str],
) -> dict[str, Any]:
    open_count = _count(canonical_summary, "open_count", "open")
    if open_count is None:
        blockers.append(
            {
                "code": f"{role}_todo_summary_missing",
                "message": f"{role} Todo summary has no valid open count",
            }
        )
        open_count = 0
    compact_open_count = _count(compact_summary, "open", "open_count")
    if compact_summary and compact_open_count is None:
        blockers.append(
            {
                "code": f"{role}_todo_compact_count_missing",
                "message": f"{role} compact Todo summary has no valid open count",
            }
        )
    elif compact_open_count is not None and compact_open_count != open_count:
        blockers.append(
            {
                "code": f"{role}_todo_count_conflict",
                "message": f"{role} Todo projections disagree on the open count",
            }
        )
    if len(projected_items) > open_count:
        blockers.append(
            {
                "code": f"{role}_todo_projection_overflow",
                "message": f"{role} projected Todo rows exceed the canonical open count",
            }
        )

    items: list[dict[str, Any]] = []
    for item in list(projected_items)[: max(0, item_limit)]:
        compact = _todo_item(item, role=role, redacted_fields=redacted_fields)
        if compact:
            items.append(compact)
    return {
        "open_count": open_count,
        "visible_count": len(items),
        "truncated": open_count > len(projected_items)
        or len(projected_items) > len(items),
        "items": items,
    }


def _freshness(
    *,
    snapshot_generated_at: Any,
    now: datetime,
    max_age_seconds: int,
    blockers: list[dict[str, str]],
) -> dict[str, Any]:
    parsed = parse_timestamp(snapshot_generated_at)
    if parsed is None:
        blockers.append(
            {
                "code": "snapshot_time_invalid",
                "message": "collaboration status snapshot time is missing or invalid",
            }
        )
        return {
            "state": "invalid",
            "generated_at": None,
            "max_age_seconds": max(0, int(max_age_seconds)),
        }
    age_seconds = (now - parsed).total_seconds()
    safe_max_age = max(0, int(max_age_seconds))
    state = "fresh"
    if age_seconds < -60:
        state = "invalid"
        blockers.append(
            {
                "code": "snapshot_time_in_future",
                "message": "collaboration status snapshot time is unexpectedly in the future",
            }
        )
    elif age_seconds > safe_max_age:
        state = "stale"
        blockers.append(
            {
                "code": "snapshot_stale",
                "message": "collaboration status snapshot exceeded its freshness window",
            }
        )
    return {
        "state": state,
        "generated_at": utc_isoformat(parsed),
        "age_seconds": round(max(0.0, age_seconds), 3),
        "max_age_seconds": safe_max_age,
    }


def build_collaboration_status(
    status_payload: Mapping[str, Any],
    *,
    goal_id: str,
    snapshot_generated_at: str | None = None,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    item_limit: int = DEFAULT_TODO_ITEM_LIMIT,
) -> dict[str, Any]:
    """Build a collaboration-safe, read-only status for one LoopX Goal.

    Runtime values may retain real work context intended for authorized peers.
    The projection omits credential-like material, provider payloads, and local
    paths while preserving the LoopX status/Todo counts as task truth.
    """

    safe_goal_id = str(goal_id or "").strip()
    blockers: list[dict[str, str]] = []
    redacted_fields: list[str] = []
    queue = _as_mapping(status_payload.get("attention_queue"))
    matching_items = [
        item
        for item in _as_mappings(queue.get("items"))
        if str(item.get("goal_id") or "") == safe_goal_id
    ]
    if not safe_goal_id:
        blockers.append(
            {"code": "goal_id_required", "message": "a Goal id is required"}
        )
    if len(matching_items) != 1:
        blockers.append(
            {
                "code": "goal_status_not_unique",
                "message": "exactly one matching Goal status item is required",
            }
        )
    item = matching_items[0] if len(matching_items) == 1 else {}
    projection = _as_mapping(item.get("goal_channel_projection"))
    project_asset = _as_mapping(item.get("project_asset"))

    if status_payload.get("ok") is not True:
        blockers.append(
            {
                "code": "status_contract_unhealthy",
                "message": "the source LoopX status contract is not healthy",
            }
        )
    if projection.get("schema_version") != GOAL_CHANNEL_PROJECTION_SCHEMA_VERSION:
        blockers.append(
            {
                "code": "goal_projection_missing",
                "message": "the Goal channel projection is missing or incompatible",
            }
        )
    if projection.get("mode") != "read_only":
        blockers.append(
            {
                "code": "goal_projection_not_read_only",
                "message": "the Goal channel projection is not read-only",
            }
        )
    truth = _as_mapping(projection.get("truth_contract"))
    if (
        truth.get("event_ledger_is_source_of_truth") is not True
        or truth.get("projection_is_writable") is not False
        or truth.get("write_authority") != "none"
    ):
        blockers.append(
            {
                "code": "truth_contract_invalid",
                "message": "the projection does not preserve the LoopX truth contract",
            }
        )

    canonical_user = _as_mapping(item.get("user_todos"))
    canonical_agent = _as_mapping(item.get("agent_todos"))
    user_items = _as_mappings(projection.get("user_todos"))
    agent_items = _as_mappings(projection.get("agent_todos"))
    user_todos = _summary_projection(
        role="user",
        canonical_summary=canonical_user,
        compact_summary=_as_mapping(project_asset.get("user_todos")),
        projected_items=user_items,
        item_limit=item_limit,
        blockers=blockers,
        redacted_fields=redacted_fields,
    )
    agent_todos = _summary_projection(
        role="agent",
        canonical_summary=canonical_agent,
        compact_summary=_as_mapping(project_asset.get("agent_todos")),
        projected_items=agent_items,
        item_limit=item_limit,
        blockers=blockers,
        redacted_fields=redacted_fields,
    )

    current_time = now or datetime.now(UTC).replace(microsecond=0)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    else:
        current_time = current_time.astimezone(UTC)
    effective_generated_at = snapshot_generated_at or utc_isoformat(current_time)
    freshness = _freshness(
        snapshot_generated_at=effective_generated_at,
        now=current_time,
        max_age_seconds=max_age_seconds,
        blockers=blockers,
    )

    display_name = _first_text(
        projection.get("display_name"),
        item.get("display_name"),
        safe_goal_id,
        limit=140,
    )
    latest_status = _first_text(
        projection.get("latest_status"), item.get("status"), limit=160
    )
    next_action = _first_text(
        projection.get("next_action"),
        project_asset.get("next_action"),
        item.get("recommended_action"),
        limit=360,
    )
    if not display_name:
        redacted_fields.append("goal.display_name")
    if not latest_status:
        redacted_fields.append("state.status")
    if not next_action:
        redacted_fields.append("state.next_action")

    visible_agent_items = agent_todos["items"]
    visible_user_items = user_todos["items"]
    focus = _first_text(
        visible_agent_items[0].get("title") if visible_agent_items else None,
        visible_user_items[0].get("title") if visible_user_items else None,
        next_action,
        limit=300,
    )
    open_gates = _as_mappings(projection.get("open_gates"))
    gate_summary = _first_text(
        visible_user_items[0].get("title") if visible_user_items else None,
        open_gates[0].get("kind") if open_gates else None,
        limit=240,
    )

    projected_goal_id = _collaboration_text(safe_goal_id, limit=140)
    if safe_goal_id and not projected_goal_id:
        redacted_fields.append("goal.goal_id")
    publishable = not blockers
    return {
        "schema_version": COLLABORATION_STATUS_SCHEMA_VERSION,
        "ok": publishable,
        "publishable": publishable,
        "visibility": COLLABORATION_VISIBILITY,
        "goal": {
            "goal_id": projected_goal_id or "goal",
            "display_name": display_name or projected_goal_id or "goal",
        },
        "state": {
            "status": latest_status,
            "waiting_on": _first_text(
                projection.get("waiting_on"), item.get("waiting_on"), limit=100
            ),
            "focus": focus,
            "next_action": next_action,
        },
        "todos": {"user": user_todos, "agent": agent_todos},
        "owner_gate": {
            "open": bool(open_gates or user_todos["open_count"]),
            "count": max(len(open_gates), int(user_todos["open_count"])),
            "summary": gate_summary,
        },
        "freshness": freshness,
        "redacted_fields": sorted(set(redacted_fields)),
        "blockers": blockers,
        "truth_contract": {
            "source": "LoopX event ledger and derived status projections",
            "projection_is_writable": False,
            "write_authority": "none",
        },
    }
