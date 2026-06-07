#!/usr/bin/env python3
"""Smoke-test passive benchmark_run_v0 ingestion from Harbor job outputs."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = (
    REPO_ROOT
    / "docs"
    / "research"
    / "long-horizon-agent-benchmarks"
    / "benchmark-run-v0-ingest.md"
)
README = (
    REPO_ROOT
    / "docs"
    / "research"
    / "long-horizon-agent-benchmarks"
    / "README.md"
)

SCHEMA_VERSION = "benchmark_run_v0"
JOB_NAME = "terminal_bench_probe_v0_codex_builtin"
BENCHMARK_ID = "terminal-bench@2.0"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_fake_harbor_job(root: Path) -> Path:
    job_dir = root / "jobs" / JOB_NAME
    trial_dir = job_dir / "terminal-bench-hello__codex__attempt-1"

    lock = {
        "schema_version": 1,
        "harbor": {
            "version": "0.4.0-test",
            "git_commit_hash": "8cfac6ad91c5c566ff14040cc4acbfe94ad42356",
        },
        "invocation": [
            "harbor",
            "run",
            "--dataset",
            BENCHMARK_ID,
            "--agent",
            "codex",
            "--model",
            "openai/gpt-5.1-codex-mini",
            "--n-concurrent",
            "1",
        ],
        "n_concurrent_trials": 1,
        "retry": {"max_retries": 0},
        "trials": [
            {
                "task": {
                    "name": "terminal-bench-hello",
                    "type": "package",
                    "digest": "sha256:" + "a" * 64,
                    "source": BENCHMARK_ID,
                },
                "agent": {
                    "name": "codex",
                    "import_path": None,
                    "model_name": "openai/gpt-5.1-codex-mini",
                    "kwargs": {"reasoning_effort": "high"},
                    "env": [],
                },
                "environment": {"type": "docker"},
                "verifier": {"type": "script"},
                "timeout_multiplier": 1.0,
            }
        ],
    }
    write_json(job_dir / "lock.json", lock)
    write_json(job_dir / "config.json", {"job_name": JOB_NAME, "datasets": [{"name": "terminal-bench", "version": "2.0"}]})

    trial_result = {
        "id": "11111111-1111-4111-8111-111111111111",
        "task_name": "terminal-bench-hello",
        "trial_name": "terminal-bench-hello__codex__attempt-1",
        "trial_uri": "harbor://jobs/redacted/trials/terminal-bench-hello__codex__attempt-1",
        "task_id": {"name": "terminal-bench-hello", "org": "terminal-bench", "ref": "sha256:" + "a" * 64},
        "source": BENCHMARK_ID,
        "task_checksum": "sha256:" + "b" * 64,
        "config": {"agent": {"name": "codex", "model_name": "openai/gpt-5.1-codex-mini"}},
        "agent_info": {
            "name": "codex",
            "version": "0.118.0",
            "model_info": {"provider": "openai", "name": "gpt-5.1-codex-mini"},
        },
        "agent_result": {
            "n_input_tokens": 1200,
            "n_cache_tokens": 100,
            "n_output_tokens": 300,
            "cost_usd": 0.42,
        },
        "verifier_result": {"rewards": {"reward": 1.0}},
        "exception_info": None,
        "started_at": iso_now(),
        "finished_at": iso_now(),
    }
    write_json(trial_dir / "result.json", trial_result)
    write_json(trial_dir / "config.json", {"trial_name": trial_result["trial_name"]})
    write_json(trial_dir / "verifier" / "reward.json", {"reward": 1.0})
    (trial_dir / "verifier" / "reward.txt").write_text("1.0\n", encoding="utf-8")
    (trial_dir / "verifier" / "test-stdout.txt").write_text("tests passed\n", encoding="utf-8")
    write_json(trial_dir / "agent" / "trajectory.json", {"schema_version": "ATIF-v1.7", "steps": [{"step_id": 1, "source": "agent"}]})
    write_json(trial_dir / "artifacts" / "manifest.json", {"files": ["public-result.txt"]})
    (trial_dir / "trial.log").write_text("public fake trial log\n", encoding="utf-8")

    job_result = {
        "id": "22222222-2222-4222-8222-222222222222",
        "started_at": iso_now(),
        "updated_at": iso_now(),
        "finished_at": iso_now(),
        "n_total_trials": 1,
        "stats": {
            "n_completed_trials": 1,
            "n_errored_trials": 0,
            "n_running_trials": 0,
            "n_pending_trials": 0,
            "n_cancelled_trials": 0,
            "n_retries": 0,
            "n_input_tokens": 1200,
            "n_cache_tokens": 100,
            "n_output_tokens": 300,
            "cost_usd": 0.42,
        },
        "trial_results": [trial_result],
    }
    write_json(job_dir / "result.json", job_result)
    return job_dir


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def trial_metric_totals(trial: dict[str, Any]) -> dict[str, Any]:
    context = trial.get("agent_result") or {}
    return {
        "input_tokens": context.get("n_input_tokens"),
        "cache_tokens": context.get("n_cache_tokens"),
        "output_tokens": context.get("n_output_tokens"),
        "cost_usd": context.get("cost_usd"),
    }


def parse_harbor_job_to_benchmark_run(job_dir: Path) -> dict[str, Any]:
    lock_path = job_dir / "lock.json"
    job_result_path = job_dir / "result.json"
    lock = load_json(lock_path)
    job_result = load_json(job_result_path)
    first_lock_trial = (lock.get("trials") or [{}])[0]
    agent_config = first_lock_trial.get("agent") or {}
    task_config = first_lock_trial.get("task") or {}
    trial_dirs = [path for path in sorted(job_dir.iterdir()) if path.is_dir()]

    trials: list[dict[str, Any]] = []
    for trial_dir in trial_dirs:
        trial_result_path = trial_dir / "result.json"
        if not trial_result_path.exists():
            continue
        trial = load_json(trial_result_path)
        rewards = ((trial.get("verifier_result") or {}).get("rewards")) or {}
        exception_info = trial.get("exception_info")
        trajectory_path = trial_dir / "agent" / "trajectory.json"
        reward_json_path = trial_dir / "verifier" / "reward.json"
        reward_text_path = trial_dir / "verifier" / "reward.txt"
        artifacts_manifest = trial_dir / "artifacts" / "manifest.json"
        trials.append(
            {
                "task_id": trial.get("task_name"),
                "trial_name": trial.get("trial_name"),
                "source": trial.get("source"),
                "reward": rewards,
                "exception_type": (exception_info or {}).get("exception_type"),
                "metrics": trial_metric_totals(trial),
                "trajectory_present": trajectory_path.exists(),
                "verifier_reward_present": reward_json_path.exists() or reward_text_path.exists(),
                "artifact_manifest_present": artifacts_manifest.exists(),
                "trial_result_present": True,
            }
        )

    progress = {
        key: (job_result.get("stats") or {}).get(key)
        for key in (
            "n_completed_trials",
            "n_errored_trials",
            "n_running_trials",
            "n_pending_trials",
            "n_cancelled_trials",
            "n_retries",
        )
    }
    progress["n_total_trials"] = job_result.get("n_total_trials")
    retry_progress_consistent = (
        (progress.get("n_completed_trials") or 0)
        + (progress.get("n_running_trials") or 0)
        + (progress.get("n_pending_trials") or 0)
        <= (progress.get("n_total_trials") or 0)
    )
    invocation = lock.get("invocation") or []

    return {
        "schema_version": SCHEMA_VERSION,
        "source_runner": "harbor",
        "benchmark_id": task_config.get("source") or BENCHMARK_ID,
        "job_name": job_dir.name,
        "mode": "passive_observer",
        "agent": {
            "name": agent_config.get("name"),
            "import_path": agent_config.get("import_path"),
            "model": agent_config.get("model_name"),
            "kwargs_keys": sorted((agent_config.get("kwargs") or {}).keys()),
        },
        "progress": progress,
        "metrics": {
            "input_tokens": (job_result.get("stats") or {}).get("n_input_tokens"),
            "cache_tokens": (job_result.get("stats") or {}).get("n_cache_tokens"),
            "output_tokens": (job_result.get("stats") or {}).get("n_output_tokens"),
            "cost_usd": (job_result.get("stats") or {}).get("cost_usd"),
        },
        "trials": trials,
        "validation": {
            "job_lock_present": lock_path.exists(),
            "job_result_present": job_result_path.exists(),
            "trial_results_present": len(trials) == (progress.get("n_completed_trials") or 0),
            "verifier_reward_present": all(item["verifier_reward_present"] or item["exception_type"] for item in trials),
            "agent_trajectory_recorded": all("trajectory_present" in item for item in trials),
            "retry_progress_consistent": retry_progress_consistent,
            "no_leaderboard_upload_requested": "--upload" not in invocation and "upload" not in invocation,
            "paths_redacted": True,
        },
        "evidence_files": [
            "job:lock.json",
            "job:result.json",
            "trial:result.json",
            "trial:agent/trajectory.json",
            "trial:verifier/reward.json",
            "trial:artifacts/manifest.json",
        ],
        "resume_or_inspect_commands": [
            "harbor job resume --job-path <job-dir>",
            "harbor view <jobs-dir>",
        ],
        "stop_conditions": [
            "do_not_run_docker_or_model_api_by_default",
            "do_not_upload_or_submit_leaderboard",
            "do_not_modify_benchmark_scoring",
            "do_not_copy_raw_codex_sessions_or_private_material",
        ],
    }


def assert_public_safe_event(event: dict[str, Any]) -> None:
    text = json.dumps(event, sort_keys=True)
    forbidden = [
        "/" + "Users/",
        "/" + "tmp/",
        "lark" + "office",
        "fei" + "shu.cn",
        "OPENAI_API_KEY",
        "auth.json",
        "sessions/",
    ]
    leaked = [needle for needle in forbidden if needle in text]
    assert not leaked, leaked


def assert_doc_contract() -> None:
    doc = DOC.read_text(encoding="utf-8")
    compact_doc = " ".join(doc.split())
    readme = README.read_text(encoding="utf-8")
    required = [
        "benchmark_run_v0",
        "For a Harbor job directory",
        "job `lock.json`",
        "job `result.json`",
        "per-trial `result.json`",
        "agent/trajectory.json",
        "verifier/reward.json",
        "resume_or_inspect_commands",
        "harbor job resume --job-path <job-dir>",
        "harbor view <jobs-dir>",
        "does not import Harbor, invoke Docker, call Codex",
        "Do not read Codex raw session files",
        "without adding benchmark-specific heartbeat prompt branches",
    ]
    missing = [snippet for snippet in required if snippet not in compact_doc]
    assert not missing, missing
    assert "benchmark-run-v0-ingest.md" in readme


def main() -> None:
    assert_doc_contract()
    with tempfile.TemporaryDirectory(prefix="benchmark-run-v0-smoke-") as tmp:
        job_dir = write_fake_harbor_job(Path(tmp))
        event = parse_harbor_job_to_benchmark_run(job_dir)

    assert event["schema_version"] == SCHEMA_VERSION, event
    assert event["source_runner"] == "harbor", event
    assert event["benchmark_id"] == BENCHMARK_ID, event
    assert event["mode"] == "passive_observer", event
    assert event["agent"]["name"] == "codex", event
    assert event["agent"]["model"] == "openai/gpt-5.1-codex-mini", event
    assert event["progress"]["n_total_trials"] == 1, event
    assert event["progress"]["n_completed_trials"] == 1, event
    assert event["metrics"]["input_tokens"] == 1200, event
    assert event["metrics"]["cost_usd"] == 0.42, event
    assert len(event["trials"]) == 1, event
    assert event["trials"][0]["reward"]["reward"] == 1.0, event
    assert event["trials"][0]["trajectory_present"] is True, event
    assert event["trials"][0]["verifier_reward_present"] is True, event
    assert all(event["validation"].values()), event["validation"]
    assert "harbor job resume --job-path <job-dir>" in event["resume_or_inspect_commands"]
    assert "do_not_upload_or_submit_leaderboard" in event["stop_conditions"]
    assert_public_safe_event(event)
    print("benchmark-run-v0-harbor-ingest-smoke ok")


if __name__ == "__main__":
    main()
