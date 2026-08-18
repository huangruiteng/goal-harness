#!/usr/bin/env python3
"""Offline contract smoke for loopx-community-discussion.

Run without network: python3 smoke/community_discussion_smoke.py
Optional live check (requires GH_TOKEN for discussions):
python3 smoke/community_discussion_smoke.py --live owner repo
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from loopx_community_discussion.contract import SCAN_SCHEMA_VERSION, dedupe_key, validate_scan
from loopx_community_discussion.normalize import make_fact, merge_facts
from loopx_community_discussion.render import render_markdown


def _fixture() -> dict:
    external = make_fact(
        fact_type="external_discussion",
        source="github",
        source_url="https://github.com/huangruiteng/loopx/issues/1",
        title="Question: how do I set a stop condition?",
        author="external-user",
        published_at="2026-08-17T00:00:00Z",
    )
    maintainer = make_fact(
        fact_type="maintainer_signal",
        source="github",
        source_url="https://github.com/huangruiteng/loopx/issues/2",
        title="RFC: typed handoff packets",
        author="huangruiteng",
        published_at="2026-08-16T00:00:00Z",
    )
    ecosystem = make_fact(
        fact_type="ecosystem_signal",
        source="hacker_news",
        source_url="https://news.ycombinator.com/item?id=1",
        title="Loop Engineering in Claude",
        author="alice",
        published_at="2026-08-15T00:00:00Z",
        text="loop engineering is a useful frame",
    )
    adoption = make_fact(
        fact_type="adoption_declaration",
        source="web",
        source_url="https://example.com/org-blog/we-standardize-on-loopx",
        title="We standardized our agent control plane on LoopX",
        author="example-org",
        published_at="2026-08-14T00:00:00Z",
        text="loopx project adoption announcement",
    )
    duplicate = make_fact(
        fact_type="external_discussion",
        source="github",
        source_url="https://github.com/huangruiteng/loopx/issues/1",
        title="Question: how do I set a stop condition?",
        author="external-user",
        published_at="2026-08-17T00:00:00Z",
    )
    facts = merge_facts([external, maintainer, ecosystem, adoption, duplicate])  # type: ignore[list-item]
    return {
        "schema_version": SCAN_SCHEMA_VERSION,
        "scan_at": "2026-08-17T00:00:00+00:00",
        "window_days": 14,
        "repo": {"owner": "huangruiteng", "name": "loopx"},
        "stats": {
            "raw_facts": 5,
            "deduped_facts": len(facts),
            "source_errors": 0,
            "strong": sum(1 for f in facts if f["relevance"] == "strong"),
        },
        "facts": facts,
        "evidence": {"sources": ["github-rest", "hn-algolia"], "rate_limit_remaining": 4800, "warnings": []},
    }


def _run_offline() -> int:
    fixture = _fixture()
    if len(fixture["facts"]) != 4:
        print(f"FAIL: dedupe should collapse duplicate facts, got {len(fixture['facts'])}", file=sys.stderr)
        return 1
    violations = validate_scan(fixture)
    if violations:
        print(f"FAIL: fixture should be valid: {violations}", file=sys.stderr)
        return 1

    broken = copy.deepcopy(fixture)
    broken["facts"][0]["fact_type"] = "not_a_type"
    if validate_scan(broken) == []:
        print("FAIL: invalid fact_type accepted", file=sys.stderr)
        return 1

    broken = copy.deepcopy(fixture)
    broken["schema_version"] = "community_discussion_scan_v1"
    if validate_scan(broken) == []:
        print("FAIL: mismatched schema_version accepted", file=sys.stderr)
        return 1

    broken = copy.deepcopy(fixture)
    broken["facts"][0]["relevance"] = "unknown"
    if validate_scan(broken) == []:
        print("FAIL: invalid relevance accepted", file=sys.stderr)
        return 1

    broken = copy.deepcopy(fixture)
    broken["facts"][0]["dedupe_key"] = "abc"
    if validate_scan(broken) == []:
        print("FAIL: short dedupe_key accepted", file=sys.stderr)
        return 1

    noise = make_fact(
        fact_type="external_discussion",
        source="hacker_news",
        source_url="https://example.com/loopxo",
        title="Loopxo token launch",
        author="scammer",
        published_at="2026-08-17T00:00:00Z",
    )
    if noise is not None:
        print("FAIL: Loopxo noise should be filtered", file=sys.stderr)
        return 1

    if dedupe_key("https://a.io/x", "Title A") != dedupe_key("  HTTPS://A.IO/x  ", "title   a"):
        print("FAIL: dedupe_key should normalize URL and title case/space", file=sys.stderr)
        return 1

    md = render_markdown(fixture)
    if "## External discussions" not in md or "https://github.com/huangruiteng/loopx/issues/1" not in md:
        print("FAIL: markdown digest missing external discussion section", file=sys.stderr)
        return 1
    if "## Public adoption & recommendations" not in md or "we-standardize-on-loopx" not in md:
        print("FAIL: markdown digest missing adoption_declaration section", file=sys.stderr)
        return 1
    if md.index("## Public adoption & recommendations") > md.index("## External discussions"):
        print("FAIL: adoption declarations must rank above ordinary discussion", file=sys.stderr)
        return 1

    print("ok: offline contract smoke passed")
    return 0


def _run_live(owner: str, repo: str) -> int:
    from loopx_community_discussion.cli import build_scan

    scan = build_scan(owner, repo, 14)
    violations = validate_scan(scan)
    if violations:
        print(f"FAIL: live scan invalid: {violations}", file=sys.stderr)
        return 1
    print(f"ok: live scan for {owner}/{repo} passed contract validation ({len(scan['facts'])} facts)")
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
