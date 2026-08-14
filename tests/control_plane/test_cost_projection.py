from __future__ import annotations

from pathlib import Path

from loopx.control_plane.quota.cost_projection import (
    QUOTA_SLOT_SPENT_CLASSIFICATION,
    goal_cost_summary,
    load_all_spend_facts,
    load_goal_spend_facts,
    project_usage_summary,
    spend_fact,
    spend_facts,
    task_cost,
)

GOAL_ID = "cost-projection-fixture"


def _spend_run(
    *,
    todo_id: str,
    agent_id: str,
    slots: int,
    generated_at: str,
    source: str = "eligible",
) -> dict:
    return {
        "generated_at": generated_at,
        "goal_id": GOAL_ID,
        "classification": QUOTA_SLOT_SPENT_CLASSIFICATION,
        "agent_id": agent_id,
        "quota_event": {
            "event_type": QUOTA_SLOT_SPENT_CLASSIFICATION,
            "source": source,
            "todo_id": todo_id,
            "slots": slots,
            "before": {"spent_slots": 0},
            "after": {"spent_slots": slots},
        },
    }


def _facts() -> list[dict]:
    return [
        _spend_run(todo_id="t1", agent_id="a1", slots=3, generated_at="2026-08-13T10:00:00Z"),
        _spend_run(todo_id="t1", agent_id="a1", slots=2, generated_at="2026-08-13T11:00:00Z"),
        _spend_run(todo_id="t2", agent_id="a2", slots=5, generated_at="2026-08-14T09:00:00Z"),
    ]


# ---------------------------------------------------------------------------
# spend_fact normalization
# ---------------------------------------------------------------------------


def test_spend_fact_normalizes_quota_event_shape() -> None:
    fact = spend_fact(_spend_run(todo_id="t1", agent_id="a1", slots=4, generated_at="2026-08-13T12:00:00Z"))
    assert fact is not None
    assert fact["goal_id"] == GOAL_ID
    assert fact["todo_id"] == "t1"
    assert fact["agent_id"] == "a1"
    assert fact["usage_units"] == 4
    assert fact["day"] == "2026-08-13"
    assert fact["source"] == "eligible"


def test_spend_fact_none_for_non_spend_event() -> None:
    assert spend_fact({"goal_id": GOAL_ID, "classification": "state_refreshed"}) is None


def test_spend_fact_supports_rollout_event_shape() -> None:
    event = {
        "goal_id": GOAL_ID,
        "event_kind": "quota_spend",
        "agent_id": "a1",
        "todo_id": "t1",
        "recorded_at": "2026-08-15T08:00:00Z",
        "details": {"slots": 7, "source": "delivery"},
    }
    fact = spend_fact(event)
    assert fact is not None
    assert fact["usage_units"] == 7
    assert fact["day"] == "2026-08-15"
    assert fact["source"] == "delivery"


def test_spend_facts_filters_stream() -> None:
    events = [
        _spend_run(todo_id="t1", agent_id="a1", slots=1, generated_at="2026-08-13T10:00:00Z"),
        {"goal_id": GOAL_ID, "classification": "state_refreshed"},
        {"goal_id": GOAL_ID, "event_kind": "quota_should_run"},
    ]
    facts = spend_facts(events)
    assert len(facts) == 1
    assert facts[0]["usage_units"] == 1


# ---------------------------------------------------------------------------
# goal_cost_summary
# ---------------------------------------------------------------------------


def test_goal_cost_summary_total_and_dimensions() -> None:
    summary = goal_cost_summary(GOAL_ID, _facts())
    assert summary["goal_id"] == GOAL_ID
    assert summary["total_usage"] == 10
    assert summary["by_agent"] == {"a2": 5, "a1": 5}
    assert summary["by_task"] == {"t2": 5, "t1": 5}
    assert summary["by_day"] == {"2026-08-14": 5, "2026-08-13": 5}
    assert summary["by_source"] == {"eligible": 10}


def test_goal_cost_summary_ignores_other_goal() -> None:
    summary = goal_cost_summary("other-goal", _facts())
    assert summary["total_usage"] == 0
    assert summary["by_agent"] == {}
    assert summary["by_day"] == {}


def test_goal_cost_summary_no_monetary_cost_by_default() -> None:
    summary = goal_cost_summary(GOAL_ID, _facts())
    assert "monetary_cost" not in summary
    assert summary["usage_units"] == 10


def test_goal_cost_summary_accepts_precomputed_facts() -> None:
    facts = spend_facts(_facts())
    summary = goal_cost_summary(GOAL_ID, facts=facts)
    assert summary["total_usage"] == 10


# ---------------------------------------------------------------------------
# task_cost
# ---------------------------------------------------------------------------


def test_task_cost_aggregates_single_todo() -> None:
    summary = task_cost(GOAL_ID, "t1", _facts())
    assert summary["total_usage"] == 5
    assert summary["by_agent"] == {"a1": 5}


def test_task_cost_unknown_todo_is_zero() -> None:
    summary = task_cost(GOAL_ID, "missing", _facts())
    assert summary["total_usage"] == 0
    assert summary["by_agent"] == {}


# ---------------------------------------------------------------------------
# File loading helpers
# ---------------------------------------------------------------------------


def _write_index(tmp_path: Path, goal_id: str, records: list[dict]) -> Path:
    index_path = tmp_path / "goals" / goal_id / "runs" / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    import json

    index_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )
    return index_path


def test_load_goal_spend_facts_from_runtime(tmp_path: Path) -> None:
    _write_index(tmp_path, GOAL_ID, _facts())
    facts = load_goal_spend_facts(tmp_path, GOAL_ID)
    assert len(facts) == 3
    assert sum(f["usage_units"] for f in facts) == 10


def test_load_all_spend_facts_across_goals(tmp_path: Path) -> None:
    _write_index(tmp_path, GOAL_ID, _facts())
    _write_index(tmp_path, "g2", [_spend_run(todo_id="t9", agent_id="a9", slots=2, generated_at="2026-08-13T10:00:00Z")])
    facts = load_all_spend_facts(tmp_path)
    assert len(facts) == 4
    assert sum(f["usage_units"] for f in facts) == 12


def test_project_usage_summary(tmp_path: Path) -> None:
    _write_index(tmp_path, GOAL_ID, _facts())
    summary = project_usage_summary(tmp_path)
    assert summary["total_usage"] == 10
    assert summary["by_goal"] == {GOAL_ID: 10}


def test_project_usage_summary_as_of_limit(tmp_path: Path) -> None:
    _write_index(tmp_path, GOAL_ID, _facts())
    summary = project_usage_summary(tmp_path, as_of="2026-08-13")
    assert summary["total_usage"] == 5


def test_load_goal_spend_facts_missing_goal_is_empty(tmp_path: Path) -> None:
    assert load_goal_spend_facts(tmp_path, "nonexistent") == []
