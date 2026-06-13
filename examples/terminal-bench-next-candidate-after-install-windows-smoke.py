#!/usr/bin/env python3
"""Smoke-test the public-safe Terminal-Bench post-install candidate packet."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
DOC = TOPIC_DIR / "terminal-bench-next-candidate-after-install-windows-20260614.md"
README = TOPIC_DIR / "README.md"

SELECTED_TASK = "financial-document-processor"
BLOCKED_TASK = "install-windows-3.11"

REQUIRED_SNIPPETS = (
    "Terminal-Bench Next Candidate After Install-Windows 2026-06-14",
    BLOCKED_TASK,
    "baseline_verifier_attribution_caveat",
    "treatment_eligible=false",
    "repeat_allowed=false",
    "new_candidate_allowed=true",
    "Select `financial-document-processor`",
    "Codex goal-mode baseline",
    "Codex goal-harness treatment",
    "task material",
    "ready",
    "no upload",
    "submit eligible",
    "auth values recorded",
    "raw paths recorded",
    "worker bridge",
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
    assert BLOCKED_TASK in text, BLOCKED_TASK
    print(f"ok selected={SELECTED_TASK} blocked={BLOCKED_TASK}")


if __name__ == "__main__":
    main()
