#!/usr/bin/env python3
"""Smoke-test public PR-program snapshot reconciliation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "loopx-pr-program" / "scripts" / "diff_snapshot.py"
FIXTURES = REPO_ROOT / "examples" / "fixtures"
BASELINE = FIXTURES / "pr-program-snapshot-baseline.public.json"
CURRENT = FIXTURES / "pr-program-snapshot-current.public.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def diff(previous: Path, current: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--previous", str(previous), "--current", str(current)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(result.stdout)


def assert_public_safe(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "/Users/",
        "/private/",
        "Bearer ",
        "api_key",
        "review_body",
        "provider_payload",
    ):
        assert forbidden not in text, forbidden


def main() -> int:
    baseline = load(BASELINE)
    current = load(CURRENT)
    assert baseline["program_id"] == current["program_id"]
    assert_public_safe(baseline)
    assert_public_safe(current)

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        baseline_path = root / "baseline.json"
        current_path = root / "current.json"
        write(baseline_path, baseline)
        write(current_path, current)

        delta = diff(baseline_path, current_path)
        assert delta["program_id"] == "example-runtime-reliability", delta
        assert delta["baseline_advance_allowed"] is True, delta
        assert delta["scope_matches_previous"] is True, delta
        assert delta["changed"] == [
            {
                "ref": "example/runtime#42",
                "changed_fields": [
                    "draft",
                    "head_sha",
                    "checks",
                    "review",
                    "work_item",
                ],
                "before": {
                    "draft": True,
                    "head_sha": "a" * 40,
                    "checks": "pending",
                    "review": "pending",
                    "work_item": "action_required",
                },
                "after": {
                    "draft": False,
                    "head_sha": "b" * 40,
                    "checks": "passed",
                    "review": "approved",
                    "work_item": "passed",
                },
            }
        ], delta
        assert_public_safe(delta)

        incomplete = json.loads(json.dumps(current))
        incomplete["result_completeness"]["complete"] = False
        incomplete["change_requests"][0]["checks"] = "unknown"
        incomplete["change_requests"][0]["review"] = "unknown"
        incomplete["change_requests"][0]["work_item"] = "unknown"
        incomplete_path = root / "incomplete.json"
        write(incomplete_path, incomplete)
        incomplete_delta = diff(baseline_path, incomplete_path)
        assert incomplete_delta["baseline_advance_allowed"] is False, incomplete_delta
        assert incomplete_delta["baseline_block_reason"] == "incomplete_result", incomplete_delta
        assert incomplete_delta["result_hash"] is None, incomplete_delta

        mismatched = json.loads(json.dumps(current))
        mismatched["result_completeness"]["scope"]["repositories"] = ["example/other"]
        mismatched_path = root / "scope-mismatch.json"
        write(mismatched_path, mismatched)
        mismatch_delta = diff(baseline_path, mismatched_path)
        assert mismatch_delta["baseline_advance_allowed"] is False, mismatch_delta
        assert mismatch_delta["baseline_block_reason"] == "scope_mismatch", mismatch_delta
        assert mismatch_delta["result_hash"] is None, mismatch_delta

    print("pr-program-snapshot-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
