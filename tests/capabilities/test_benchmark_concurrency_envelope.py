from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit import (
    admit_benchmark_case,
    build_benchmark_concurrency_config,
    build_benchmark_concurrency_status,
    configure_benchmark_concurrency_envelope,
    default_benchmark_concurrency_envelope_path,
    read_benchmark_concurrency_envelope,
    release_benchmark_case,
)
from loopx.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _connected_goal_registries(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "canonical-project"
    source_registry = project / ".loopx" / "registry.json"
    source_registry.parent.mkdir(parents=True)
    goal = {
        "id": "fixture-goal",
        "objective": "Run a public benchmark study.",
        "repo": str(project),
    }
    source_registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(tmp_path / "source-runtime"),
                "goals": [goal],
            }
        ),
        encoding="utf-8",
    )
    global_registry = tmp_path / "shared-runtime" / "registry.global.json"
    global_registry.parent.mkdir(parents=True)
    global_registry.write_text(
        json.dumps(
            {
                "registry_role": "global-local",
                "common_runtime_root": str(global_registry.parent),
                "goals": [{**goal, "source_registry": str(source_registry)}],
            }
        ),
        encoding="utf-8",
    )
    return project, global_registry


def _configure(
    path: Path,
    *,
    total: int = 8,
    target: int | None = None,
    baseline: int = 7,
) -> None:
    result = configure_benchmark_concurrency_envelope(
        path,
        build_benchmark_concurrency_config(
            max_active_cases=total,
            target_active_cases=target,
            max_baseline_cases=baseline,
            max_test_cases=total,
            reserved_test_cases=1,
        ),
        execute=True,
        observed_at="2026-08-18T07:00:00Z",
    )
    assert result["ok"] is True
    assert result["write_performed"] is True


def test_config_rejects_role_caps_outside_total() -> None:
    with pytest.raises(ValueError, match="max_baseline_cases"):
        build_benchmark_concurrency_config(
            max_active_cases=4,
            max_baseline_cases=5,
        )
    with pytest.raises(ValueError, match="reserved_test_cases"):
        build_benchmark_concurrency_config(
            max_active_cases=4,
            max_test_cases=1,
            reserved_test_cases=2,
        )
    with pytest.raises(ValueError, match="target_active_cases"):
        build_benchmark_concurrency_config(
            max_active_cases=4,
            target_active_cases=5,
        )
    with pytest.raises(ValueError, match="combined baseline and test capacity"):
        build_benchmark_concurrency_config(
            max_active_cases=8,
            target_active_cases=7,
            max_baseline_cases=3,
            max_test_cases=3,
        )


def test_status_hints_backfill_to_target_without_weakening_hard_cap(
    tmp_path: Path,
) -> None:
    path = tmp_path / "concurrency-envelope.json"
    _configure(path, total=8, target=4, baseline=7)

    initial = build_benchmark_concurrency_status(
        read_benchmark_concurrency_envelope(path)
    )
    assert initial["config"]["max_active_cases"] == 8
    assert initial["target_occupancy"] == {
        "active_cases": 4,
        "current_cases": 0,
        "missing_cases": 4,
        "underfilled": True,
        "utilization": 0.0,
    }
    assert initial["backfill_hint"]["preferred_arm_group"] == "test"
    assert initial["runtime_reconciliation_hint"] == {
        "required_on_transition_or_cadence": True,
        "reason_code": "admission_ledger_is_not_runtime_liveness",
        "active_count_source": "admission_ledger",
        "authoritative_observation": "benchmark_runtime_observation_v0",
        "observation_command": "loopx benchmark runtime-observation --help",
        "triggers": [
            "launch_receipt",
            "terminal_transition",
            "runner_invalid_transition",
            "periodic_liveness_check",
        ],
        "instruction": (
            "Classify exact-job receipts and runner-owner liveness through "
            "runtime-observation. Apply its typed terminal or runner-invalid transition "
            "before releasing that run, then read concurrency-status and backfill any "
            "reported gap."
        ),
    }
    assert initial["next_action"] == "backfill_to_target"

    for index, role in enumerate(("treatment", "baseline", "baseline", "baseline")):
        result = admit_benchmark_case(
            path,
            run_id=f"run-{index}",
            case_id=f"case-{index}",
            arm_role=role,
            execute=True,
            admitted_at=f"2026-08-18T07:0{index + 1}:00Z",
        )
        assert result["admitted"] is True

    at_target = build_benchmark_concurrency_status(
        read_benchmark_concurrency_envelope(path)
    )
    assert at_target["target_occupancy"]["underfilled"] is False
    assert at_target["remaining_capacity"]["total"] == 4
    assert (
        at_target["runtime_reconciliation_hint"]["active_count_source"]
        == "admission_ledger"
    )
    assert at_target["next_action"] == "admit_before_launch"


def test_reserved_test_slot_prevents_baseline_starvation(tmp_path: Path) -> None:
    path = tmp_path / "concurrency-envelope.json"
    _configure(path, total=4, baseline=4)

    for index in range(3):
        result = admit_benchmark_case(
            path,
            run_id=f"baseline-{index}",
            case_id=f"case-{index}",
            arm_role="baseline",
            execute=True,
            admitted_at=f"2026-08-18T07:0{index + 1}:00Z",
        )
        assert result["admitted"] is True

    blocked = admit_benchmark_case(
        path,
        run_id="baseline-3",
        case_id="case-3",
        arm_role="baseline",
        execute=True,
        admitted_at="2026-08-18T07:04:00Z",
    )
    assert blocked["ok"] is False
    assert blocked["reason_codes"] == ["reserved_test_capacity"]

    test_arm = admit_benchmark_case(
        path,
        run_id="control-4",
        case_id="case-4",
        arm_role="control",
        execute=True,
        admitted_at="2026-08-18T07:05:00Z",
    )
    assert test_arm["admitted"] is True
    assert test_arm["status"]["active_counts"] == {
        "total": 4,
        "baseline": 3,
        "test": 1,
    }


