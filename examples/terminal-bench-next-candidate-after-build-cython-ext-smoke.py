#!/usr/bin/env python3
"""Smoke-test the public-safe Terminal-Bench post-build-cython selection."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
DOC = TOPIC_DIR / "terminal-bench-next-candidate-after-build-cython-ext-20260614.md"
README = TOPIC_DIR / "README.md"

SELECTED_TASK = "pytorch-model-recovery"
PREVIOUS_TASK = "build-cython-ext"

REQUIRED_SNIPPETS = (
    "Terminal-Bench Next Candidate After Build-Cython-Ext 2026-06-14",
    PREVIOUS_TASK,
    "official score `1.0`",
    "select_new_material_ready_case_no_score_failure",
    "kv-store-grpc",
    "post-launch-materialization blocker",
    "old bare-Codex hard-case evidence",
    "official score `0.0`",
    f"Select `{SELECTED_TASK}`",
    "Codex goal-mode baseline",
    "Codex goal-harness treatment",
    "task material",
    "no upload",
    "submit eligible",
    "auth values recorded",
    "raw paths recorded",
    "worker bridge",
    "ready_for_private_managed_no_upload_pilot_review",
    "missing_real_assisted_worker_observation",
    "benchmark_verifier_attribution_review_v0",
    "python3 examples/terminal-bench-next-candidate-after-build-cython-ext-smoke.py",
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
    assert PREVIOUS_TASK in text, PREVIOUS_TASK
    print(f"ok selected={SELECTED_TASK} previous={PREVIOUS_TASK}")


if __name__ == "__main__":
    main()
