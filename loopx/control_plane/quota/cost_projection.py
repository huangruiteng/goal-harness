"""Read-only usage / cost projection over existing spend events.

RFC C3 (Usage and Cost Projection):

* Raw spend facts already exist (``quota/slot_accounting``); callers must not
  aggregate them manually.
* This module is a pure read projection: it never mutates accounting state.
* ``usage_units`` is deliberately distinguished from ``monetary_cost``
  (RFC §9.3): ``slots`` are usage units, not a currency. Monetary cost can
  later be derived if provider pricing is introduced.
* First version aggregates directly from existing events (RFC §9.4); the same
  contract may later be materialized without changing callers.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..runtime.time import now_utc_iso

#: Classification marker produced by ``quota/slot_accounting``.
QUOTA_SLOT_SPENT_CLASSIFICATION = "quota_slot_spent"

#: Rollout event kind that carries a quota spend receipt.
QUOTA_SPEND_EVENT_KIND = "quota_spend"

#: Optional monetary conversion hook. When set, ``cost_projection`` exposes
#: ``monetary_cost`` in addition to ``usage_units``.
PRICING_PER_USAGE_UNIT: float | None = None


# ---------------------------------------------------------------------------
# Spend fact extraction (normalization over heterogeneous event shapes)
# ---------------------------------------------------------------------------


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _usage_units_of(event: Mapping[str, Any]) -> int:
    """Extract the usage-unit count from any supported spend shape."""
    quota_event = _as_mapping(event.get("quota_event"))
    if quota_event:
        slots = quota_event.get("slots")
        if slots is not None:
            return max(0, _int(slots))
    # Rollout event shape: details carry flat scalar fields.
    details = _as_mapping(event.get("details"))
    if details:
        slots = details.get("slots")
        if slots is not None:
            return max(0, _int(slots))
        slots = details.get("usage_units")
        if slots is not None:
            return max(0, _int(slots))
    return 0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_spend_event(event: Mapping[str, Any]) -> bool:
    if _as_mapping(event.get("quota_event")):
        return True
    if _text(event.get("classification")) == QUOTA_SLOT_SPENT_CLASSIFICATION:
        return True
    if _text(event.get("event_kind")) == QUOTA_SPEND_EVENT_KIND:
        return True
    details = _as_mapping(event.get("details"))
    return _text(details.get("event_type")) == QUOTA_SLOT_SPENT_CLASSIFICATION


def spend_fact(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize one event into a minimal spend fact, or ``None`` if it is not
    a spend event."""
    if not _is_spend_event(event):
        return None
    quota_event = _as_mapping(event.get("quota_event"))
    details = _as_mapping(event.get("details"))
    agent_id = _text(event.get("agent_id")) or _text(quota_event.get("agent_id"))
    todo_id = _text(event.get("todo_id")) or _text(quota_event.get("todo_id"))
    source = _text(quota_event.get("source")) or _text(details.get("source"))
    generated_at = _text(event.get("generated_at")) or _text(event.get("recorded_at"))
    return {
        "goal_id": _text(event.get("goal_id")),
        "todo_id": todo_id,
        "agent_id": agent_id,
        "usage_units": _usage_units_of(event),
        "source": source,
        "generated_at": generated_at,
        "day": generated_at[:10] if len(generated_at) >= 10 else "",
    }