def test_admission_is_idempotent_and_release_reopens_capacity(tmp_path: Path) -> None:
    path = tmp_path / "concurrency-envelope.json"
    _configure(path, total=2, baseline=1)
    first = admit_benchmark_case(
        path,
        run_id="control-1",
        case_id="case-1",
        arm_role="treatment",
        execute=True,
        admitted_at="2026-08-18T07:01:00Z",
    )
    repeated = admit_benchmark_case(
        path,
        run_id="control-1",
        case_id="case-1",
        arm_role="treatment",
        execute=True,
        admitted_at="2026-08-18T07:02:00Z",
    )
    assert first["write_performed"] is True
    assert repeated["idempotent"] is True
    assert repeated["write_performed"] is False

    released = release_benchmark_case(
        path,
        run_id="control-1",
        execute=True,
        released_at="2026-08-18T07:03:00Z",
    )
    repeated_release = release_benchmark_case(
        path,
        run_id="control-1",
        execute=True,
        released_at="2026-08-18T07:04:00Z",
    )
    assert released["released"] is True
    assert released["write_performed"] is True
    assert repeated_release["idempotent"] is True
    assert repeated_release["write_performed"] is False
    assert (
        build_benchmark_concurrency_status(read_benchmark_concurrency_envelope(path))[
            "active_counts"
        ]["total"]
        == 0
    )


def test_atomic_admission_never_exceeds_total_capacity(tmp_path: Path) -> None:
    path = tmp_path / "concurrency-envelope.json"
    _configure(path, total=3, baseline=2)

    def admit(index: int) -> dict[str, object]:
        return admit_benchmark_case(
            path,
            run_id=f"run-{index}",
            case_id=f"case-{index}",
            arm_role="control" if index == 0 else "baseline",
            execute=True,
            admitted_at=f"2026-08-18T07:{index + 1:02d}:00Z",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(admit, range(12)))

    assert sum(result["admitted"] is True for result in results) == 3
    status = build_benchmark_concurrency_status(
        read_benchmark_concurrency_envelope(path)
    )
    assert status["active_counts"]["total"] == 3
    assert status["overcommitted"] is False


def test_cli_previews_config_and_requires_admission_before_launch(
    tmp_path: Path,
) -> None:
    base = [
        str(REPO_ROOT / "scripts/loopx"),
        "benchmark",
        "concurrency-configure",
        "--goal-id",
        "fixture-goal",
        "--project",
        str(tmp_path),
        "--max-active-cases",
        "8",
        "--target-active-cases",
        "6",
        "--max-baseline-cases",
        "7",
        "--max-test-cases",
        "4",
        "--reserved-test-cases",
        "1",
        "--format",
        "json",
    ]
    path = default_benchmark_concurrency_envelope_path(
        project=tmp_path, goal_id="fixture-goal"
    )
    preview = subprocess.run(
        base,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(preview.stdout)["dry_run"] is True
    assert not path.exists()

    configured = subprocess.run(
        [*base, "--execute"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    configured_payload = json.loads(configured.stdout)
    assert configured_payload["write_performed"] is True
    assert str(tmp_path) not in configured.stdout

    admitted = subprocess.run(
        [
            str(REPO_ROOT / "scripts/loopx"),
            "benchmark",
            "concurrency-admit",
            "--goal-id",
            "fixture-goal",
            "--project",
            str(tmp_path),
            "--run-id",
            "baseline-1",
            "--case-id",
            "case-1",
            "--arm-role",
            "baseline",
            "--execute",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(admitted.stdout)["admitted"] is True

    shown = subprocess.run(
        [
            str(REPO_ROOT / "scripts/loopx"),
            "benchmark",
            "concurrency-status",
            "--goal-id",
            "fixture-goal",
            "--project",
            str(tmp_path),
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(shown.stdout)
    assert payload["active_counts"] == {"total": 1, "baseline": 1, "test": 0}
    assert payload["target_occupancy"]["missing_cases"] == 5
    assert payload["backfill_hint"]["required"] is True
    assert payload["next_action"] == "backfill_to_target"


def test_cli_omitted_project_routes_envelope_to_registered_goal_repo(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, global_registry = _connected_goal_registries(tmp_path)
    unrelated = tmp_path / "linked-worktree"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert (
        main(
            [
                "--registry",
                str(global_registry),
                "benchmark",
                "concurrency-configure",
                "--goal-id",
                "fixture-goal",
                "--max-active-cases",
                "4",
                "--max-baseline-cases",
                "3",
                "--reserved-test-cases",
                "1",
                "--execute",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    envelope = default_benchmark_concurrency_envelope_path(
        project=project,
        goal_id="fixture-goal",
    )

    assert payload["status"]["config"]["max_active_cases"] == 4
    assert envelope.is_file()
    assert not (unrelated / ".loopx").exists()
