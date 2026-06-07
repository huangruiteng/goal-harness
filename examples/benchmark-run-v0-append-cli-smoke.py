#!/usr/bin/env python3
"""Smoke-test appending benchmark_run_v0 through the Goal Harness CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.status import collect_status  # noqa: E402


GOAL_ID = "benchmark-append-cli-fixture"
BENCHMARK_ID = "terminal-bench@2.0"
CONTROL_PLANE_SCORE_COMPONENTS = (
    "restartability",
    "stale_state_avoidance",
    "evidence_discipline",
    "boundary_safety",
    "writeback_quality",
    "gate_compliance",
    "failure_attribution",
    "overhead",
)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def benchmark_run_event() -> dict[str, Any]:
    return {
        "schema_version": "benchmark_run_v0",
        "source_runner": "harbor",
        "benchmark_id": BENCHMARK_ID,
        "job_name": "terminal_bench_probe_v0_codex_builtin",
        "mode": "passive_observer",
        "agent": {
            "name": "codex",
            "model": "openai/gpt-5.1-codex-mini",
            "kwargs_keys": ["reasoning_effort"],
        },
        "progress": {
            "n_total_trials": 1,
            "n_completed_trials": 1,
            "n_errored_trials": 0,
            "n_running_trials": 0,
            "n_pending_trials": 0,
            "n_cancelled_trials": 0,
            "n_retries": 0,
        },
        "metrics": {
            "input_tokens": 1234,
            "cache_tokens": 100,
            "output_tokens": 321,
            "cost_usd": 0.45,
        },
        "trials": [
            {
                "task_id": "terminal-bench-hello",
                "trial_name": "terminal-bench-hello__codex__attempt-1",
                "source": BENCHMARK_ID,
                "reward": {"reward": 1.0},
                "metrics": {
                    "input_tokens": 1234,
                    "cache_tokens": 100,
                    "output_tokens": 321,
                    "cost_usd": 0.45,
                },
                "trajectory_present": True,
                "verifier_reward_present": True,
                "artifact_manifest_present": True,
                "trial_result_present": True,
            }
        ],
        "validation": {
            "job_lock_present": True,
            "job_result_present": True,
            "trial_results_present": True,
            "verifier_reward_present": True,
            "agent_trajectory_recorded": True,
            "retry_progress_consistent": True,
            "no_leaderboard_upload_requested": True,
            "paths_redacted": True,
        },
        "evidence_files": [
            "job:lock.json",
            "job:result.json",
            "trial:result.json",
            "trial:agent/trajectory.json",
            "trial:verifier/reward.json",
        ],
        "resume_or_inspect_commands": [
            "harbor job resume --job-path <job-dir>",
            "harbor view <jobs-dir>",
        ],
        "stop_conditions": [
            "do_not_run_docker_or_model_api_by_default",
            "do_not_upload_or_submit_leaderboard",
        ],
    }


def benchmark_result_event() -> dict[str, Any]:
    components = {
        "restartability": 1.0,
        "stale_state_avoidance": 1.0,
        "evidence_discipline": 1.0,
        "boundary_safety": 1.0,
        "writeback_quality": 1.0,
        "gate_compliance": 1.0,
        "failure_attribution": 1.0,
        "overhead": 0.0,
    }
    return {
        "schema_version": "benchmark_result_v0",
        "task_id": "mini_control_plane_repair_v0",
        "scenario_id": "with_goal_harness",
        "worker_mode": "deterministic",
        "harness_identity": "goal_harness",
        "worker_surface": "deterministic_shim",
        "terminal_state": "success",
        "official_task_score": {"kind": "deterministic_validation", "passed": True, "value": 1.0},
        "control_plane_score": {
            "schema_version": "control_plane_score_core_v0",
            "kind": "core_v0",
            "aggregation": "unweighted_mean",
            "value": 0.875,
            "components": components,
            "component_order": list(CONTROL_PLANE_SCORE_COMPONENTS),
        },
        "step_count": 3,
        "wall_time_ms": 42.0,
        "validation_pass_count": 4,
        "validation_fail_count": 0,
        "changed_file_count": 3,
        "changed_files": ["src/control_plane.py", "state/ACTIVE_GOAL_STATE.md"],
        "forbidden_access_count": 0,
        "stale_state_error_count": 0,
        "open_todo_preserved": True,
        "archive_hygiene_passed": True,
        "queue_contract_passed": True,
        "trace_publicness": "public",
        "failure_attribution_labels": [],
        "goal_tick_phase_coverage": 1.0,
        "writeback_count": 3,
        "spend_count": 3,
        "spend_before_validation_count": 0,
        "state_reconstructable": True,
    }


def write_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    project = root / "project"
    runtime = root / "runtime"
    state_file = f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
    registry_path = project / ".goal-harness" / "registry.json"
    benchmark_run_path = root / "benchmark_run.json"
    benchmark_result_path = root / "benchmark_result.json"

    (project / Path(state_file).parent).mkdir(parents=True, exist_ok=True)
    (project / state_file).write_text(
        "---\n"
        "status: active-read-only\n"
        "updated_at: 2026-06-07T00:00:00+00:00\n"
        "---\n\n"
        "# Benchmark Append CLI Fixture\n\n"
        "## Agent Todo\n\n"
        "- [ ] Append compact benchmark_run_v0 and benchmark_result_v0 events through the CLI.\n\n"
        "## Next Action\n\n"
        "- Inspect the appended benchmark status/result projections.\n",
        encoding="utf-8",
    )
    write_json(
        registry_path,
        {
            "schema_version": 1,
            "updated_at": "2026-06-07T00:00:00+00:00",
            "common_runtime_root": str(runtime),
            "goals": [
                {
                    "id": GOAL_ID,
                    "domain": "benchmark-projection",
                    "status": "active-read-only",
                    "repo": str(project),
                    "state_file": state_file,
                    "adapter": {
                        "kind": "harness_self_improvement",
                        "status": "connected-read-only",
                    },
                    "quota": {"compute": 1.0, "window_hours": 24},
                    "authority_sources": [],
                }
            ],
        },
    )
    write_json(benchmark_run_path, benchmark_run_event())
    write_json(benchmark_result_path, benchmark_result_event())
    return registry_path, runtime, benchmark_run_path, benchmark_result_path


def run_cli(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "goal_harness.cli", *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict), payload
    return payload


def assert_no_private_surface(summary: dict[str, Any]) -> None:
    text = json.dumps(summary, sort_keys=True)
    forbidden = [
        "/" + "Users/",
        "/" + "tmp/",
        "OPENAI_API_KEY",
        "auth.json",
        "sessions/",
        "lark" + "office",
        "fei" + "shu.cn",
    ]
    leaked = [needle for needle in forbidden if needle in text]
    assert not leaked, leaked


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="benchmark-run-v0-append-") as tmp:
        registry_path, runtime, benchmark_run_path, benchmark_result_path = write_fixture(Path(tmp))
        index_path = runtime / "goals" / GOAL_ID / "runs" / "index.jsonl"

        base_args = [
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(runtime),
            "--format",
            "json",
            "history",
            "append-benchmark-run",
            "--goal-id",
            GOAL_ID,
            "--benchmark-run-json",
            str(benchmark_run_path),
            "--delivery-batch-scale",
            "implementation",
            "--delivery-outcome",
            "primary_goal_outcome",
        ]

        dry_run = run_cli(base_args)
        assert dry_run["ok"], dry_run
        assert dry_run["dry_run"] is True, dry_run
        assert dry_run["appended"] is False, dry_run
        assert not index_path.exists(), index_path
        assert_no_private_surface(dry_run["benchmark_run"])

        appended = run_cli([*base_args, "--execute"])
        assert appended["ok"], appended
        assert appended["dry_run"] is False, appended
        assert appended["appended"] is True, appended
        assert index_path.exists(), index_path
        assert_no_private_surface(appended["benchmark_run"])

        result_args = [
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(runtime),
            "--format",
            "json",
            "history",
            "append-benchmark-result",
            "--goal-id",
            GOAL_ID,
            "--benchmark-result-json",
            str(benchmark_result_path),
            "--delivery-batch-scale",
            "implementation",
            "--delivery-outcome",
            "primary_goal_outcome",
        ]

        result_dry_run = run_cli(result_args)
        assert result_dry_run["ok"], result_dry_run
        assert result_dry_run["dry_run"] is True, result_dry_run
        assert result_dry_run["appended"] is False, result_dry_run
        assert_no_private_surface(result_dry_run["benchmark_result"])
        assert "changed_files" not in result_dry_run["benchmark_result"], result_dry_run

        result_appended = run_cli([*result_args, "--execute"])
        assert result_appended["ok"], result_appended
        assert result_appended["dry_run"] is False, result_appended
        assert result_appended["appended"] is True, result_appended
        assert_no_private_surface(result_appended["benchmark_result"])
        assert "changed_files" not in result_appended["benchmark_result"], result_appended

        index_records = [
            json.loads(line)
            for line in index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(index_records) == 2, index_records
        assert index_records[0]["classification"] == "benchmark_run_v0", index_records
        assert index_records[0]["benchmark_run"]["schema_version"] == "benchmark_run_v0", index_records
        assert index_records[1]["classification"] == "benchmark_result_v0", index_records
        assert index_records[1]["benchmark_result"]["schema_version"] == "benchmark_result_v0", index_records
        assert "changed_files" not in index_records[1]["benchmark_result"], index_records

        status = collect_status(
            registry_path=registry_path,
            runtime_root_override=str(runtime),
            scan_roots=[],
            limit=10,
        )
        assert status["ok"], status
        latest_runs = status["run_history"]["goals"][0]["latest_runs"]
        result_run = next(run for run in latest_runs if run.get("classification") == "benchmark_result_v0")
        run_event = next(run for run in latest_runs if run.get("classification") == "benchmark_run_v0")
        result_summary = result_run["benchmark_result_summary"]
        assert result_summary["schema_version"] == "benchmark_result_v0", result_summary
        assert result_summary["official_task_score"]["value"] == 1.0, result_summary
        assert result_summary["control_plane_score"]["schema_version"] == "control_plane_score_core_v0", result_summary
        assert result_summary["control_plane_score"]["value"] == 0.875, result_summary
        assert tuple(result_summary["control_plane_score"]["component_order"]) == CONTROL_PLANE_SCORE_COMPONENTS, result_summary
        assert "changed_files" not in result_summary, result_summary
        assert_no_private_surface(result_summary)

        summary = run_event["benchmark_run_summary"]
        assert summary["benchmark_id"] == BENCHMARK_ID, summary
        assert summary["progress"]["n_completed_trials"] == 1, summary
        assert summary["metrics"]["cost_usd"] == 0.45, summary
        assert summary["validation"]["all_passed"] is True, summary
        assert status["event_ledger_summary"]["totals"]["benchmark_runs_24h"] == 1, status
        assert_no_private_surface(summary)

    print("benchmark-run-v0-append-cli-smoke ok")


if __name__ == "__main__":
    main()
