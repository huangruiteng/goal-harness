#!/usr/bin/env python3
"""Validate the public long-horizon agent state protocol contract."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "docs"
    / "reference"
    / "protocols"
    / "long-horizon-agent-state-protocol-v0.md"
)
INDEX_PATH = REPO_ROOT / "docs" / "reference" / "protocols" / "README.md"

FORBIDDEN_PRIVATE_PATTERNS = [
    re.compile(r"/" + r"Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"/" + "private/"),
    re.compile(r"\b" + "depart" + "ment" + r"\b", re.IGNORECASE),
    re.compile("\u90e8\u95e8"),
    re.compile("\u6c47\u62a5"),
]


def assert_contains(source: str, snippet: str, label: str) -> None:
    if snippet not in source:
        raise AssertionError(f"missing {label}: {snippet}")


def assert_public_safe(source: str) -> None:
    for pattern in FORBIDDEN_PRIVATE_PATTERNS:
        if pattern.search(source):
            raise AssertionError(f"protocol matched private pattern {pattern.pattern!r}")


def main() -> int:
    protocol = PROTOCOL_PATH.read_text(encoding="utf-8")
    index = INDEX_PATH.read_text(encoding="utf-8")
    assert_public_safe(protocol)
    assert_public_safe(index)

    assert_contains(index, "long_horizon_agent_state_protocol_v0", "protocol index")
    assert_contains(protocol, "## Source Protocol", "source protocol section")
    assert_contains(protocol, "## Projection Protocol", "projection protocol section")
    assert_contains(protocol, '"projection_is_writable": false', "read-only projection flag")
    assert_contains(protocol, "interaction_contract_v0", "interaction contract anchor")
    assert_contains(protocol, "agent_lane_next_action_v0", "agent lane next action anchor")
    assert_contains(protocol, "loopx_rollout_event_v0", "rollout event anchor")
    assert_contains(protocol, "rollback_packet_v0", "rollback future contract")
    assert_contains(protocol, "candidate todos are not silently promoted", "candidate todo acceptance")
    print("long-horizon-agent-state-protocol smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
