#!/usr/bin/env python3
"""Smoke-test the public-safe Terminal-Bench post-regex-log selection."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
DOC = TOPIC_DIR / "terminal-bench-next-candidate-after-regex-log-20260614.md"
README = TOPIC_DIR / "README.md"

SELECTED_TASK = "large-scale-text-editing"
FALLBACKS = (
    "git-multibranch",
    "nginx-request-logging",
    "headless-terminal",
    "mteb-retrieve",
)
SCREENED = (
    "headless-terminal",
    "git-multibranch",
    SELECTED_TASK,
    "nginx-request-logging",
    "mteb-retrieve",
    "hf-model-inference",
    "path-tracing",
    "password-recovery",
)

REQUIRED_SNIPPETS = (
    "Terminal-Bench Next Candidate After Regex-Log 2026-06-14",
    "loop_validation_no_score_uplift",
    "repeat_allowed=false",
    "new_candidate_allowed=true",
    "candidate source-boundary guard",
    "clean=true",
    "blocked_source_count=0",
    "name-only cached official task-id scan",
    "88 material-ready",
    "Sixty",
    SELECTED_TASK,
    "task_material_readiness_status=ready",
    "task_material_ready=true",
    "no_upload_boundary=true",
    "submit_eligible=false",
    "auth_values_recorded=false",
    "raw_paths_recorded=false",
    "validation_passed=true",
    "Codex CLI goal mode versus",
    "Run exactly one private no-upload paired pilot",
    "benchmark_verifier_attribution_review_v0",
    "python3 examples/terminal-bench-next-candidate-after-regex-log-smoke.py",
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
    for task_id in SCREENED:
        assert task_id in text, task_id
    for task_id in FALLBACKS:
        assert task_id in text, task_id
    print(f"ok selected={SELECTED_TASK} screened={len(SCREENED)}")


if __name__ == "__main__":
    main()
