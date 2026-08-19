from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from typing import Any

from .contract import SCAN_SCHEMA_VERSION, validate_scan
from .normalize import merge_facts
from .render import render_markdown
from .sources.github import collect_github
from .sources.hn import collect_hn


EXTENSION_ID = "loopx-community-discussion"
REQUEST_SCHEMA_VERSION = "loopx_community_discussion_request_v0"
RESPONSE_SCHEMA_VERSION = "loopx_community_discussion_response_v0"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=EXTENSION_ID)
    parser.add_argument("--doctor", action="store_true", help="run the managed-runtime health check")
    sub = parser.add_subparsers(dest="command")
    scan = sub.add_parser("scan", help="collect a community discussion scan")
    scan.add_argument("--owner", required=True)
    scan.add_argument("--repo", required=True)
    scan.add_argument("--days", type=int, default=14)
    scan.add_argument("--format", choices=("json", "md"), default="json")
    return parser


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


def _doctor() -> int:
    _emit(
        {
            "ok": True,
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "extension_id": EXTENSION_ID,
            "doctor": "ok",
        }
    )
    return 0


def build_scan(owner: str, repo: str, days: int) -> dict[str, Any]:
    if not owner.strip() or not repo.strip():
        raise ValueError("owner and repo must be non-empty strings")
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")
    github_facts, github_evidence = collect_github(owner.strip(), repo.strip(), days)
    hn_facts, hn_evidence = collect_hn(days)
    raw_facts = github_facts + hn_facts
    facts = merge_facts(raw_facts)
    evidence = {
        "sources": sorted(set(github_evidence["sources"] + hn_evidence["sources"])),
        "rate_limit_remaining": github_evidence["rate_limit_remaining"],
        "warnings": github_evidence["warnings"] + hn_evidence["warnings"],
    }
    return {
        "schema_version": SCAN_SCHEMA_VERSION,
        "scan_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "window_days": days,
        "repo": {"owner": owner.strip(), "name": repo.strip()},
        "stats": {
            "raw_facts": len(raw_facts),
            "deduped_facts": len(facts),
            "source_errors": sum(1 for f in facts if f["fact_type"] == "source_error"),
            "strong": sum(1 for f in facts if f["relevance"] == "strong"),
        },
        "facts": facts,
        "evidence": evidence,
    }


def _scan_command(args: argparse.Namespace) -> int:
    try:
        scan = build_scan(args.owner, args.repo, args.days)
    except (ValueError, OSError) as exc:
        _emit({"ok": False, "error": str(exc)})
        return 1
    violations = validate_scan(scan)
    if violations:
        _emit({"ok": False, "error": f"scan contract violated: {violations}"})
        return 1
    if args.format == "md":
        sys.stdout.write(render_markdown(scan))
    else:
        _emit(scan)
    return 0


def _run_request(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        raise ValueError("extension input must be a JSON object")
    if payload.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError(f"extension input must use {REQUEST_SCHEMA_VERSION}")
    scan = build_scan(str(payload.get("owner") or ""), str(payload.get("repo") or ""), int(payload.get("days") or 14))
    violations = validate_scan(scan)
    if violations:
        raise ValueError(f"scan contract violated: {violations}")
    _emit(
        {
            "ok": True,
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "extension_id": EXTENSION_ID,
            "request_schema_version": REQUEST_SCHEMA_VERSION,
            "result": scan,
        }
    )
    return 0


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.doctor:
        return _doctor()
    try:
        if args.command == "scan":
            return _scan_command(args)
        payload = json.load(sys.stdin)
        return _run_request(payload)
    except (json.JSONDecodeError, OSError, ValueError, KeyError) as exc:
        _emit(
            {
                "ok": False,
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "extension_id": EXTENSION_ID,
                "error": str(exc),
            }
        )
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
