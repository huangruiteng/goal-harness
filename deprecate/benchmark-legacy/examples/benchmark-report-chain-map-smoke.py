#!/usr/bin/env python3
"""Smoke-test the benchmark report chain map contract."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
README = TOPIC_DIR / "README.md"
ROADMAP = TOPIC_DIR / "roadmap.md"
CHAIN_MAP = TOPIC_DIR / "benchmark-report-chain-map-v0.md"
STATUS_CONTRACT = REPO_ROOT / "docs" / "status-data-contract.md"

SCHEMA_CHAIN = [
    "benchmark_run_v0",
    "benchmark_result_v0",
    "benchmark_comparison_v0",
    "benchmark_comparison_decision_note_v0",
    "benchmark_experiment_report_v0",
    "benchmark_experiment_report_readiness_note_v0",
    "benchmark_experiment_report_replay_decision_v0",
]

HANDOFF_FIELDS = [
    "official_score",
    "control_plane_score",
    "readiness",
    "authorization",
    "replay_decision",
    "next_run_mode",
    "negative_evidence_layers",
    "must_not_claim",
    "stop_condition",
]

BOUNDARY_SNIPPETS = [
    "fixture, status, and review-packet contracts",
    "run a real benchmark",
    "model APIs",
    "simulator",
    "hidden tests",
    "expected solutions",
    "private traces",
    "raw runner logs",
    "local artifact paths",
    "raw session records",
    "leaderboard evidence",
    "benchmark's native scoring protocol",
    "external execution",
]

FORBIDDEN_TEXT = [
    "/" + "Users/",
    "/" + "tmp/",
    "OPENAI" + "_" + "API" + "_" + "KEY",
    "ANTHROPIC" + "_" + "API" + "_" + "KEY",
    "DAYTONA" + "_" + "API" + "_" + "KEY",
    "lark" + "office",
    "fei" + "shu.cn",
    "raw" + "_thread",
    "session" + "_history",
    "sk-" + "example",
]


def assert_ordered_chain(text: str) -> None:
    positions = []
    for schema in SCHEMA_CHAIN:
        position = text.find(schema)
        assert position >= 0, schema
        positions.append(position)
    assert positions == sorted(positions), positions


def assert_no_forbidden_text(text: str) -> None:
    leaked = [marker for marker in FORBIDDEN_TEXT if marker in text]
    assert not leaked, leaked


def main() -> None:
    text = CHAIN_MAP.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    roadmap = ROADMAP.read_text(encoding="utf-8")
    status_contract = STATUS_CONTRACT.read_text(encoding="utf-8")

    assert_ordered_chain(text)
    missing_fields = [field for field in HANDOFF_FIELDS if field not in text]
    assert not missing_fields, missing_fields
    missing_boundaries = [snippet for snippet in BOUNDARY_SNIPPETS if snippet not in text]
    assert not missing_boundaries, missing_boundaries

    assert "benchmark-report-chain-map-v0.md" in readme
    assert "benchmark-report-chain-map-v0.md" in roadmap
    assert "benchmark-report-chain-map-v0.md" in status_contract
    assert "explanatory only" in status_contract
    assert "does not add a status" in status_contract
    assert "field, append a run-history event" in status_contract

    for artifact_text in [text, readme, roadmap]:
        assert_no_forbidden_text(artifact_text)

    print("benchmark-report-chain-map-smoke ok")


if __name__ == "__main__":
    main()
