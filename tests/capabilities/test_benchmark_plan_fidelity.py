from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit import (
    BENCHMARK_PLAN_FIDELITY_SCHEMA_VERSION,
    BenchmarkPlanRole,
    build_benchmark_plan_fidelity_receipt,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _contract() -> dict[BenchmarkPlanRole, list[str]]:
    return {
        BenchmarkPlanRole.TECHNICAL_WORK: ["implement", "implementation"],
        BenchmarkPlanRole.INDEPENDENT_VALIDATION: ["validate", "validation"],
        BenchmarkPlanRole.REVIEW_REFINE: ["review", "review_refine"],
    }


def _required() -> dict[BenchmarkPlanRole, int]:
    return {
        BenchmarkPlanRole.TECHNICAL_WORK: 1,
        BenchmarkPlanRole.INDEPENDENT_VALIDATION: 1,
    }


def test_explicit_action_kind_aliases_qualify_stable_semantic_roles() -> None:
    receipt = build_benchmark_plan_fidelity_receipt(
        action_kinds=["implementation", "implementation", "validation"],
        role_action_kinds=_contract(),
        required_role_counts=_required(),
    )

    assert receipt["schema_version"] == BENCHMARK_PLAN_FIDELITY_SCHEMA_VERSION
    assert receipt["qualified"] is True
    assert receipt["classification"] == "plan_role_contract_qualified"
    assert receipt["observed_role_counts"] == {
        "technical_work": 2,
        "independent_validation": 1,
        "review_refine": 0,
    }
    assert receipt["classified_action_count"] == 3
    assert receipt["unclassified_action_count"] == 0
    assert receipt["blockers"] == []
    assert receipt["exact_action_kind_matching"] is True


def test_unconfigured_near_match_does_not_satisfy_required_role() -> None:
    receipt = build_benchmark_plan_fidelity_receipt(
        action_kinds=["implementation_detail", "validation_review"],
        role_action_kinds=_contract(),
        required_role_counts=_required(),
    )

    assert receipt["qualified"] is False
    assert receipt["classification"] == "required_plan_role_missing"
    assert receipt["observed_role_counts"]["technical_work"] == 0
    assert receipt["observed_role_counts"]["independent_validation"] == 0
    assert receipt["unclassified_action_count"] == 2
    assert receipt["blockers"] == [
        "required_role_missing:technical_work",
        "required_role_missing:independent_validation",
    ]


def test_caller_can_explicitly_map_compound_provider_tokens() -> None:
    contract = _contract()
    contract[BenchmarkPlanRole.TECHNICAL_WORK].append("implementation_detail")
    contract[BenchmarkPlanRole.INDEPENDENT_VALIDATION].append("validation_review")
    receipt = build_benchmark_plan_fidelity_receipt(
        action_kinds=["implementation_detail", "validation_review"],
        role_action_kinds=contract,
        required_role_counts=_required(),
    )

    assert receipt["qualified"] is True
    assert receipt["observed_role_counts"]["technical_work"] == 1
    assert receipt["observed_role_counts"]["independent_validation"] == 1


def test_receipt_does_not_record_todo_text_or_action_kind_tokens() -> None:
    private_like_token = "provider_private_implementation"
    receipt = build_benchmark_plan_fidelity_receipt(
        action_kinds=[private_like_token, "validation"],
        role_action_kinds={
            **_contract(),
            BenchmarkPlanRole.TECHNICAL_WORK: [
                "implement",
                private_like_token,
            ],
        },
        required_role_counts=_required(),
    )

    rendered = json.dumps(receipt, sort_keys=True)
    assert private_like_token not in rendered
    assert receipt["public_boundary"] == {
        "todo_text_recorded": False,
        "raw_action_kinds_recorded": False,
        "path_recorded": False,
        "trajectory_recorded": False,
    }
    assert receipt["write_performed"] is False


def test_overlapping_action_kind_contract_fails_closed() -> None:
    contract = _contract()
    contract[BenchmarkPlanRole.INDEPENDENT_VALIDATION].append("implementation")

    with pytest.raises(ValueError, match="^action_kind_contract_overlap$"):
        build_benchmark_plan_fidelity_receipt(
            action_kinds=["implementation", "validation"],
            role_action_kinds=contract,
            required_role_counts=_required(),
        )


def test_required_role_without_mapping_fails_closed() -> None:
    with pytest.raises(
        ValueError,
        match="^required_role_missing_action_kind_contract$",
    ):
        build_benchmark_plan_fidelity_receipt(
            action_kinds=["implementation"],
            role_action_kinds={
                BenchmarkPlanRole.TECHNICAL_WORK: ["implementation"],
            },
            required_role_counts=_required(),
        )


@pytest.mark.parametrize(
    (
        "action_kinds",
        "role_action_kinds",
        "required_role_counts",
        "error_type",
        "message",
    ),
    [
        (
            "implementation",
            _contract(),
            _required(),
            TypeError,
            "invalid_action_kinds",
        ),
        (
            ["implementation/unsafe"],
            _contract(),
            _required(),
            ValueError,
            "invalid_action_kind",
        ),
        (
            [1],
            _contract(),
            _required(),
            TypeError,
            "invalid_action_kind",
        ),
        (
            ["implementation"],
            {"unknown_role": ["implementation"]},
            _required(),
            ValueError,
            "invalid_benchmark_plan_role",
        ),
        (
            ["implementation"],
            _contract(),
            {BenchmarkPlanRole.TECHNICAL_WORK: 0},
            ValueError,
            "invalid_required_role_count",
        ),
    ],
)
def test_invalid_plan_contract_inputs_fail_closed(
    action_kinds: object,
    role_action_kinds: object,
    required_role_counts: object,
    error_type: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error_type, match=rf"^{message}$"):
        build_benchmark_plan_fidelity_receipt(
            action_kinds=action_kinds,  # type: ignore[arg-type]
            role_action_kinds=role_action_kinds,  # type: ignore[arg-type]
            required_role_counts=required_role_counts,  # type: ignore[arg-type]
        )


def test_cli_qualifies_real_provider_tokens_without_echoing_them() -> None:
    private_like_token = "provider-private-work"
    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts/loopx"),
            "benchmark",
            "plan-fidelity",
            "--action-kind",
            private_like_token,
            "--action-kind",
            "independent_validation",
            "--role-action-kind",
            f"technical_work={private_like_token}",
            "--role-action-kind",
            "independent_validation=independent_validation",
            "--required-role-count",
            "technical_work=1",
            "--required-role-count",
            "independent_validation=1",
            "--require-qualified",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    receipt = json.loads(completed.stdout)
    assert receipt["qualified"] is True
    assert receipt["observed_role_counts"]["technical_work"] == 1
    assert receipt["observed_role_counts"]["independent_validation"] == 1
    assert private_like_token not in completed.stdout


def test_cli_fails_closed_for_unmapped_near_match() -> None:
    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts/loopx"),
            "benchmark",
            "plan-fidelity",
            "--action-kind",
            "implementation_detail",
            "--role-action-kind",
            "technical_work=implementation",
            "--required-role-count",
            "technical_work=1",
            "--require-qualified",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    receipt = json.loads(completed.stdout)
    assert receipt["classification"] == "required_plan_role_missing"
    assert receipt["blockers"] == ["required_role_missing:technical_work"]
    assert "implementation_detail" not in completed.stdout


def test_cli_reduces_invalid_mapping_to_public_safe_receipt() -> None:
    invalid_assignment = "provider-private-assignment"
    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts/loopx"),
            "benchmark",
            "plan-fidelity",
            "--action-kind",
            "implementation",
            "--role-action-kind",
            invalid_assignment,
            "--required-role-count",
            "technical_work=1",
            "--require-qualified",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    receipt = json.loads(completed.stdout)
    assert receipt["classification"] == "plan_fidelity_input_invalid"
    assert receipt["blockers"] == ["plan_fidelity_input_invalid"]
    assert invalid_assignment not in completed.stdout
