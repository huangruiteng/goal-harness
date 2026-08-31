from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loopx.capabilities.benchmark_toolkit import (
    admit_benchmark_case,
    build_benchmark_adaptive_concurrency_decision,
    build_benchmark_adaptive_concurrency_policy,
    build_benchmark_concurrency_config,
    configure_benchmark_concurrency_envelope,
    default_benchmark_concurrency_envelope_path,
    read_benchmark_concurrency_envelope,
    tune_benchmark_concurrency_target,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _feedback(
    now: datetime,
    *,
    streak: int = 2,
    launch_attempts: int = 1,
    launch_failures: int = 0,
    provider_capacity_rejections: int = 0,
    runner_invalid_transitions: int = 0,
) -> dict[str, object]:
    return {
        "schema_version": "benchmark_concurrency_feedback_v0",
        "window_started_at": (now - timedelta(minutes=5)).isoformat(),
        "observed_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "saturated_healthy_window_streak": streak,
        "launch_attempts": launch_attempts,
        "launch_failures": launch_failures,
        "provider_capacity_rejections": provider_capacity_rejections,
        "runner_invalid_transitions": runner_invalid_transitions,
    }


def _headroom(now: datetime, *, state: str = "sufficient") -> dict[str, object]:
    return {
        "schema_version": "benchmark_resource_headroom_receipt_v0",
        "observed_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "checks": [
            {"kind": "memory", "state": state},
            {"kind": "provider_capacity", "state": state},
        ],
    }


def _configured_envelope(
    tmp_path: Path, *, target: int = 3, maximum: int = 5, active: int = 3
) -> Path:
    path = default_benchmark_concurrency_envelope_path(
        project=tmp_path, goal_id="fixture-goal"
    )
    configured = configure_benchmark_concurrency_envelope(
        path,
        build_benchmark_concurrency_config(
            max_active_cases=maximum,
            target_active_cases=target,
            max_baseline_cases=maximum,
            max_test_cases=maximum,
        ),
        execute=True,
    )
    assert configured["ok"] is True
    for index in range(active):
        admitted = admit_benchmark_case(
            path,
            run_id=f"run-{index}",
            case_id=f"case-{index}",
            arm_role="treatment",
            execute=True,
        )
        assert admitted["ok"] is True
    return path


def test_saturated_healthy_windows_increase_only_target(tmp_path: Path) -> None:
    path = _configured_envelope(tmp_path)
    now = datetime.now(UTC)
    policy = build_benchmark_adaptive_concurrency_policy()

    result = tune_benchmark_concurrency_target(
        path,
        policy=policy,
        feedback=_feedback(now),
        resource_headroom_receipt=_headroom(now),
        execute=True,
        decided_at=(now + timedelta(seconds=1)).isoformat(),
    )

    stored = read_benchmark_concurrency_envelope(path)
    assert result["action"] == "increase"
    assert result["write_performed"] is True
    assert stored is not None
    assert stored["config"]["target_active_cases"] == 4
    assert stored["config"]["max_active_cases"] == 5
    assert len(stored["active_runs"]) == 3
    assert result["operator_hard_ceiling_changed"] is False
    assert result["active_runs_terminated"] is False


