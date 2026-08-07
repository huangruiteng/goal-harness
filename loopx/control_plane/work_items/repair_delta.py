from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, cast

from ..runtime.time import now_utc, parse_timestamp
from ..scheduler.monitor_todo import monitor_cadence_delta
from ..todos.contract import (
    TODO_STATUS_DONE,
    TODO_TASK_CLASS_ADVANCEMENT,
    TODO_TASK_CLASS_BLOCKER,
    TODO_TASK_CLASS_MONITOR,
    normalize_todo_claimed_by,
    normalize_todo_id,
    normalize_todo_no_followup,
    normalize_todo_resume_when,
    normalize_todo_status,
)
from ..todos.projection import (
    todo_item_claimed_by_agent_or_unclaimed,
    todo_item_expires_at,
    todo_item_is_actionable_open,
    todo_item_is_expired_monitor,
    todo_item_next_due_at,
    todo_item_task_class,
)
from ..todos.todo_summary import todo_successor_todo_ids

REPAIR_DELTA_KIND_CHOICES = (
    "effective_action",
    "interaction_contract",
    "runnable_todo_set",
    "user_gate",
    "blocker",
    "successor_or_supersede",
    "capability_gate",
    "monitor_target",
    "active_state_next_action",
    "goal_vision_patch",
    "goal_boundary_projection",
    "no_followup",
    "watch_lane_continuation",
)

FRONTIER_REPLAN_ACK_DELTA_KINDS = frozenset(
    {
        "active_state_next_action",
        "blocker",
        "goal_vision_patch",
        "no_followup",
        "runnable_todo_set",
        "successor_or_supersede",
        "watch_lane_continuation",
    }
)

# These deltas change the executable or terminal frontier. Watch/readback-only
# deltas may acknowledge a replan, but they do not by themselves prove an
# accountable delivery that may consume quota.
ACCOUNTABLE_REPLAN_DELTA_KINDS = frozenset(
    {
        "blocker",
        "capability_gate",
        "goal_boundary_projection",
        "goal_vision_patch",
        "no_followup",
        "runnable_todo_set",
        "successor_or_supersede",
    }
)


