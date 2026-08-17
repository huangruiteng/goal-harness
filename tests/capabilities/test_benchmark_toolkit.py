from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit import (
    BENCHMARK_INTEGRITY_POLICY_SCHEMA_VERSION,
    BENCHMARK_RUNTIME_INTEGRITY_ATTESTATION_SCHEMA_VERSION,
    REQUIRED_RUNTIME_ATTESTATIONS,
    build_benchmark_integrity_qualification,
)
from loopx.capabilities.catalog import build_capability_detail_packet

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_catalog_exposes_post_run_case_insight_monitor_contract() -> None:
    capability = build_capability_detail_packet("benchmark-toolkit")["capability"]
    analysis = capability["post_run_case_analysis"]

    assert "continuous_monitor" in analysis["benchmark_start_hint"]
    assert analysis["monitor_todo_template"] == {
        "task_class": "continuous_monitor",
        "action_kind": "benchmark_case_insight_monitor",
        "trigger": "material_scored_case_transition",
        "text": (
            "On each material scored-case transition, read the complete private "
            "evaluation evidence, write one benchmark_case_insight_v0, and report "
            "only new reusable insight."
        ),
    }
    hint = analysis["hint"]
    for evidence_name in (
        "real trajectory",
        "hidden tests",
        "grader or verifier",
        "failure and score details",
    ):
        assert evidence_name in hint

    assert "must not access" in analysis["role_boundary"]["solver"]
    assert "only after" in analysis["role_boundary"]["post_run_analyst"]
    artifact = analysis["artifact_template"]
    assert artifact["schema_version"] == "benchmark_case_insight_v0"
    assert artifact["evidence_reviewed"] == [
        "task",
        "real_trajectory",
        "final_patch_or_workspace",
        "hidden_tests",
        "grader_or_verifier",
        "failure_and_score_details",
    ]
    assert set(artifact["insight"]) == {
        "approach_summary",
        "decisive_evidence",
        "why_this_outcome",
        "expectedness",
        "baseline_treatment_difference",
        "loopx_implication",
        "next_probe",
    }
    assert "reuse_boundary" in artifact


def _attestation() -> dict[str, object]:
    return {
        "schema_version": BENCHMARK_RUNTIME_INTEGRITY_ATTESTATION_SCHEMA_VERSION,
        "authority": "runner",
        "benchmark_id": "fixture@v0",
        "case_id": "case-1",
        **{field: True for field in REQUIRED_RUNTIME_ATTESTATIONS},
    }


def _trajectory(
    *, command: str = "git status", observation: str = "clean"
) -> dict[str, object]:
    return {
        "schema_version": "ATIF-v1.7",
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "message": "",
                "tool_calls": [
                    {
                        "function_name": "exec_command",
                        "arguments": {"cmd": command},
                    }
                ],
                "observation": observation,
            }
        ],
    }


def test_clean_private_trajectory_and_runner_attestation_qualify() -> None:
    receipt = build_benchmark_integrity_qualification(
        trajectory=_trajectory(),
        runtime_attestation=_attestation(),
    )

    assert receipt["integrity_qualified"] is True
    assert receipt["integrity_countable"] is True
    assert receipt["score_claim_eligible"] is True
    assert receipt["score_claim_countable"] is False
    assert receipt["matched_pair_countable"] is False
    assert receipt["benchmark_cheating_detected"] is False
    assert receipt["blockers"] == []
    assert receipt["public_boundary"] == {
        "private_trajectory_read": True,
        "raw_content_recorded": False,
        "raw_arguments_recorded": False,
        "raw_observations_recorded": False,
        "sensitive_values_recorded": False,
        "input_paths_recorded": False,
    }


