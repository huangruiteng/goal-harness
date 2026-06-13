#!/usr/bin/env python3
"""Smoke-test the public-safe Terminal-Bench post-db-wal candidate packet."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
DOC = TOPIC_DIR / "terminal-bench-next-candidate-after-db-wal-recovery-20260614.md"
README = TOPIC_DIR / "README.md"

SELECTED_TASK = "build-cython-ext"
PREVIOUS_TASK = "db-wal-recovery"

REQUIRED_SNIPPETS = (
    "Terminal-Bench Next Candidate After DB-WAL-Recovery 2026-06-14",
    PREVIOUS_TASK,
    "official score `1.0`",
    "official score `0.0`",
    "verifier_platform_probe_failure",
    "select_new_material_ready_case_no_score_failure",
    "Select `build-cython-ext`",
    "Codex goal-mode baseline",
    "Codex goal-harness treatment",
    "task material required",
    "no upload boundary",
    "auth values read",
    "real runner invoked",
    "real Codex invoked",
    "worker bridge",
    "ready_for_private_managed_no_upload_pilot_review",
    "benchmark_verifier_attribution_review_v0",
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
