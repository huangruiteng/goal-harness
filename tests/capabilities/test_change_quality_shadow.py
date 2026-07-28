from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.capabilities.change_quality.result import (
    REVIEW_LENS_IDS,
    SIMPLIFY_PRIMARY_LENS_IDS,
)
from loopx.capabilities.change_quality.shadow import (
    CHANGE_QUALITY_SHADOW_RESULT_SCHEMA_VERSION,
    build_change_quality_shadow_prompt,
    build_change_quality_shadow_receipt,
    change_quality_shadow_output_schema,
    grade_change_quality_shadow_result,
    load_change_quality_shadow_matrix,
    normalize_change_quality_shadow_result,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "tests/fixtures/change_quality/model_shadow_matrix.json"


def _matrix() -> dict:
    return load_change_quality_shadow_matrix(MATRIX_PATH)


def _case(case_id: str) -> dict:
    return next(case for case in _matrix()["cases"] if case["case_id"] == case_id)


def _result(
    case: dict,
    *,
    version: str = "v1",
    findings: list[dict] | None = None,
    lenses: list[str] | None = None,
    safe_fix: str | None = None,
    simplification: str | None = None,
) -> dict:
    return {
        "schema_version": CHANGE_QUALITY_SHADOW_RESULT_SCHEMA_VERSION,
        "case_id": case["case_id"],
        "contract_version": version,
        "summary": "Reviewed the exact public fixture diff.",
        "findings": findings or [],
        "reviewed_lenses": (
            lenses if lenses is not None else list(SIMPLIFY_PRIMARY_LENS_IDS)
        ),
        "simplification": {
            "outcome": (simplification or case["gold"]["simplification_outcome"]),
            "reason": "The selected outcome matches the smallest coherent change.",
        },
        "safe_fix": {
            "action": safe_fix or case["gold"]["safe_fix_action"],
            "reason": "The repair boundary is explicit and behavior preserving.",
        },
        "validation_commands": ["python3 -m unittest"],
    }


def _finding(*, finding_class: str, path: str) -> dict:
    return {
        "finding_class": finding_class,
        "severity": "warning",
        "code": "known-complexity",
        "path": path,
        "line": 1,
        "message": "The changed implementation violates the fixture contract.",
    }


def test_shadow_matrix_covers_five_real_prs_and_three_languages() -> None:
    matrix = _matrix()

    assert len(matrix["cases"]) == 8
    assert sum(case["kind"] == "real_pr_clean" for case in matrix["cases"]) == 5
    synthetic = [
        case for case in matrix["cases"] if case["kind"] == "synthetic_simplification"
    ]
    assert {case["language"] for case in synthetic} == {
        "python",
        "rust",
        "typescript",
    }
    assert all(len(case["gold"]["findings"]) == 1 for case in synthetic)


def test_v0_prompt_does_not_smuggle_in_v1_lens_ids() -> None:
    case = _case("pr-2590-clean")

    v0 = build_change_quality_shadow_prompt(case, contract_version="v0")
    v1 = build_change_quality_shadow_prompt(case, contract_version="v1")

    assert all(lens_id not in v0 for lens_id in REVIEW_LENS_IDS)
    assert all(lens_id in v1 for lens_id in SIMPLIFY_PRIMARY_LENS_IDS)
    assert "Do not modify tracked files" in v0
    assert "Do not modify tracked files" in v1


def test_output_schema_is_closed_and_bounded() -> None:
    schema = change_quality_shadow_output_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["findings"]["maxItems"] == 12
    assert schema["properties"]["reviewed_lenses"]["maxItems"] == 20
    assert set(schema["required"]) == set(schema["properties"])


def test_normalizer_and_grader_match_seeded_python_simplification() -> None:
    case = _case("python-one-use-wrapper")
    raw = _result(
        case,
        findings=[
            _finding(
                finding_class="complexity",
                path="src/app.py",
            )
        ],
    )

    normalized = normalize_change_quality_shadow_result(
        raw,
        case=case,
        contract_version="v1",
    )
    grade = grade_change_quality_shadow_result(normalized, case=case)

    assert grade["matched_finding_count"] == 1
    assert grade["false_positive_count"] == 0
    assert grade["false_negative_count"] == 0
    assert grade["lens_coverage_count"] == len(SIMPLIFY_PRIMARY_LENS_IDS)
    assert grade["safe_fix_match"] is True
    assert grade["simplification_match"] is True


def test_clean_case_penalizes_speculative_finding() -> None:
    case = _case("pr-2597-clean")
    raw = _result(
        case,
        findings=[
            _finding(
                finding_class="complexity",
                path="loopx/control_plane/goals/goal_frontier.py",
            )
        ],
    )

    normalized = normalize_change_quality_shadow_result(
        raw,
        case=case,
        contract_version="v1",
    )
    grade = grade_change_quality_shadow_result(normalized, case=case)

    assert grade["matched_finding_count"] == 0
    assert grade["false_positive_count"] == 1
    assert grade["false_negative_count"] == 0


def test_normalizer_rejects_local_paths_and_mismatched_identity() -> None:
    case = _case("python-one-use-wrapper")
    raw = _result(
        case,
        findings=[
            _finding(
                finding_class="correctness",
                path="/tmp/private.py",
            )
        ],
    )

    with pytest.raises(ValueError, match="repo-relative"):
        normalize_change_quality_shadow_result(
            raw,
            case=case,
            contract_version="v1",
        )

    raw = _result(case)
    raw["case_id"] = "another-case"
    with pytest.raises(ValueError, match="case_id"):
        normalize_change_quality_shadow_result(
            raw,
            case=case,
            contract_version="v1",
        )


def test_receipt_promotes_only_complete_accurate_bounded_v1() -> None:
    matrix = _matrix()
    runs = []
    for case in matrix["cases"]:
        expected_count = len(case["gold"]["findings"])
        for version in ("v0", "v1"):
            runs.append(
                {
                    "case_id": case["case_id"],
                    "contract_version": version,
                    "valid": True,
                    "expected_finding_count": expected_count,
                    "predicted_finding_count": expected_count,
                    "matched_finding_count": expected_count,
                    "false_positive_count": 0,
                    "false_negative_count": 0,
                    "lens_coverage_count": (
                        len(SIMPLIFY_PRIMARY_LENS_IDS) if version == "v1" else 1
                    ),
                    "lens_required_count": len(SIMPLIFY_PRIMARY_LENS_IDS),
                    "safe_fix_match": True,
                    "simplification_match": True,
                    "tracked_files_modified": False,
                    "input_tokens": 100,
                    "output_tokens": 100 if version == "v0" else 120,
                    "latency_ms": 1000 if version == "v0" else 1100,
                    "result_digest": f"sha256:{case['case_id']}-{version}",
                }
            )

    receipt = build_change_quality_shadow_receipt(
        matrix=matrix,
        runs=runs,
        model_ref="test-model:medium",
        source_commit="a" * 40,
    )

    assert receipt["arms"]["v0"]["primary_lens_completeness"] == 0.5
    assert receipt["arms"]["v1"]["primary_lens_completeness"] == 1.0
    assert receipt["strict_receipt_promotion_recommended"] is True
    assert receipt["automatic_policy_mutation_allowed"] is False
    assert receipt["persistence_boundary"] == {
        "raw_prompts_persisted": False,
        "raw_model_responses_persisted": False,
        "stderr_persisted": False,
    }


def test_receipt_fails_promotion_on_one_false_positive() -> None:
    matrix = _matrix()
    runs = []
    for case in matrix["cases"]:
        expected_count = len(case["gold"]["findings"])
        for version in ("v0", "v1"):
            false_positive = version == "v1" and case["case_id"] == "pr-2590-clean"
            runs.append(
                {
                    "case_id": case["case_id"],
                    "contract_version": version,
                    "valid": True,
                    "expected_finding_count": expected_count,
                    "predicted_finding_count": expected_count + int(false_positive),
                    "matched_finding_count": expected_count,
                    "false_positive_count": int(false_positive),
                    "false_negative_count": 0,
                    "lens_coverage_count": len(SIMPLIFY_PRIMARY_LENS_IDS),
                    "lens_required_count": len(SIMPLIFY_PRIMARY_LENS_IDS),
                    "safe_fix_match": True,
                    "simplification_match": True,
                    "tracked_files_modified": False,
                    "input_tokens": 100,
                    "output_tokens": 100,
                    "latency_ms": 1000,
                    "result_digest": f"sha256:{case['case_id']}-{version}",
                }
            )

    receipt = build_change_quality_shadow_receipt(
        matrix=matrix,
        runs=runs,
        model_ref="test-model:medium",
        source_commit="b" * 40,
    )

    assert receipt["arms"]["v1"]["precision"] == 0.75
    assert receipt["acceptance"]["v1_simplify_precision_at_least_0_8"] is False
    assert receipt["strict_receipt_promotion_recommended"] is False


def test_fixture_json_has_no_absolute_local_paths() -> None:
    raw = MATRIX_PATH.read_text(encoding="utf-8")

    assert "/Users/" not in raw
    assert "/tmp/" not in raw
    json.loads(raw)
