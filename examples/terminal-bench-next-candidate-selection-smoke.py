#!/usr/bin/env python3
"""Smoke-test the public-safe Terminal-Bench next-candidate packet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
DOC = TOPIC_DIR / "terminal-bench-next-candidate-selection-20260614.md"
README = TOPIC_DIR / "README.md"

SCHEMA = "terminal_bench_next_candidate_selection_20260614_v0"
BENCHMARK_ID = "terminal-bench@2.0"
SELECTED_TASK = "compile-compcert"
FALLBACK_ORDER = (
    "install-windows-3.11",
    "pytorch-model-recovery",
    "financial-document-processor",
    "multi-source-data-merger",
)
PREFLIGHTED_CANDIDATES = (
    SELECTED_TASK,
    "install-windows-3.11",
    "financial-document-processor",
    "multi-source-data-merger",
    "pytorch-model-recovery",
)

REQUIRED_DOC_SNIPPETS = [
    "Terminal-Bench Next Candidate Selection 2026-06-14",
    "llm-inference-batching-scheduler",
    "treatment_eligible=false",
    "repeat_allowed=false",
    "new_candidate_allowed=true",
    "requires_verifier_preflight_repair=true",
    SELECTED_TASK,
    "Codex goal-mode baseline",
    "Goal Harness treatment",
    "task_material_readiness_status=ready",
    "no_upload_boundary=true",
    "submit_eligible=false",
    "auth_values_recorded=false",
    "raw_paths_recorded=false",
    "python3 examples/terminal-bench-next-candidate-selection-smoke.py",
]

FORBIDDEN_TEXT = [
    "/" + "Users/",
    "/" + "private/",
    ".local/" + "private-benchmark-jobs",
    ".cache/" + "harbor/tasks",
    "OPENAI" + "_API_KEY=",
    "CODEX" + "_AUTH",
    "auth" + ".json" + "\":",
    "raw" + "_thread",
    "session" + "_history",
    "lark" + "office",
    "fei" + "shu.cn",
    "sk-" + "example",
]


def selection_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "generated_from_public_safe_compact_surfaces": True,
        "task_text_read": False,
        "raw_logs_read": False,
        "trajectories_read": False,
        "hidden_tests_read": False,
        "solution_files_read": False,
        "real_runner_invoked": False,
        "real_codex_invoked": False,
        "model_api_invoked": False,
        "upload_or_leaderboard": False,
        "cached_official_task_count": 89,
        "attempted_task_or_repeat_directory_count": 22,
        "unused_cached_task_count": 69,
        "blocked_task": {
            "task_id": "llm-inference-batching-scheduler",
            "treatment_eligible": False,
            "repeat_allowed": False,
            "new_candidate_allowed": True,
            "requires_verifier_preflight_repair": True,
        },
        "preflighted_candidates": [
            {
                "task_id": task_id,
                "codex_goal_mode_baseline_ready": True,
                "goal_harness_treatment_ready": True,
                "task_material_readiness_status": "ready",
                "no_upload_boundary": True,
                "submit_eligible": False,
                "auth_values_recorded": False,
                "raw_paths_recorded": False,
            }
            for task_id in PREFLIGHTED_CANDIDATES
        ],
        "selected_task": SELECTED_TASK,
        "fallback_order": list(FALLBACK_ORDER),
        "next_allowed_action": "launch_one_private_no_upload_paired_pilot",
        "paired_baseline": "codex-goal-mode",
        "paired_treatment": "codex-goal-harness",
        "same_task_repeat_requires": "benchmark_verifier_attribution_review_v0",
        "claim_boundary": {
            "not_official_score_evidence_yet": True,
            "not_leaderboard_evidence": True,
            "not_native_codex_uplift_claim": True,
        },
    }


def assert_public_safe_text(text: str) -> None:
    leaked = [marker for marker in FORBIDDEN_TEXT if marker in text]
    assert not leaked, leaked


def assert_doc_contract() -> None:
    text = DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_DOC_SNIPPETS if snippet not in text]
    assert not missing, missing
    assert_public_safe_text(text)
    assert DOC.name in readme, readme


def assert_selection_payload(payload: dict[str, Any]) -> None:
    assert payload["schema_version"] == SCHEMA, payload
    assert payload["benchmark_id"] == BENCHMARK_ID, payload
    assert payload["selected_task"] == SELECTED_TASK, payload
    assert payload["paired_baseline"] == "codex-goal-mode", payload
    assert payload["paired_treatment"] == "codex-goal-harness", payload
    assert payload["blocked_task"]["treatment_eligible"] is False, payload
    assert payload["blocked_task"]["repeat_allowed"] is False, payload
    assert payload["blocked_task"]["new_candidate_allowed"] is True, payload
    assert payload["blocked_task"]["requires_verifier_preflight_repair"] is True, payload
    assert payload["unused_cached_task_count"] > 0, payload
    assert [item["task_id"] for item in payload["preflighted_candidates"]] == list(
        PREFLIGHTED_CANDIDATES
    ), payload
    for item in payload["preflighted_candidates"]:
        assert item["codex_goal_mode_baseline_ready"] is True, item
        assert item["goal_harness_treatment_ready"] is True, item
        assert item["task_material_readiness_status"] == "ready", item
        assert item["no_upload_boundary"] is True, item
        assert item["submit_eligible"] is False, item
        assert item["auth_values_recorded"] is False, item
        assert item["raw_paths_recorded"] is False, item
    assert payload["next_allowed_action"] == "launch_one_private_no_upload_paired_pilot", payload
    assert payload["same_task_repeat_requires"] == "benchmark_verifier_attribution_review_v0", payload
    text = json.dumps(payload, sort_keys=True)
    assert len(text) < 12000, len(text)
    assert_public_safe_text(text)


def main() -> None:
    assert_doc_contract()
    payload = selection_payload()
    assert_selection_payload(payload)
    print(
        "ok "
        f"benchmark={payload['benchmark_id']} "
        f"selected={payload['selected_task']} "
        f"preflighted={len(payload['preflighted_candidates'])} "
        f"next={payload['next_allowed_action']}"
    )


if __name__ == "__main__":
    main()
