#!/usr/bin/env python3
"""Smoke-test SkillsBench verifier bootstrap missing-score attribution."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.status import compact_benchmark_run  # noqa: E402
from loopx.benchmark_adapters.skillsbench_verifier_bootstrap import (  # noqa: E402
    apply_skillsbench_verifier_bootstrap_missing_score_attribution,
)


def _missing_score_compact() -> dict:
    return {
        "schema_version": "benchmark_run_v0",
        "source_runner": "official_skillsbench_benchflow_launch_failure",
        "mode": "skillsbench_codex_app_server_goal_baseline",
        "route": "codex-app-server-goal-baseline",
        "dataset": "skillsbench@1.1",
        "task_id": "powerlifting-coef-calc",
        "agent": "codex",
        "model": "gpt-5.5-codex",
        "official_score_status": "missing",
        "official_score": None,
        "official_task_score": {
            "kind": "skillsbench_verifier_reward_missing",
            "value": None,
            "passed": False,
        },
        "score_failure_attribution": "skillsbench_runner_error",
        "failure_attribution_labels": [
            "official_score_missing",
            "skillsbench_runner_setup_error",
        ],
        "runner_failure": {
            "schema_version": "skillsbench_runner_failure_v0",
            "failure_class": "skillsbench_runner_error",
            "raw_logs_read": False,
            "raw_task_text_read": False,
            "raw_trajectory_read": False,
        },
        "validation": {
            "raw_verifier_output_read": False,
            "raw_logs_read": False,
            "raw_task_text_read": False,
            "raw_trajectory_read": False,
        },
    }


def _uv_bootstrap_plan() -> dict:
    return {
        "task_staging": {
            "schema_version": "skillsbench_task_staging_v0",
            "staged": True,
            "verifier_uv_bootstrap_risk_detected": True,
            "verifier_uv_bootstrap_mirror_patch_required": True,
            "verifier_uv_bootstrap_mirror_patch_applied": True,
            "verifier_uv_bootstrap_pip_fallback_patch_applied": True,
            "verifier_uv_bootstrap_version": "0.7.13",
            "verifier_uv_bootstrap_mirror_host": "releases.astral.sh",
            "original_task_mutated": False,
        },
        "task_setup_preflight": {
            "schema_version": "skillsbench_task_setup_preflight_v0",
            "status": "verifier_bootstrap_risk_detected",
            "verifier_uv_bootstrap_risk_detected": True,
            "raw_task_text_read": False,
            "raw_logs_read": False,
            "raw_trajectory_read": False,
        },
    }


def test_missing_score_uv_bootstrap_risk_gets_verifier_dependency_attribution() -> None:
    compact = _missing_score_compact()
    plan = _uv_bootstrap_plan()
    changed = apply_skillsbench_verifier_bootstrap_missing_score_attribution(
        compact,
        task_staging=plan["task_staging"],
        setup_preflight=plan["task_setup_preflight"],
    )

    assert changed is True, compact
    assert compact["official_score_status"] == "missing", compact
    assert compact["official_score"] is None, compact
    assert compact["score_failure_attribution"] == (
        "verifier_dependency_install_failure"
    ), compact
    assert compact["verifier_dependency_failure_count"] == 1, compact
    assert "verifier_dependency_install_failure" in compact[
        "failure_attribution_labels"
    ], compact
    assert "verifier_uv_install_or_download_failure" in compact[
        "failure_attribution_labels"
    ], compact
    diagnostic = compact["verifier_bootstrap_diagnostic"]
    assert diagnostic["raw_verifier_output_read"] is False, diagnostic
    assert diagnostic["verifier_uv_bootstrap_version"] == "0.7.13", diagnostic
    assert (
        compact["official_task_score"]["kind"]
        == "skillsbench_verifier_bootstrap_reward_missing"
    ), compact

    reduced = compact_benchmark_run(compact)
    assert reduced is not None, compact
    assert reduced["score_failure_attribution"] == (
        "verifier_dependency_install_failure"
    ), reduced
    assert reduced["verifier_dependency_failure_count"] == 1, reduced


def test_completed_score_is_not_reclassified_by_bootstrap_risk() -> None:
    compact = _missing_score_compact()
    plan = _uv_bootstrap_plan()
    compact.update(
        {
            "official_score_status": "completed",
            "official_score": 0.5,
            "official_task_score": {
                "kind": "skillsbench_verifier_reward",
                "value": 0.5,
                "passed": False,
            },
            "score_failure_attribution": "official_verifier_solution_failure",
            "failure_attribution_labels": ["official_verifier_solution_failure"],
        }
    )

    changed = apply_skillsbench_verifier_bootstrap_missing_score_attribution(
        compact,
        task_staging=plan["task_staging"],
        setup_preflight=plan["task_setup_preflight"],
    )

    assert changed is False, compact
    assert compact["score_failure_attribution"] == (
        "official_verifier_solution_failure"
    ), compact
    assert "verifier_bootstrap_diagnostic" not in compact, compact


if __name__ == "__main__":
    test_missing_score_uv_bootstrap_risk_gets_verifier_dependency_attribution()
    test_completed_score_is_not_reclassified_by_bootstrap_risk()
    print("skillsbench-verifier-bootstrap-missing-score-smoke: ok")
