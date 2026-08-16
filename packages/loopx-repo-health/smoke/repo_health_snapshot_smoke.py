#!/usr/bin/env python3
"""Offline contract smoke for loopx-repo-health.

Run without network: python3 smoke/repo_health_snapshot_smoke.py
Optional live check (requires GH_TOKEN for stargazers/traffic):
python3 smoke/repo_health_snapshot_smoke.py --live owner repo
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loopx_repo_health.contract import SNAPSHOT_SCHEMA_VERSION, validate_snapshot
from loopx_repo_health.render import render_markdown


def _fixture() -> dict:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "captured_at": "2026-08-17T00:00:00+00:00",
        "repo": {
            "owner": "huangruiteng",
            "name": "loopx",
            "license": "Apache-2.0",
            "created_at": "2026-05-31T14:58:56Z",
            "pushed_at": "2026-08-16T17:44:43Z",
        },
        "counts": {
            "stars": 4804,
            "forks": 417,
            "watchers": 14,
            "open_issues": 29,
            "releases": 1,
            "contributors": 39,
            "prs_total": 200,
            "issues_total": 76,
        },
        "traffic_14d": {
            "views": {"count": 88117, "uniques": 27496},
            "clones": {"count": 29250, "uniques": 4602},
        },
        "latency": {
            "pr_merge_p25_min": 12.0,
            "pr_merge_p75_min": 1440.0,
            "first_response_p25_min": 30.0,
            "first_response_p75_min": 720.0,
        },
        "star_timeline_weekly": [{"week": "2026-W33", "stars": 197}],
        "evidence": {
            "sources": ["github-rest"],
            "rate_limit_remaining": 4900,
            "warnings": [],
        },
    }


def _run_offline() -> int:
    fixture = _fixture()
    violations = validate_snapshot(fixture)
    if violations:
        print(f"FAIL: fixture should be valid: {violations}", file=sys.stderr)
        return 1

    broken = copy.deepcopy(fixture)
    broken["counts"]["stars"] = -1
    if validate_snapshot(broken) == []:
        print("FAIL: negative stars accepted", file=sys.stderr)
        return 1

    broken = copy.deepcopy(fixture)
    broken["schema_version"] = "repo_health_snapshot_v1"
    if validate_snapshot(broken) == []:
        print("FAIL: mismatched schema_version accepted", file=sys.stderr)
        return 1

    broken = copy.deepcopy(fixture)
    broken["traffic_14d"]["views"] = {"count": -1, "uniques": 0}
    if validate_snapshot(broken) == []:
        print("FAIL: negative traffic accepted", file=sys.stderr)
        return 1

    md = render_markdown(fixture)
    if "Repo Health: huangruiteng/loopx" not in md or "| stars | 4804 |" not in md:
        print("FAIL: markdown projection missing expected rows", file=sys.stderr)
        return 1

    print("ok: offline contract smoke passed")
    return 0


def _run_live(owner: str, repo: str) -> int:
    from loopx_repo_health.github import GitHubRepoHealthCollector

    snapshot = GitHubRepoHealthCollector(owner, repo).collect().to_dict()
    violations = validate_snapshot(snapshot)
    if violations:
        print(f"FAIL: live snapshot invalid: {violations}", file=sys.stderr)
        return 1
    print(f"ok: live snapshot for {owner}/{repo} passed contract validation")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", nargs=2, metavar=("OWNER", "REPO"))
    args = parser.parse_args()
    if args.live:
        return _run_live(*args.live)
    return _run_offline()


if __name__ == "__main__":
    raise SystemExit(main())