def normalize_repair_delta_kinds(values: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    allowed = set(REPAIR_DELTA_KIND_CHOICES)
    for value in values or []:
        item = str(value or "").strip()
        if not item:
            continue
        if item not in allowed:
            raise ValueError(
                "repair_delta_kind must be one of: "
                + ", ".join(REPAIR_DELTA_KIND_CHOICES)
            )
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def repair_delta_kinds_have_frontier_delta(values: Iterable[str] | None) -> bool:
    return bool(
        {
            str(item or "").strip()
            for item in (values or [])
            if str(item or "").strip()
        }
        & FRONTIER_REPLAN_ACK_DELTA_KINDS
    )


def repair_delta_kinds_have_accountable_progress(
    values: Iterable[str] | None,
) -> bool:
    return bool(
        {
            str(item or "").strip()
            for item in (values or [])
            if str(item or "").strip()
        }
        & ACCOUNTABLE_REPLAN_DELTA_KINDS
    )


def _todo_is_done(item: dict[str, Any]) -> bool:
    return bool(
        item.get("done") is True
        or normalize_todo_status(item.get("status")) == TODO_STATUS_DONE
    )


def _bounded_watch_todo_ids(
    items: list[dict[str, Any]],
    *,
    observed_at: datetime,
) -> list[str]:
    todo_ids: list[str] = []
    for item in items:
        if not (
            todo_item_is_actionable_open(item)
            and todo_item_task_class(item) == TODO_TASK_CLASS_MONITOR
            and str(item.get("target_key") or "").strip()
            and monitor_cadence_delta(item.get("cadence")) is not None
        ):
            continue
        next_due_at = todo_item_next_due_at(item)
        if next_due_at is None:
            continue
        expires_text = str(item.get("expires_at") or "").strip()
        expires_at = todo_item_expires_at(item)
        if expires_text and expires_at is None:
            continue
        if expires_at is not None and (
            todo_item_is_expired_monitor(item, now=observed_at)
            or expires_at <= next_due_at
        ):
            continue
        resume_when = normalize_todo_resume_when(item.get("resume_when"))
        if resume_when and item.get("resume_ready") is True:
            continue
        if expires_at is None and not resume_when:
            continue
        todo_id = normalize_todo_id(item.get("todo_id"))
        if todo_id:
            todo_ids.append(todo_id)
    return todo_ids


def _todo_source_projection_is_complete(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    items = summary.get("items")
    proof = summary.get("source_proof")
    counts = [
        summary.get(key)
        for key in ("total_count", "open_count", "done_count", "deferred_count")
    ]
    if not all(type(count) is int and count >= 0 for count in counts):
        return False
    total_count, open_count, done_count, deferred_count = cast(
        tuple[int, int, int, int],
        tuple(counts),
    )
    # Open lanes omit source_proof by design, so exact item/count parity is the
    # completeness guard for the unbounded parser used by refresh-state.
    return bool(
        summary.get("schema_version") == "todo_summary_v0"
        and isinstance(items, list)
        and total_count == open_count + done_count
        and deferred_count <= open_count
        and len(items) == total_count
        and (
            proof is None
            or (
                isinstance(proof, dict)
                and proof.get("schema_version") == "todo_source_proof_v0"
                and proof.get("role") == "agent"
                and proof.get("item_count") == total_count
                and proof.get("derived") is True
            )
        )
        and summary.get("source_section") == "Agent Todo"
    )


def _scoped_no_followup_todo_ids(
    summary: dict[str, Any] | None,
    *,
    items: list[dict[str, Any]],
) -> list[str]:
    if not _todo_source_projection_is_complete(summary):
        return []
    completed = [
        (item, todo_id)
        for item in items
        if _todo_is_done(item)
        and (todo_id := normalize_todo_id(item.get("todo_id")))
    ]
    if not completed:
        return []

    def recency(candidate: tuple[dict[str, Any], str]) -> tuple[float, int]:
        item, _ = candidate
        completed_at = parse_timestamp(item.get("completed_at") or item.get("updated_at"))
        index = item.get("index")
        return (
            completed_at.timestamp() if completed_at is not None else float("-inf"),
            index if type(index) is int else -1,
        )

    latest_item, latest_id = max(completed, key=recency)
    if not (
        normalize_todo_no_followup(latest_item.get("no_followup")) is True
        and latest_item.get("route_continuation_replan_required") is not True
    ):
        return []
    return [latest_id]


def _successor_transition_todo_ids(
    items: list[dict[str, Any]],
    *,
    agent_id: str | None,
) -> list[str]:
    by_id = {
        todo_id: item
        for item in items
        if (todo_id := normalize_todo_id(item.get("todo_id")))
    }
    evidence_ids: list[str] = []
    for source in items:
        source_id = normalize_todo_id(source.get("todo_id"))
        if not source_id or not _todo_is_done(source):
            continue
        for successor_id in todo_successor_todo_ids(source, items=items):
            successor = by_id.get(successor_id)
            if not successor or not (
                todo_item_claimed_by_agent_or_unclaimed(
                    successor,
                    agent_id=agent_id,
                )
                and todo_item_is_actionable_open(successor)
                and todo_item_task_class(successor) == TODO_TASK_CLASS_ADVANCEMENT
            ):
                continue
            for todo_id in (source_id, successor_id):
                if todo_id not in evidence_ids:
                    evidence_ids.append(todo_id)
    return evidence_ids


def validate_repair_delta_claims(
    values: Iterable[str],
    *,
    agent_todo_summary: dict[str, Any] | None,
    agent_id: str | None,
    advancement_policy: str,
    next_action_changed: bool,
    vision_patch_written: bool,
    observed_at: datetime | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, str]]]:
    projected_items: Any = (
        agent_todo_summary.get("items")
        if isinstance(agent_todo_summary, dict)
        else None
    )
    items: list[dict[str, Any]] = [
        item
        for item in (projected_items if isinstance(projected_items, list) else [])
        if isinstance(item, dict)
    ]
    normalized_agent_id = normalize_todo_claimed_by(agent_id)
    scoped = [
        item
        for item in items
        if todo_item_claimed_by_agent_or_unclaimed(
            item,
            agent_id=normalized_agent_id,
        )
    ]
    runnable_ids = [
        todo_id
        for item in scoped
        if todo_item_is_actionable_open(item)
        and todo_item_task_class(item) == TODO_TASK_CLASS_ADVANCEMENT
        and (todo_id := normalize_todo_id(item.get("todo_id")))
    ]
    blocker_ids = [
        todo_id
        for item in scoped
        if todo_item_is_actionable_open(item)
        and todo_item_task_class(item) == TODO_TASK_CLASS_BLOCKER
        and (todo_id := normalize_todo_id(item.get("todo_id")))
    ]
    bounded_watch_ids = _bounded_watch_todo_ids(
        scoped,
        observed_at=observed_at or now_utc(),
    )
    successor_transition_ids = _successor_transition_todo_ids(
        items,
        agent_id=normalized_agent_id,
    )
    no_followup_ids = _scoped_no_followup_todo_ids(
        agent_todo_summary,
        items=scoped,
    )

    accepted: list[str] = []
    evidence: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for kind in values:
        reason = ""
        todo_ids: list[str] = []
        if kind not in FRONTIER_REPLAN_ACK_DELTA_KINDS:
            accepted.append(kind)
            continue
        if kind == "runnable_todo_set":
            todo_ids = runnable_ids
            reason = "no scoped open advancement todo exists"
        elif kind == "blocker":
            todo_ids = blocker_ids
            reason = "no scoped open blocker todo exists"
        elif kind == "watch_lane_continuation":
            todo_ids = bounded_watch_ids
            reason = (
                "repeat_until_closed vision requires advancement"
                if advancement_policy == "repeat_until_closed"
                else (
                    "no scoped monitor has a valid target, cadence, next due, "
                    "and unexpired expiry or unresolved resume condition"
                )
            )
            if advancement_policy == "repeat_until_closed":
                todo_ids = []
        elif kind == "successor_or_supersede":
            todo_ids = successor_transition_ids
            reason = "no completed todo links a scoped open advancement successor"
        elif kind == "no_followup":
            todo_ids = no_followup_ids
            reason = (
                "no scoped completed todo has a validated local no-follow-up closure"
            )
        elif kind == "active_state_next_action" and not next_action_changed:
            reason = "active-state Next Action did not change"
        elif kind == "goal_vision_patch" and not vision_patch_written:
            reason = "no vision patch was written"
        elif kind in {"active_state_next_action", "goal_vision_patch"}:
            accepted.append(kind)
            continue
        else:
            rejected.append(
                {
                    "kind": kind,
                    "reason": "frontier delta kind has no evidence resolver",
                }
            )
            continue

        if todo_ids:
            accepted.append(kind)
            evidence.append(
                {
                    "kind": kind,
                    "source": "active_state_agent_todos",
                    "todo_ids": todo_ids,
                }
            )
        else:
            rejected.append({"kind": kind, "reason": reason})
    return accepted, evidence, rejected
