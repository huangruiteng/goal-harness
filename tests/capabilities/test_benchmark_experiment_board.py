from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit import (
    BENCHMARK_EXPERIMENT_BOARD_ROW_SCHEMA_VERSION,
    build_benchmark_experiment_board,
    default_benchmark_experiment_board_path,
    normalize_benchmark_experiment_board_row,
    read_benchmark_experiment_board_rows,
    render_benchmark_experiment_board_markdown,
    upsert_benchmark_experiment_board_row,
)
from loopx.capabilities.catalog import (
    build_capability_detail_packet,
    render_capability_detail_markdown,
)
from loopx.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _row(
    *,
    run_id: str,
    arm_id: str,
    arm_role: str,
    protocol_id: str,
    observed_at: str,
    f2p: int,
    comparison_anchor_run_id: str | None = None,
    claim_scope: str = "matched_study",
    status: str = "completed",
    score_countable: bool = True,
    fidelity: str = "qualified",
    insight_status: str = "complete",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": BENCHMARK_EXPERIMENT_BOARD_ROW_SCHEMA_VERSION,
        "benchmark_id": "fixture-swe@1",
        "study_id": "native-goal-study",
        "case_id": "case-12",
        "run_id": run_id,
        "arm_id": arm_id,
        "arm_role": arm_role,
        "attempt": 1,
        "status": status,
        "observed_at": observed_at,
        "model_id": "solver-model-v1",
        "protocol_id": protocol_id,
        "comparison_protocol_id": "native-goal-corrected-v1",
        "claim_scope": claim_scope,
        "primary_metric": "feature_pass",
        "guardrail_metrics": ["preservation_pass", "reward"],
        "metrics": {
            "feature_pass": {
                "value": f2p,
                "total": 66,
                "higher_is_better": True,
            },
            "preservation_pass": {
                "value": 293,
                "total": 293,
                "higher_is_better": True,
            },
            "reward": {"value": 0, "higher_is_better": True},
        },
        "countability": {
            "integrity_qualified": score_countable,
            "official_result_present": status == "completed",
            "score_countable": score_countable,
        },
        "treatment_fidelity": fidelity,
        "effort": {
            "duration_ms": 1000,
            "agent_steps": 10,
            "estimated_cost_usd": 0.25,
        },
        "insight": {
            "status": insight_status,
            "classification": "boundary-mismatch",
            "artifact_ref": "case-12-insight.json",
        },
    }
    if comparison_anchor_run_id is not None:
        payload["comparison_anchor_run_id"] = comparison_anchor_run_id
    return payload


def _baseline(**overrides: object) -> dict[str, object]:
    payload = _row(
        run_id="baseline-12",
        arm_id="native-goal",
        arm_role="baseline",
        protocol_id="runner-v21",
        observed_at="2026-08-18T00:00:00+00:00",
        f2p=0,
        fidelity="not_applicable",
    )
    payload.update(overrides)
    return payload


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


def test_row_rejects_raw_or_path_like_fields() -> None:
    raw_field = _baseline(raw_trajectory="private content")
    with pytest.raises(ValueError, match="unsupported fields"):
        normalize_benchmark_experiment_board_row(raw_field)

    path_ref = _baseline()
    path_ref["insight"] = {
        "status": "complete",
        "artifact_ref": "/private/case-12-insight.json",
    }
    with pytest.raises(ValueError, match="public-safe token"):
        normalize_benchmark_experiment_board_row(path_ref)


def test_row_rejects_illegal_role_and_countability_states() -> None:
    baseline_with_anchor = _baseline(comparison_anchor_run_id="other-run")
    with pytest.raises(ValueError, match="baseline rows cannot name"):
        normalize_benchmark_experiment_board_row(baseline_with_anchor)

    standard_without_anchor = _row(
        run_id="control-12",
        arm_id="loop-control",
        arm_role="control",
        protocol_id="runner-v23",
        observed_at="2026-08-18T00:20:00+00:00",
        f2p=64,
    )
    with pytest.raises(ValueError, match="non-baseline rows must name"):
        normalize_benchmark_experiment_board_row(standard_without_anchor)

    explore_with_study_claim = _row(
        run_id="explore-12",
        arm_id="combined-critic",
        arm_role="explore",
        protocol_id="runner-v23",
        observed_at="2026-08-18T00:40:00+00:00",
        f2p=66,
        comparison_anchor_run_id="control-12",
    )
    with pytest.raises(ValueError, match="explore rows must use diagnostic_only"):
        normalize_benchmark_experiment_board_row(explore_with_study_claim)

    running_countable = _baseline(status="running")
    with pytest.raises(ValueError, match="score_countable requires completed"):
        normalize_benchmark_experiment_board_row(running_countable)

    unqualified_countable = _baseline(
        countability={
            "integrity_qualified": False,
            "official_result_present": True,
            "score_countable": True,
        }
    )
    with pytest.raises(ValueError, match="requires integrity_qualified"):
        normalize_benchmark_experiment_board_row(unqualified_countable)


