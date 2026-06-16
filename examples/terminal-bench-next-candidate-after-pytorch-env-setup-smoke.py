#!/usr/bin/env python3
"""Smoke-test the public-safe Terminal-Bench post-pytorch setup selection."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
DOC = TOPIC_DIR / "terminal-bench-next-candidate-after-pytorch-env-setup-20260614.md"
README = TOPIC_DIR / "README.md"

SELECTED_TASK = "make-doom-for-mips"
FALLBACK_TASK = "regex-log"
BLOCKED_TASK = "pytorch-model-recovery"
STALE_TASK = "db-wal-recovery"

REQUIRED_SNIPPETS = (
    "Terminal-Bench Next Candidate After Pytorch Env Setup 2026-06-14",
    BLOCKED_TASK,
    "environment_setup_failed_before_worker",
    "environment_setup_repeat_allowed=false",
    "repeat_allowed=false",
    STALE_TASK,
    "already has a current Codex goal-mode versus",
    "baseline official score `1.0`",
    "treatment official score `0.0`",
    SELECTED_TASK,
    FALLBACK_TASK,
    "task_material_readiness_status=ready",
    "no_upload_boundary=true",
    "submit_eligible=false",
    "auth_values_recorded=false",
    "raw_paths_recorded=false",
    f"Select `{SELECTED_TASK}`",
    "Codex goal-mode baseline",
    "Codex goal-harness treatment",
    "ready_for_private_managed_no_upload_pilot_review",
    "missing_real_assisted_worker_observation",
    "benchmark_verifier_attribution_review_v0",
    "python3 examples/terminal-bench-next-candidate-after-pytorch-env-setup-smoke.py",
)

FORBIDDEN_TEXT = (
    "/" + "Users/",
    ".local/" + "private-benchmark-jobs",
    ".cache/" + "harbor/tasks",
    "OPENAI" + "_API_KEY=",
    "CODEX" + "_AUTH",
    "auth" + ".json" + "\":",
    "raw" + "_thread",
    "session" + "_history",
    "sk-" + "example",
)


def main() -> None:
    text = DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
    assert not missing, missing
    leaked = [marker for marker in FORBIDDEN_TEXT if marker in text]
    assert not leaked, leaked
    assert DOC.name in readme, DOC.name
    assert SELECTED_TASK in text, SELECTED_TASK
    assert FALLBACK_TASK in text, FALLBACK_TASK
    assert BLOCKED_TASK in text, BLOCKED_TASK
    assert STALE_TASK in text, STALE_TASK
    print(f"ok selected={SELECTED_TASK} fallback={FALLBACK_TASK}")


if __name__ == "__main__":
    main()