def test_restricted_source_cross_trial_and_credential_exposure_fail_closed() -> None:
    secret = "fixture-sensitive-value-123456"
    restricted_path = "/private/evaluator/solution/solution.patch"
    other_trial = "/private/runs/another-trial"
    trajectory = _trajectory(
        command=f"env && git apply {restricted_path} && cat {other_trial}",
        observation=f"shell output contained {secret}",
    )
    policy = {
        "schema_version": BENCHMARK_INTEGRITY_POLICY_SCHEMA_VERSION,
        "policy_id": "fixture-policy",
        "denied_argument_markers": {"other_trial_request": [other_trial]},
    }
    receipt = build_benchmark_integrity_qualification(
        trajectory=trajectory,
        runtime_attestation=_attestation(),
        policy=policy,
        sensitive_values=[secret],
    )

    assert receipt["integrity_qualified"] is False
    assert receipt["score_claim_eligible"] is False
    assert receipt["score_claim_countable"] is False
    assert receipt["benchmark_cheating_detected"] is True
    assert receipt["classification"] == "restricted_evaluation_access_detected"
    assert receipt["evidence_counts"]["restricted_answer_source_request"] == 1
    assert receipt["evidence_counts"]["other_trial_request"] == 1
    assert receipt["evidence_counts"]["credential_probe"] == 1
    assert receipt["evidence_counts"]["credential_value_observed"] == 1
    rendered = json.dumps(receipt, sort_keys=True)
    for private_value in (secret, restricted_path, other_trial):
        assert private_value not in rendered


def test_missing_runner_isolation_is_uncountable_without_inventing_cheating() -> None:
    attestation = copy.deepcopy(_attestation())
    attestation["evaluator_sources_denied"] = False
    receipt = build_benchmark_integrity_qualification(
        trajectory=_trajectory(),
        runtime_attestation=attestation,
    )

    assert receipt["integrity_qualified"] is False
    assert receipt["benchmark_cheating_detected"] is False
    assert receipt["classification"] == "runtime_isolation_not_attested"
    assert "runtime_attestation_evaluator_sources_denied_missing" in receipt["blockers"]


def test_shell_network_flags_do_not_bypass_integrity_scan() -> None:
    receipt = build_benchmark_integrity_qualification(
        trajectory=_trajectory(command="curl -fsS https://example.invalid/probe"),
        runtime_attestation=_attestation(),
    )

    assert receipt["integrity_qualified"] is False
    assert receipt["benchmark_cheating_detected"] is False
    assert receipt["classification"] == "integrity_policy_violation"
    assert receipt["evidence_counts"]["external_network_request"] == 1


@pytest.mark.parametrize("field", ["benchmark_id", "case_id"])
def test_path_like_attestation_labels_fail_closed_without_leaking(
    field: str,
) -> None:
    private_path = "/Users/private-user/.local/benchmark/case-1"
    attestation = _attestation()
    attestation[field] = private_path

    receipt = build_benchmark_integrity_qualification(
        trajectory=_trajectory(),
        runtime_attestation=attestation,
    )

    assert receipt["integrity_qualified"] is False
    assert receipt[field] == "redacted"
    assert f"runtime_attestation_{field}_path_like" in receipt["blockers"]
    assert private_path not in json.dumps(receipt, sort_keys=True)


def test_path_like_policy_id_fails_closed_without_leaking() -> None:
    private_path = "C:\\Users\\private-user\\policy.json"
    receipt = build_benchmark_integrity_qualification(
        trajectory=_trajectory(),
        runtime_attestation=_attestation(),
        policy={
            "schema_version": BENCHMARK_INTEGRITY_POLICY_SCHEMA_VERSION,
            "policy_id": private_path,
        },
    )

    assert receipt["integrity_qualified"] is False
    assert receipt["policy_id"] == "redacted"
    assert "integrity_policy_id_path_like" in receipt["blockers"]
    assert private_path not in json.dumps(receipt, sort_keys=True)


def test_bare_sensitive_filename_does_not_match_unrelated_path_basename() -> None:
    receipt = build_benchmark_integrity_qualification(
        trajectory=_trajectory(command="git apply /home/me/reference.patch"),
        runtime_attestation=_attestation(),
    )

    assert receipt["integrity_qualified"] is True
    assert receipt["evidence_counts"]["restricted_answer_source_request"] == 0