def test_board_keeps_standard_and_explore_lanes_and_compares_explicit_anchor() -> None:
    baseline = _baseline()
    treatment = _row(
        run_id="control-12",
        arm_id="loop-control",
        arm_role="control",
        protocol_id="runner-v23",
        observed_at="2026-08-18T00:20:00+00:00",
        f2p=64,
        comparison_anchor_run_id="baseline-12",
    )
    explore = _row(
        run_id="explore-12",
        arm_id="combined-critic",
        arm_role="explore",
        protocol_id="runner-v23",
        observed_at="2026-08-18T00:40:00+00:00",
        f2p=66,
        comparison_anchor_run_id="control-12",
        claim_scope="diagnostic_only",
    )

    board = build_benchmark_experiment_board([baseline, treatment, explore])

    assert board["summary"]["arm_role_counts"] == {
        "baseline": 1,
        "control": 1,
        "explore": 1,
        "treatment": 0,
    }
    assert board["summary"]["matched_pair_countable_count"] == 2
    assert board["summary"]["comparison_arm_role_counts"] == {
        "control": {"all": 1, "matched_pair_countable": 1},
        "explore": {"all": 1, "matched_pair_countable": 1},
        "treatment": {"all": 0, "matched_pair_countable": 0},
    }
    assert board["summary"]["comparison_claim_scope_counts"] == {
        "diagnostic_only": {"all": 1, "matched_pair_countable": 1},
        "inventory_only": {"all": 0, "matched_pair_countable": 0},
        "matched_study": {"all": 1, "matched_pair_countable": 1},
    }
    rendered = render_benchmark_experiment_board_markdown(board)
    assert "- Countable matched-study comparisons: `1`" in rendered
    assert "- Countable diagnostic-only comparisons: `1`" in rendered
    comparisons = {item["candidate_arm_role"]: item for item in board["comparisons"]}
    assert comparisons["control"]["metric_deltas"]["feature_pass"]["delta"] == 64
    assert comparisons["control"]["metric_deltas"]["feature_pass"]["direction"] == (
        "improved"
    )
    assert comparisons["control"]["warning_codes"] == [
        "exact_protocol_revision_differs"
    ]
    assert comparisons["explore"]["claim_scope"] == "diagnostic_only"
    assert comparisons["explore"]["comparison_anchor_arm_role"] == "control"
    assert comparisons["explore"]["metric_deltas"]["feature_pass"]["delta"] == 2
    assert board["agent_guidance"]["required_sequence"][0] == (
        "read_board_before_launch_or_case_selection"
    )


def test_locked_jsonl_upsert_updates_one_stable_run_row(tmp_path: Path) -> None:
    ledger = tmp_path / "experiment-board.jsonl"
    running = _baseline(
        status="running",
        metrics={},
        countability={
            "integrity_qualified": False,
            "official_result_present": False,
            "score_countable": False,
        },
        insight={"status": "pending"},
    )
    first = upsert_benchmark_experiment_board_row(ledger, running)
    second = upsert_benchmark_experiment_board_row(
        ledger, _baseline(arm_id="corrected-native-goal")
    )
    rows = read_benchmark_experiment_board_rows(ledger)

    assert first["write"]["status"] == "inserted"
    assert second["write"]["status"] == "updated"
    assert second["write"]["path_recorded"] is False
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["arm_id"] == "corrected-native-goal"
    assert "domain_state_key" not in rows[0]


