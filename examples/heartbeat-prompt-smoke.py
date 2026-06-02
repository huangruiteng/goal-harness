#!/usr/bin/env python3
"""Smoke-test the reusable heartbeat automation prompt contract."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "heartbeat-automation-prompt.md"
README = REPO_ROOT / "README.md"


def normalized(text: str) -> str:
    return " ".join(text.split())


def assert_ordered(text: str, phrases: tuple[str, ...]) -> None:
    compact = normalized(text)
    positions = []
    for phrase in phrases:
        assert phrase in compact, phrase
        positions.append(compact.index(phrase))
    assert positions == sorted(positions), positions


def main() -> int:
    doc = DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    must_have = (
        "<ACTIVE_GOAL_STATE_PATH>",
        "<GOAL_ID>",
        "goal-harness --format json quota should-run --goal-id <GOAL_ID>",
        "should_run=false",
        "DONT_NOTIFY",
        "do not do implementation work, adapter work, file edits, research, or project exploration",
        "should_run=true",
        "Choose exactly one bounded, verifiable step",
        "Run the smallest useful validation",
        "Write back changed files, validation, critic, and next action",
        "goal-harness refresh-state --goal-id <GOAL_ID>",
        "goal-harness quota spend-slot --goal-id <GOAL_ID> --slots 1 --source heartbeat --execute",
        "append exactly one",
        "Do not append spend for should_run=false skips, preflight failures, pure dry-run previews, or duplicate accounting attempts",
        "Return a compact final report",
    )
    compact_doc = normalized(doc)
    for phrase in must_have:
        assert phrase in compact_doc, phrase

    assert_ordered(
        doc,
        (
            "Before spending delivery compute, run:",
            "If the result says should_run=false",
            "If the result says should_run=true",
            "Run the smallest useful validation",
            "goal-harness refresh-state --goal-id <GOAL_ID>",
            "goal-harness quota spend-slot --goal-id <GOAL_ID> --slots 1 --source heartbeat --execute",
            "Return a compact final report",
        ),
    )

    assert "docs/heartbeat-automation-prompt.md" in readme, readme
    print("heartbeat-prompt-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