def spend_facts(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project a heterogeneous event stream down to normalized spend facts."""
    facts: list[dict[str, Any]] = []
    for event in events:
        fact = spend_fact(event)
        if fact is not None:
            facts.append(fact)
    return facts


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _cost(usage_units: int) -> float | None:
    if PRICING_PER_USAGE_UNIT is None:
        return None
    return usage_units * PRICING_PER_USAGE_UNIT


def goal_cost_summary(
    goal_id: str,
    events: Sequence[Mapping[str, Any]] | None = None,
    *,
    facts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate usage for one Goal: total + by agent / task / day.

    Accepts either raw ``events`` or already-normalized ``facts``.
    """
    source_facts = facts if facts is not None else spend_facts(events or [])
    by_agent: dict[str, int] = defaultdict(int)
    by_task: dict[str, int] = defaultdict(int)
    by_day: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    total = 0
    for fact in source_facts:
        if _text(fact.get("goal_id")) != _text(goal_id):
            continue
        usage = max(0, _int(fact.get("usage_units")))
        total += usage
        if _text(fact.get("agent_id")):
            by_agent[_text(fact.get("agent_id"))] += usage
        if _text(fact.get("todo_id")):
            by_task[_text(fact.get("todo_id"))] += usage
        if _text(fact.get("day")):
            by_day[_text(fact.get("day"))] += usage
        if _text(fact.get("source")):
            by_source[_text(fact.get("source"))] += usage
    monetary = _cost(total)
    summary: dict[str, Any] = {
        "goal_id": _text(goal_id),
        "total_usage": total,
        "by_agent": dict(sorted(by_agent.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_task": dict(sorted(by_task.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_day": dict(sorted(by_day.items())),
        "by_source": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
        "usage_units": total,
    }
    if monetary is not None:
        summary["monetary_cost"] = round(monetary, 6)
    return summary


def task_cost(
    goal_id: str,
    todo_id: str,
    events: Sequence[Mapping[str, Any]] | None = None,
    *,
    facts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate usage for one Task inside a Goal."""
    source_facts = facts if facts is not None else spend_facts(events or [])
    by_agent: dict[str, int] = defaultdict(int)
    total = 0
    for fact in source_facts:
        if _text(fact.get("goal_id")) != _text(goal_id):
            continue
        if _text(fact.get("todo_id")) != _text(todo_id):
            continue
        usage = max(0, _int(fact.get("usage_units")))
        total += usage
        if _text(fact.get("agent_id")):
            by_agent[_text(fact.get("agent_id"))] += usage
    monetary = _cost(total)
    summary: dict[str, Any] = {
        "goal_id": _text(goal_id),
        "todo_id": _text(todo_id),
        "total_usage": total,
        "by_agent": dict(sorted(by_agent.items(), key=lambda kv: (-kv[1], kv[0]))),
        "usage_units": total,
    }
    if monetary is not None:
        summary["monetary_cost"] = round(monetary, 6)
    return summary


# ---------------------------------------------------------------------------
# Event loading helpers (read-only)
# ---------------------------------------------------------------------------


def _load_run_index_records(runtime_root: Path, goal_id: str) -> list[dict[str, Any]]:
    index_path = Path(runtime_root) / "goals" / goal_id / "runs" / "index.jsonl"
    if not index_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def load_goal_spend_facts(runtime_root: Path, goal_id: str) -> list[dict[str, Any]]:
    """Load normalized spend facts for a Goal from its persisted run index."""
    return spend_facts(_load_run_index_records(runtime_root, goal_id))


def load_all_spend_facts(
    runtime_root: Path,
    goal_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Load normalized spend facts across Goals under a runtime root."""
    root = Path(runtime_root)
    goals_dir = root / "goals"
    if goal_ids is not None:
        goal_list = [str(g).strip() for g in goal_ids if str(g).strip()]
    else:
        goal_list = sorted(
            (p.name for p in goals_dir.iterdir() if p.is_dir()) if goals_dir.exists() else []
        )
    facts: list[dict[str, Any]] = []
    for goal_id in goal_list:
        facts.extend(load_goal_spend_facts(root, goal_id))
    return facts


def project_usage_summary(
    runtime_root: Path,
    goal_ids: Iterable[str] | None = None,
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Read-only usage summary across Goals.

    ``as_of`` (ISO date) optionally limits the projection to spend facts
    generated on or before that date.
    """
    facts = load_all_spend_facts(runtime_root, goal_ids)
    if as_of:
        as_of_day = _text(as_of)[:10]
        facts = [f for f in facts if _text(f.get("day")) <= as_of_day]
    by_goal: dict[str, int] = defaultdict(int)
    for fact in facts:
        by_goal[_text(fact.get("goal_id"))] += max(0, _int(fact.get("usage_units")))
    summary: dict[str, Any] = {
        "projected_at": now_utc_iso(),
        "total_usage": sum(by_goal.values()),
        "by_goal": dict(sorted(by_goal.items(), key=lambda kv: (-kv[1], kv[0]))),
        "usage_units": sum(by_goal.values()),
    }
    monetary = _cost(sum(by_goal.values()))
    if monetary is not None:
        summary["monetary_cost"] = round(monetary, 6)
    return summary