def test_upsert_rejects_stale_transition_after_terminal_state(tmp_path: Path) -> None:
    ledger = tmp_path / "experiment-board.jsonl"
    upsert_benchmark_experiment_board_row(ledger, _baseline())

    stale_running = _baseline(
        status="running",
        metrics={},
        countability={
            "integrity_qualified": False,
            "official_result_present": False,
            "score_countable": False,
        },
        insight={"status": "pending"},
    )
    with pytest.raises(ValueError, match="cannot move from completed to running"):
        upsert_benchmark_experiment_board_row(ledger, stale_running)

    rows = read_benchmark_experiment_board_rows(ledger)
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"


def test_cli_previews_then_writes_and_reads_board(tmp_path: Path) -> None:
    row_path = tmp_path / "row.json"
    row_path.write_text(json.dumps(_baseline()), encoding="utf-8")
    command = [
        str(REPO_ROOT / "scripts/loopx"),
        "benchmark",
        "experiment-board-upsert",
        "--goal-id",
        "fixture-goal",
        "--project",
        str(tmp_path),
        "--row-json",
        str(row_path),
        "--format",
        "json",
    ]

    preview = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    preview_payload = json.loads(preview.stdout)
    ledger = default_benchmark_experiment_board_path(
        project=tmp_path, goal_id="fixture-goal"
    )
    assert preview_payload["write"]["status"] == "preview_inserted"
    assert preview_payload["write"]["write_performed"] is False
    assert not ledger.exists()

    executed = subprocess.run(
        [*command, "--execute"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    executed_payload = json.loads(executed.stdout)
    assert executed_payload["write"]["status"] == "inserted"
    assert executed_payload["path_recorded"] is False
    assert str(tmp_path) not in executed.stdout
    assert ledger.exists()

    shown = subprocess.run(
        [
            str(REPO_ROOT / "scripts/loopx"),
            "benchmark",
            "experiment-board-show",
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
    shown_payload = json.loads(shown.stdout)
    assert shown_payload["summary"]["run_count"] == 1
    assert shown_payload["agent_guidance"]["next_action"] == (
        "close_running_rows_or_review_matched_comparisons"
    )


def test_cli_omitted_project_routes_board_to_registered_goal_repo(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, global_registry = _connected_goal_registries(tmp_path)
    unrelated = tmp_path / "linked-worktree"
    unrelated.mkdir()
    row_path = tmp_path / "row.json"
    row_path.write_text(json.dumps(_baseline()), encoding="utf-8")
    monkeypatch.chdir(unrelated)

    assert (
        main(
            [
                "--registry",
                str(global_registry),
                "benchmark",
                "experiment-board-upsert",
                "--goal-id",
                "fixture-goal",
                "--row-json",
                str(row_path),
                "--execute",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    ledger = default_benchmark_experiment_board_path(
        project=project,
        goal_id="fixture-goal",
    )

    assert payload["summary"]["run_count"] == 1
    assert ledger.is_file()
    assert not (unrelated / ".loopx").exists()


def test_cli_explicit_project_cannot_override_registered_goal_repo(
    tmp_path: Path,
    capsys,
) -> None:
    project, global_registry = _connected_goal_registries(tmp_path)
    stale_project = tmp_path / "stale-linked-worktree"
    stale_project.mkdir()
    row_path = tmp_path / "row.json"
    row_path.write_text(json.dumps(_baseline()), encoding="utf-8")

    with pytest.raises(SystemExit):
        main(
            [
                "--registry",
                str(global_registry),
                "benchmark",
                "experiment-board-upsert",
                "--goal-id",
                "fixture-goal",
                "--project",
                str(stale_project),
                "--row-json",
                str(row_path),
                "--execute",
                "--format",
                "json",
            ]
        )

    assert "--project must match the canonical connected goal repository" in (
        capsys.readouterr().err
    )
    assert not default_benchmark_experiment_board_path(
        project=project,
        goal_id="fixture-goal",
    ).exists()
    assert not (stale_project / ".loopx").exists()


def test_capability_show_teaches_agents_to_use_the_board() -> None:
    packet = build_capability_detail_packet("benchmark-toolkit")
    capability = packet["capability"]
    usage = capability["agent_usage"]
    rendered = render_capability_detail_markdown(packet)

    assert usage["required_sequence"][0] == (
        "read_experiment_board_before_launch_or_case_selection"
    )
    assert "experiment-board-show" in usage["board_commands"]["read"]
    assert "experiment-board-upsert" in usage["board_commands"]["write"]
    assert "## Agent Usage" in rendered
    assert "read_experiment_board_before_launch_or_case_selection" in rendered