@pytest.mark.parametrize(
    "command",
    [
        "python3 -c 'import os; print(os.environ.get(\"API_KEY\"))'",
        "python3 -c 'import os; print(os.getenv(\"API_KEY\"))'",
        "python3 -c 'import subprocess; subprocess.run([\"tool\"], env={})'",
    ],
)
def test_environment_access_forms_are_credential_probes(command: str) -> None:
    receipt = build_benchmark_integrity_qualification(
        trajectory=_trajectory(command=command),
        runtime_attestation=_attestation(),
    )

    assert receipt["integrity_qualified"] is False
    assert receipt["evidence_counts"]["credential_probe"] == 1


def test_non_access_control_tool_text_is_not_an_access_request() -> None:
    trajectory = _trajectory()
    trajectory["steps"][0]["tool_calls"][0] = {
        "function_name": "update_plan",
        "arguments": {
            "plan": [
                {
                    "step": "Inspect env configuration without exposing credentials",
                    "status": "in_progress",
                },
                {
                    "step": "Do not fetch a hidden reference.patch with curl",
                    "status": "pending",
                },
            ]
        },
    }

    receipt = build_benchmark_integrity_qualification(
        trajectory=trajectory,
        runtime_attestation=_attestation(),
    )

    assert receipt["integrity_qualified"] is True
    assert receipt["evidence_counts"]["credential_probe"] == 0
    assert receipt["evidence_counts"]["external_network_request"] == 0
    assert receipt["evidence_counts"]["restricted_answer_source_request"] == 0


def test_non_access_control_tool_still_detects_a_sensitive_value() -> None:
    secret = "fixture-sensitive-value-123456"
    trajectory = _trajectory()
    trajectory["steps"][0]["tool_calls"][0] = {
        "function_name": "update_plan",
        "arguments": {"explanation": f"Observed {secret}"},
    }

    receipt = build_benchmark_integrity_qualification(
        trajectory=trajectory,
        runtime_attestation=_attestation(),
        sensitive_values=[secret],
    )

    assert receipt["integrity_qualified"] is False
    assert receipt["evidence_counts"]["credential_probe"] == 0
    assert receipt["evidence_counts"]["credential_value_observed"] == 1


def test_invalid_private_inputs_fail_before_receipt_building() -> None:
    with pytest.raises(ValueError, match="policy_schema_mismatch"):
        build_benchmark_integrity_qualification(
            trajectory=_trajectory(),
            runtime_attestation=_attestation(),
            policy={"schema_version": "wrong"},
        )
    with pytest.raises(ValueError, match="sensitive_value_too_short"):
        build_benchmark_integrity_qualification(
            trajectory=_trajectory(),
            runtime_attestation=_attestation(),
            sensitive_values=["short"],
        )


def test_cli_emits_only_compact_public_safe_receipt(tmp_path: Path) -> None:
    trajectory_path = tmp_path / "private-trajectory.json"
    attestation_path = tmp_path / "private-attestation.json"
    trajectory_path.write_text(json.dumps(_trajectory()), encoding="utf-8")
    attestation_path.write_text(json.dumps(_attestation()), encoding="utf-8")
    secret = "fixture-cli-sensitive-value-123456"
    env = {**os.environ, "BENCHMARK_TOOLKIT_TEST_SECRET": secret}

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts/loopx"),
            "benchmark",
            "integrity-qualification",
            "--trajectory-json",
            str(trajectory_path),
            "--runtime-attestation-json",
            str(attestation_path),
            "--sensitive-value-env",
            "BENCHMARK_TOOLKIT_TEST_SECRET",
            "--require-qualified",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["integrity_qualified"] is True
    assert payload["public_boundary"]["input_paths_recorded"] is False
    assert secret not in completed.stdout
    assert str(tmp_path) not in completed.stdout
