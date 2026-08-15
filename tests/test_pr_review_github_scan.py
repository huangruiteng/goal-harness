from __future__ import annotations

from pathlib import Path

import loopx.pr_review as pr_review_module


HEAD_1 = "a" * 40
HEAD_2 = "b" * 40


def _rows() -> list[dict[str, object]]:
    return [
        {
            "number": 1,
            "title": "one",
            "state": "OPEN",
            "headRefOid": HEAD_1,
            "updatedAt": "2026-08-12T00:00:00Z",
        },
        {
            "number": 2,
            "title": "two",
            "state": "OPEN",
            "headRefOid": HEAD_2,
            "updatedAt": "2026-08-12T00:00:00Z",
        },
    ]


def _fake_run_gh_json(args: list[str], *, cwd: Path | None = None):
    if args[0] == "pr" and args[1] == "list":
        return _rows()
    if args[0] == "api" and args[1].endswith("/check-runs"):
        if args[1].endswith(f"{HEAD_2}/check-runs"):
            return [
                {"name": "build", "status": "IN_PROGRESS", "conclusion": ""},
            ]
        return [
            {"name": "pytest", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "lint", "status": "COMPLETED", "conclusion": "FAILURE"},
        ]
    return {}


def test_pr_list_json_excludes_status_check_rollup(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake(args: list[str], *, cwd: Path | None = None):
        calls.append(args)
        return _fake_run_gh_json(args, cwd=cwd)

    monkeypatch.setattr(pr_review_module, "_run_gh_json", fake)
    scan = pr_review_module.scan_github_pull_requests(
        repo="huangruiteng/loopx",
        limit=10,
        state_filter="open",
    )

    list_call = next(
        args for args in calls if args[0] == "pr" and args[1] == "list"
    )
    json_fields = list_call[list_call.index("--json") + 1].split(",")
    assert "statusCheckRollup" not in json_fields

    rows = scan["pull_requests"]
    assert len(rows) == 2
    assert rows[0]["statusCheckRollup"] == [
        {"name": "pytest", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"name": "lint", "status": "COMPLETED", "conclusion": "FAILURE"},
    ]
    assert rows[1]["statusCheckRollup"] == [
        {"name": "build", "status": "IN_PROGRESS", "conclusion": ""},
    ]
    api_calls = [args for args in calls if args[0] == "api"]
    assert any(
        args[1] == f"repos/huangruiteng/loopx/commits/{HEAD_1}/check-runs"
        for args in api_calls
    )
    assert any(
        args[1] == f"repos/huangruiteng/loopx/commits/{HEAD_2}/check-runs"
        for args in api_calls
    )


def test_pr_list_failed_check_lookup_leaves_rollup_absent(monkeypatch) -> None:
    def fake(args: list[str], *, cwd: Path | None = None):
        if args[0] == "pr" and args[1] == "list":
            return _rows()
        raise RuntimeError("api unavailable")

    monkeypatch.setattr(pr_review_module, "_run_gh_json", fake)
    scan = pr_review_module.scan_github_pull_requests(
        repo="huangruiteng/loopx",
        limit=10,
        state_filter="open",
    )
    rows = scan["pull_requests"]
    assert all("statusCheckRollup" not in row for row in rows)


def test_security_policy_keeps_public_entry_classification_after_move() -> None:
    assert pr_review_module._file_area(".github/SECURITY.md") == (
        "public_entry_or_policy"
    )
