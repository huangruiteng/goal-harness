#!/usr/bin/env python3
"""Smoke-test the public SWE-Marathon vliw launch packet."""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
PACKET_PATH = DOC_DIR / "swe-marathon-vliw-kernel-optimization-launch-packet-v0.md"
CATALOG_PATH = DOC_DIR / "swe-marathon-full-suite-status-20260622.json"
README_PATH = DOC_DIR / "README.md"

FORBIDDEN_PATTERNS = [
    re.compile("/" + "Users/"),
    re.compile("/" + "private/"),
    re.compile(r"\." + "local/"),
    re.compile("trajectory_copied" + r"\"\\s*:\\s*" + "tr" + "ue"),
    re.compile("raw_logs_copied" + r"\"\\s*:\\s*" + "tr" + "ue"),
    re.compile("raw_task_text_copied" + r"\"\\s*:\\s*" + "tr" + "ue"),
    re.compile("verifier_output_copied" + r"\"\\s*:\\s*" + "tr" + "ue"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}"),
]


def assert_public_safe(text: str) -> None:
    for pattern in FORBIDDEN_PATTERNS:
        assert not pattern.search(text), pattern.pattern


def load_case() -> dict:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return next(
        case
        for case in catalog["cases"]
        if case["case_id"] == "vliw-kernel-optimization"
    )


def test_packet_matches_catalog() -> None:
    case = load_case()
    packet = PACKET_PATH.read_text(encoding="utf-8")
    assert case["experiment_tier"] == "p0_next_fresh_cpu_no_cua_candidate"
    assert case["public_ledger_status"] == "not_started"
    assert case["gpus"] == 0
    assert str(case["agent_timeout_sec"]) in packet
    assert str(case["verifier_timeout_sec"]) in packet
    assert str(case["build_timeout_sec"]) in packet
    assert "`vliw-kernel-optimization`" in packet
    assert "completion source of truth is no active case-local LoopX todo" in packet


def test_no_execution_boundary() -> None:
    packet = PACKET_PATH.read_text(encoding="utf-8")
    assert "Do not execute this command from an automatic heartbeat" in packet
    assert "omit `--upload`" in packet
    assert "automatic heartbeat is the only launch authority" in packet
    assert "loopx_*" in packet
    assert "goal_harness" not in packet
    assert_public_safe(packet)


def test_readme_indexes_packet() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    assert "swe-marathon-vliw-kernel-optimization-launch-packet-v0.md" in readme


if __name__ == "__main__":
    test_packet_matches_catalog()
    test_no_execution_boundary()
    test_readme_indexes_packet()
    print("swe-marathon-vliw-launch-packet-smoke ok")
