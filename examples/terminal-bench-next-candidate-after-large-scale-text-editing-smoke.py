#!/usr/bin/env python3
"""Smoke-test the public-safe Terminal-Bench post-large-scale selection."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
DOC = TOPIC_DIR / "terminal-bench-next-candidate-after-large-scale-text-editing-20260614.md"
README = TOPIC_DIR / "README.md"

BLOCKED_TASK = "large-scale-text-editing"
SELECTED_TASK = "git-multibranch"
FALLBACKS = (
    "nginx-request-logging",
    "headless-terminal",
)

REQUIRED_SNIPPETS = (
    "Terminal-Bench Next Candidate After Large-Scale-Text-Editing 2026-06-14",
    BLOCKED_TASK,
    "require_existing_codex",
    "official score `0.0`",
    "worker CLI counter trace reaches the minimum",
    "same worker-startup blocker",
    SELECTED_TASK,
    "task_material_readiness_status=ready",
    "task_material_ready=true",
    "no_upload_boundary=true",
    "submit_eligible=false",
    "auth_values_recorded=false",
    "raw_paths_recorded=false",
    "worker_bridge_requested=true",
    "worker_bridge_requested=false",
    "Codex CLI goal mode versus",
    "Run exactly one private no-upload paired pilot",
    "benchmark_verifier_attribution_review_v0",
    "python3 examples/terminal-bench-next-candidate-after-large-scale-text-editing-smoke.py",
)

FORBIDDEN_TEXT = (
    "/" + "Users/",
    "/" + "private/",
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
    assert BLOCKED_TASK in text, BLOCKED_TASK
    for task_id in FALLBACKS:
        assert task_id in text, task_id
    print(f"ok selected={SELECTED_TASK} blocked={BLOCKED_TASK}")


if __name__ == "__main__":
    main()
