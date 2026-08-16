from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loopx.control_plane.quota.usage_collector import (
    UsageSample,
    collect_usage_for_run,
)
from loopx.control_plane.quota.usage_summary import (
    blank_usage_goal,
    build_usage_summary,
)


def _run(
    goal_id: str,
    *,
    generated_at: datetime,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run: dict[str, Any] = {"goal_id": goal_id, "generated_at": generated_at}
    if usage is not None:
        run["usage"] = usage
    return run


def _identity_parse(value: Any) -> Any:
    return value


def test_blank_usage_goal_has_usage_fields() -> None:
    goal = blank_usage_goal("g1")
    for suffix in ("24h", "7d"):
        assert goal[f"input_tokens_{suffix}"] == 0
        assert goal[f"output_tokens_{suffix}"] == 0
        assert goal[f"cache_tokens_{suffix}"] == 0
        assert goal[f"cost_usd_{suffix}"] == 0.0
        assert goal[f"duration_ms_{suffix}"] == 0


def test_collect_usage_for_run_returns_none_without_usage_block() -> None:
    assert collect_usage_for_run({"goal_id": "g1"}) is None
    assert collect_usage_for_run({"goal_id": "g1", "usage": "not-a-dict"}) is None


def test_collect_usage_for_run_returns_none_when_no_tokens() -> None:
    # cost alone, with no tokens, is not aggregate-worthy.
    assert collect_usage_for_run({"usage": {"cost_usd": 0.1}}) is None


def test_collect_usage_for_run_normalizes_fields() -> None:
    sample = collect_usage_for_run(
        {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_tokens": 20,
                "cost_usd": 0.2,
                "duration_ms": 5000,
                "provider": "codex",
                "model": "codex-1",
            }
        }
    )
    assert sample == UsageSample(100, 50, 20, 0.2, 5000, "codex", "codex-1")


def test_build_usage_summary_aggregates_usage_within_windows() -> None:
    now = datetime.now(timezone.utc)
    history = {
        "runs": [
            _run(
                "g1",
                generated_at=now,
                usage={
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_tokens": 20,
                    "cost_usd": 0.1,
                    "duration_ms": 1000,
                    "provider": "codex",
                    "model": "codex",
                },
            ),
            _run(
                "g1",
                generated_at=now,
                usage={
                    "input_tokens": 200,
                    "output_tokens": 60,
                    "cost_usd": 0.2,
                    "duration_ms": 2000,
                    "provider": "codex",
                    "model": "codex",
                },
            ),
        ]
    }
    summary = build_usage_summary(history, parse_timestamp=_identity_parse)
    totals = summary["totals"]
    assert totals["input_tokens_24h"] == 300
    assert totals["output_tokens_24h"] == 110
    assert totals["cache_tokens_24h"] == 20
    assert totals["cost_usd_24h"] == round(0.1 + 0.2, 6)
    assert totals["duration_ms_24h"] == 3000
    goal = summary["goals"][0]
    assert goal["goal_id"] == "g1"
    assert goal["input_tokens_24h"] == 300


def test_build_usage_summary_degrades_when_runs_report_no_usage() -> None:
    now = datetime.now(timezone.utc)
    history = {"runs": [_run("g1", generated_at=now)]}
    summary = build_usage_summary(history, parse_timestamp=_identity_parse)
    for bucket in (summary["totals"], summary["goals"][0]):
        assert "input_tokens_24h" not in bucket
        assert "cost_usd_24h" not in bucket
        assert "duration_ms_24h" not in bucket
        assert "input_tokens_7d" not in bucket
        assert "cost_usd_7d" not in bucket
        assert "duration_ms_7d" not in bucket
    # existing run accounting still works alongside the new fields
    assert summary["totals"]["runs_24h"] == 1


def test_build_usage_summary_only_emits_windows_with_usage_samples() -> None:
    now = datetime.now(timezone.utc)
    history = {
        "runs": [
            _run(
                "g1",
                generated_at=now - timedelta(days=2),
                usage={
                    "input_tokens": 25,
                    "output_tokens": 5,
                    "provider": "codex",
                    "model": "codex",
                },
            )
        ]
    }
    summary = build_usage_summary(history, parse_timestamp=_identity_parse)
    for bucket in (summary["totals"], summary["goals"][0]):
        assert "input_tokens_24h" not in bucket
        assert bucket["input_tokens_7d"] == 25
        assert bucket["output_tokens_7d"] == 5


def test_build_usage_summary_keeps_old_runs_out_of_usage_windows() -> None:
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)
    history = {
        "runs": [
            _run(
                "g1",
                generated_at=now,
                usage={
                    "input_tokens": 100,
                    "output_tokens": 1,
                    "provider": "codex",
                    "model": "codex",
                },
            ),
            _run(
                "g1",
                generated_at=old,
                usage={
                    "input_tokens": 999,
                    "output_tokens": 1,
                    "provider": "codex",
                    "model": "codex",
                },
            ),
        ]
    }
    summary = build_usage_summary(history, parse_timestamp=_identity_parse)
    assert summary["totals"]["input_tokens_7d"] == 100
    assert summary["totals"]["input_tokens_24h"] == 100


def test_build_usage_summary_is_provider_neutral() -> None:
    now = datetime.now(timezone.utc)
    history = {
        "runs": [
            _run(
                "g1",
                generated_at=now,
                usage={
                    "input_tokens": 10,
                    "output_tokens": 1,
                    "provider": "codex",
                    "model": "codex",
                },
            ),
            _run(
                "g1",
                generated_at=now,
                usage={
                    "input_tokens": 40,
                    "output_tokens": 1,
                    "provider": "claude",
                    "model": "claude-x",
                },
            ),
        ]
    }
    summary = build_usage_summary(history, parse_timestamp=_identity_parse)
    assert summary["totals"]["input_tokens_24h"] == 50


def test_build_usage_summary_rounds_cost_to_avoid_float_drift() -> None:
    now = datetime.now(timezone.utc)
    history = {
        "runs": [
            _run(
                "g1",
                generated_at=now,
                usage={
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_usd": 0.1,
                    "provider": "x",
                    "model": "y",
                },
            ),
            _run(
                "g1",
                generated_at=now,
                usage={
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_usd": 0.2,
                    "provider": "x",
                    "model": "y",
                },
            ),
        ]
    }
    summary = build_usage_summary(history, parse_timestamp=_identity_parse)
    assert summary["totals"]["cost_usd_24h"] == 0.3


def test_collect_usage_for_run_rejects_bool_tokens() -> None:
    # bool is not a valid token count and must not be accepted as 1.
    sample = collect_usage_for_run(
        {"usage": {"input_tokens": True, "output_tokens": 10}}
    )
    assert sample is not None
    assert sample.input_tokens == 0
    assert sample.output_tokens == 10


def test_collect_usage_for_run_rejects_negative_tokens() -> None:
    sample = collect_usage_for_run(
        {"usage": {"input_tokens": -100, "output_tokens": 10}}
    )
    assert sample is not None
    assert sample.input_tokens == 0
    assert sample.output_tokens == 10


def test_collect_usage_for_run_rejects_non_numeric_tokens() -> None:
    # a numeric string is not coerced; only real numbers count.
    sample = collect_usage_for_run(
        {"usage": {"input_tokens": "100", "output_tokens": 10}}
    )
    assert sample is not None
    assert sample.input_tokens == 0
    assert sample.output_tokens == 10


def test_collect_usage_for_run_rejects_negative_cost() -> None:
    sample = collect_usage_for_run(
        {"usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": -0.5}}
    )
    assert sample is not None
    assert sample.cost_usd == 0.0
