#!/usr/bin/env python3
"""Smoke-test the content-ops queue-status projection CLI."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.content_ops.item_lifecycle import (  # noqa: E402
    apply_content_ops_item_event,
    build_content_ops_item,
)


PRIVATE_PATTERNS = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"/private/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]+"),
]


def _review_ready() -> dict[str, Any]:
    item = build_content_ops_item(
        item_id="community-recap-v1",
        item_kind="post",
        channel="x",
        content_digest="sha256:" + "b" * 64,
        content_ref="draft:community-recap-v1",
        source_refs=["source:github-loopx-public-recap"],
        created_at="2026-08-10T02:00:00+08:00",
    )
    return apply_content_ops_item_event(
        item,
        {
            "event_id": "review:community-recap-v1",
            "action": "submit_review",
            "expected_state": item["state"],
            "expected_revision": item["revision"],
            "occurred_at": "2026-08-10T02:05:00+08:00",
            "payload": {},
        },
    )["item"]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        item_path = Path(tmp) / "item.json"
        item_path.write_text(
            json.dumps(_review_ready(), ensure_ascii=True),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "loopx.cli",
                "--format",
                "json",
                "content-ops",
                "queue-status",
                "--item-json",
                str(item_path),
                "--queue-id",
                "loopx-x-operations",
                "--generated-at",
                "2026-08-10T02:10:00+08:00",
            ],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    assert payload["projection"]["queue_id"] == "loopx-x-operations", payload
    assert payload["projection"]["counts"] == {"review_ready": 1}, payload
    assert payload["projection"]["next_action"]["item_id"] == "community-recap-v1"
    assert payload["external_reads_performed"] is False, payload
    assert payload["external_writes_performed"] is False, payload
    assert payload["autopublish_allowed"] is False, payload

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            raise AssertionError(f"payload matched private pattern {pattern.pattern!r}")

    print("content-ops-queue-status-smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