def test_underfilled_or_incomplete_health_streak_holds(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    policy = build_benchmark_adaptive_concurrency_policy()
    underfilled = _configured_envelope(tmp_path / "underfilled", active=2)
    incomplete = _configured_envelope(tmp_path / "incomplete")

    underfilled_result = tune_benchmark_concurrency_target(
        underfilled,
        policy=policy,
        feedback=_feedback(now),
        resource_headroom_receipt=_headroom(now),
        decided_at=(now + timedelta(seconds=1)).isoformat(),
    )
    incomplete_result = tune_benchmark_concurrency_target(
        incomplete,
        policy=policy,
        feedback=_feedback(now, streak=1),
        resource_headroom_receipt=_headroom(now),
        decided_at=(now + timedelta(seconds=1)).isoformat(),
    )

    assert underfilled_result["action"] == "hold"
    assert underfilled_result["reason_codes"] == ["target_not_saturated"]
    assert incomplete_result["action"] == "hold"
    assert incomplete_result["reason_codes"] == [
        "saturated_healthy_window_streak_incomplete"
    ]


def test_missing_stale_or_unresolved_headroom_fails_closed(tmp_path: Path) -> None:
    path = _configured_envelope(tmp_path)
    now = datetime.now(UTC)
    policy = build_benchmark_adaptive_concurrency_policy()

    missing = build_benchmark_adaptive_concurrency_decision(
        read_benchmark_concurrency_envelope(path),
        policy=policy,
        feedback=_feedback(now),
        resource_headroom_receipt=None,
        decided_at=(now + timedelta(seconds=1)).isoformat(),
    )
    stale = build_benchmark_adaptive_concurrency_decision(
        read_benchmark_concurrency_envelope(path),
        policy=policy,
        feedback=_feedback(now),
        resource_headroom_receipt=_headroom(now),
        decided_at=(now + timedelta(minutes=6)).isoformat(),
    )
    unresolved = build_benchmark_adaptive_concurrency_decision(
        read_benchmark_concurrency_envelope(path),
        policy=policy,
        feedback=_feedback(now),
        resource_headroom_receipt=_headroom(now, state="unresolved"),
        decided_at=(now + timedelta(seconds=1)).isoformat(),
    )

    assert missing["action"] == "hold"
    assert missing["reason_codes"] == ["resource_headroom_receipt_required"]
    assert stale["action"] == "hold"
    assert "concurrency_feedback_expired" in stale["reason_codes"]
    assert unresolved["action"] == "hold"
    assert unresolved["reason_codes"] == [
        "memory_unresolved",
        "provider_capacity_unresolved",
    ]


def test_capacity_pressure_decreases_target_without_killing_runs(
    tmp_path: Path,
) -> None:
    path = _configured_envelope(tmp_path, target=4, active=4)
    now = datetime.now(UTC)

    result = tune_benchmark_concurrency_target(
        path,
        policy=build_benchmark_adaptive_concurrency_policy(decrease_step=2),
        feedback=_feedback(now, provider_capacity_rejections=1),
        resource_headroom_receipt=_headroom(now),
        execute=True,
        decided_at=(now + timedelta(seconds=1)).isoformat(),
    )

    stored = read_benchmark_concurrency_envelope(path)
    assert result["action"] == "decrease"
    assert result["next_target_active_cases"] == 2
    assert stored is not None
    assert stored["config"]["target_active_cases"] == 2
    assert len(stored["active_runs"]) == 4
    assert result["status"]["overcommitted"] is False


def test_stale_failure_feedback_holds_instead_of_decreasing(tmp_path: Path) -> None:
    path = _configured_envelope(tmp_path, target=4, active=4)
    now = datetime.now(UTC)

    result = tune_benchmark_concurrency_target(
        path,
        policy=build_benchmark_adaptive_concurrency_policy(),
        feedback=_feedback(now, launch_failures=1),
        resource_headroom_receipt=_headroom(now),
        execute=True,
        decided_at=(now + timedelta(minutes=6)).isoformat(),
    )

    stored = read_benchmark_concurrency_envelope(path)
    assert result["action"] == "hold"
    assert "concurrency_feedback_expired" in result["reason_codes"]
    assert result["write_performed"] is False
    assert stored is not None
    assert stored["config"]["target_active_cases"] == 4


def test_hard_ceiling_and_preview_are_preserved(tmp_path: Path) -> None:
    path = _configured_envelope(tmp_path, target=5, maximum=5, active=5)
    before = path.read_text(encoding="utf-8")
    now = datetime.now(UTC)

    result = tune_benchmark_concurrency_target(
        path,
        policy=build_benchmark_adaptive_concurrency_policy(increase_step=3),
        feedback=_feedback(now),
        resource_headroom_receipt=_headroom(now),
        execute=False,
        decided_at=(now + timedelta(seconds=1)).isoformat(),
    )

    assert result["action"] == "hold"
    assert result["reason_codes"] == ["operator_hard_ceiling_reached"]
    assert result["write_performed"] is False
    assert path.read_text(encoding="utf-8") == before


def test_cli_tune_preview_then_execute(tmp_path: Path) -> None:
    path = _configured_envelope(tmp_path)
    now = datetime.now(UTC)
    feedback_path = tmp_path / "feedback.json"
    headroom_path = tmp_path / "headroom.json"
    feedback_path.write_text(json.dumps(_feedback(now)), encoding="utf-8")
    headroom_path.write_text(json.dumps(_headroom(now)), encoding="utf-8")
    base = [
        str(REPO_ROOT / "scripts/loopx"),
        "benchmark",
        "concurrency-tune",
        "--goal-id",
        "fixture-goal",
        "--project",
        str(tmp_path),
        "--feedback-json",
        str(feedback_path),
        "--resource-headroom-json",
        str(headroom_path),
        "--format",
        "json",
    ]

    preview = subprocess.run(
        base, cwd=REPO_ROOT, text=True, capture_output=True, check=True
    )
    assert json.loads(preview.stdout)["dry_run"] is True
    assert (
        read_benchmark_concurrency_envelope(path)["config"]["target_active_cases"] == 3
    )

    executed = subprocess.run(
        [*base, "--execute"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(executed.stdout)
    assert payload["action"] == "increase"
    assert payload["write_performed"] is True
    assert str(feedback_path) not in executed.stdout
    assert str(headroom_path) not in executed.stdout
    assert (
        read_benchmark_concurrency_envelope(path)["config"]["target_active_cases"] == 4
    )
