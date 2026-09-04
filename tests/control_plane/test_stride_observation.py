from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loopx.control_plane.runtime.stride_observation import (
    STRIDE_EVALUATION_SCHEMA_VERSION,
    STRIDE_OBSERVATION_SCHEMA_VERSION,
    build_stride_observation,
    evaluate_stride_observation,
)

GOAL_ID = "fixture-stride-goal"
AGENT_ID = "codex-side-bypass"


def _write_run_index(
    runtime_root: Path,
    rows: list[dict],
) -> None:
    index_path = (
        runtime_root / "goals" / GOAL_ID / "runs" / "index.jsonl"
    )
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _run(
    *,
    classification: str,
    outcome: str,
    minutes_ago: int,
) -> dict:
    generated_at = (
        datetime.now(UTC) - timedelta(minutes=minutes_ago)
    ).isoformat()
    return {
        "generated_at": generated_at,
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "classification": classification,
        "delivery_outcome": outcome,
    }


def test_empty_runtime_is_fail_closed_observation(tmp_path: Path) -> None:
    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["schema_version"] == STRIDE_OBSERVATION_SCHEMA_VERSION
    assert observation["lineage"]["source_run_count"] == 0
    assert observation["effect"]["unknown"] is True
    assert observation["shadow_only"] is True
    assert observation["delivery"]["evidence_fresh"] is False
    assert observation["authority"]["segment_disposition"] == "unknown"


def test_derives_delivery_and_authority_from_run_receipts(
    tmp_path: Path,
) -> None:
    _write_run_index(
        tmp_path,
        [
            _run(
                classification="bounded_replan_progress",
                outcome="outcome_progress",
                minutes_ago=180,
            ),
            _run(
                classification="exact_head_review_delivered_3206",
                outcome="outcome_progress",
                minutes_ago=60,
            ),
            _run(
                classification="monitor_watch",
                outcome="surface_only",
                minutes_ago=1,
            ),
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["lineage"]["source_run_count"] == 3
    assert observation["delivery"]["material_slices"] == 2
    assert observation["delivery"]["latest_outcome"] == "surface_only"
    assert observation["delivery"]["evidence_fresh"] is True
    assert observation["authority"]["bounded_slices_since_change"] == 2
    assert observation["effect"]["unknown"] is True
    assert observation["mismatch_signals"] == []


def test_stale_evidence_reports_settlement_lag_signal(tmp_path: Path) -> None:
    _write_run_index(
        tmp_path,
        [
            _run(
                classification="monitor_watch",
                outcome="surface_only",
                minutes_ago=12 * 60,
            )
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["delivery"]["evidence_fresh"] is False
    assert observation["mismatch_signals"] == ["settlement_lag"]

    evaluation = evaluate_stride_observation(observation)
    assert evaluation["schema_version"] == STRIDE_EVALUATION_SCHEMA_VERSION
    assert evaluation["signals"] == ["settlement_lag"]
    assert evaluation["recommendations"] == []
    assert evaluation["shadow_only"] is True


def test_other_agent_runs_are_not_attributed(tmp_path: Path) -> None:
    _write_run_index(
        tmp_path,
        [
            {
                "generated_at": (
                    datetime.now(UTC) - timedelta(minutes=5)
                ).isoformat(),
                "goal_id": GOAL_ID,
                "agent_id": "codex-quality-qualification",
                "classification": "exact_head_review_delivered_3206",
                "delivery_outcome": "outcome_progress",
            }
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["lineage"]["source_run_count"] == 0


# --- Synthetic stride-boundary fixture (RFC #3204 section 13) -------------
#
# Hand-built synthetic receipts only: no copied provider payloads, source or
# draft bodies, review text, private locators, host paths, credentials, or
# cursor state. Each assertion traces to one validation criterion of the
# hierarchical stride RFC.


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_boundary_observation_stays_shadow_only_across_segment_states(
    tmp_path: Path,
) -> None:
    # Criterion 8: shadow mode changes no scheduling, quota, notification,
    # gate, or execution behavior. Checked across every synthetic boundary
    # state, with a byte snapshot proving the projection never mutates the
    # runtime tree it observes.
    states: dict[str, list[dict]] = {
        "no_receipts": [],
        "mid_segment_fresh": [
            _run(
                classification="bounded_progress_report",
                outcome="outcome_progress",
                minutes_ago=90,
            ),
            _run(
                classification="bounded_progress_report",
                outcome="outcome_progress",
                minutes_ago=30,
            ),
        ],
        "after_authority_marker": [
            _run(
                classification="bounded_progress_report",
                outcome="outcome_progress",
                minutes_ago=120,
            ),
            _run(
                classification="bounded_replan_progress",
                outcome="outcome_progress",
                minutes_ago=60,
            ),
        ],
        "stale_evidence": [
            _run(
                classification="monitor_watch",
                outcome="surface_only",
                minutes_ago=12 * 60,
            ),
        ],
    }
    for name, rows in states.items():
        runtime_root = tmp_path / name
        if rows:
            _write_run_index(runtime_root, rows)
        before = _snapshot_tree(runtime_root)

        observation = build_stride_observation(
            runtime_root,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
        )
        evaluation = evaluate_stride_observation(observation)

        assert observation["shadow_only"] is True, name
        assert observation["effect"]["unknown"] is True, name
        assert evaluation["shadow_only"] is True, name
        assert evaluation["recommendations"] == [], name
        assert _snapshot_tree(runtime_root) == before, name


def test_boundary_missing_metrics_stay_unknown_not_inferred_from_prose(
    tmp_path: Path,
) -> None:
    # Criterion 2: missing host detail remains unknown rather than inferred
    # from prose. Authority-marker words and progress claims live only in
    # fields the projection never reads; they must not manufacture metrics.
    _write_run_index(
        tmp_path,
        [
            {
                "generated_at": (
                    datetime.now(UTC) - timedelta(minutes=30)
                ).isoformat(),
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "summary": (
                    "operator said this replan changed the vision and the "
                    "gate; feels like real progress"
                ),
            },
            {
                "generated_at": (
                    datetime.now(UTC) - timedelta(minutes=10)
                ).isoformat(),
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "classification": "",
                "delivery_outcome": "",
                "notes": "another stride boundary crossed in prose only",
            },
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["lineage"]["source_run_count"] == 2
    assert observation["delivery"]["material_slices"] == 0
    assert observation["delivery"]["latest_outcome"] == "none"
    assert observation["authority"]["bounded_slices_since_change"] == 2
    assert observation["authority"]["segment_disposition"] == "unknown"
    assert observation["effect"]["unknown"] is True


def test_boundary_authority_changes_require_explicit_markers(
    tmp_path: Path,
) -> None:
    # Criterion 6: reports with no authority delta are not counted as heavy
    # steering. Only complete values from the controlled writer allowlist
    # restart the bounded-slice count; status, monitor, review, and vision
    # checkpoint classifications never do, and the latest explicit value wins.
    _write_run_index(
        tmp_path / "with_markers",
        [
            _run(
                classification="bounded_progress_report",
                outcome="outcome_progress",
                minutes_ago=240,
            ),
            _run(
                classification="surface_status_note",
                outcome="surface_only",
                minutes_ago=180,
            ),
            _run(
                classification="bounded_replan_progress",
                outcome="outcome_progress",
                minutes_ago=120,
            ),
            _run(
                classification="monitor_watch",
                outcome="surface_only",
                minutes_ago=60,
            ),
            _run(
                classification="operator_gate_deferred",
                outcome="surface_only",
                minutes_ago=30,
            ),
            _run(
                classification="exact_head_review_delivered",
                outcome="outcome_progress",
                minutes_ago=5,
            ),
        ],
    )

    marked = build_stride_observation(
        tmp_path / "with_markers",
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )
    # Latest controlled authority value sits at index 4; only the final review
    # follows.
    assert marked["authority"]["bounded_slices_since_change"] == 1

    _write_run_index(
        tmp_path / "without_markers",
        [
            _run(
                classification="surface_status_note",
                outcome="surface_only",
                minutes_ago=120,
            ),
            _run(
                classification="monitor_watch",
                outcome="surface_only",
                minutes_ago=60,
            ),
            _run(
                classification="exact_head_review_delivered",
                outcome="outcome_progress",
                minutes_ago=10,
            ),
        ],
    )

    unmarked = build_stride_observation(
        tmp_path / "without_markers",
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )
    assert unmarked["authority"]["bounded_slices_since_change"] == 3


@pytest.mark.parametrize(
    "classification",
    [
        "revision_review",
        "supervision_check",
        "waiting_at_approval_gate",
        "provisional_benchmark_reward",
        "not_replan",
        "vision_check",
        "gate_not_approved",
        "gate_status_recorded_without_transition",
        "no_gate_changed",
        "replan_noop",
        "autonomous_replan_recorded",
        "route_continuation_replan_recorded",
        "successor_replan_recorded",
        "monitor_poll_autonomous_replan_recorded_v0",
        "goal_vision_checkpoint",
    ],
)
def test_boundary_unknown_classifications_stay_no_change(
    tmp_path: Path,
    classification: str,
) -> None:
    _write_run_index(
        tmp_path,
        [
            _run(
                classification="bounded_progress_report",
                outcome="outcome_progress",
                minutes_ago=120,
            ),
            _run(
                classification=classification,
                outcome="surface_only",
                minutes_ago=60,
            ),
            _run(
                classification="exact_head_review_delivered",
                outcome="outcome_progress",
                minutes_ago=10,
            ),
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["authority"]["bounded_slices_since_change"] == 3


@pytest.mark.parametrize(
    "classification",
    [
        "bounded_replan_progress",
        "operator_gate_approved",
        "operator_gate_rejected",
        "operator_gate_deferred",
    ],
)
def test_boundary_controlled_authority_classifications_reset_stride(
    tmp_path: Path,
    classification: str,
) -> None:
    _write_run_index(
        tmp_path,
        [
            _run(
                classification="bounded_progress_report",
                outcome="outcome_progress",
                minutes_ago=120,
            ),
            _run(
                classification=classification,
                outcome="surface_only",
                minutes_ago=60,
            ),
            _run(
                classification="exact_head_review_delivered",
                outcome="outcome_progress",
                minutes_ago=10,
            ),
        ],
    )

    observation = build_stride_observation(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert observation["authority"]["bounded_slices_since_change"] == 1


def test_boundary_projection_replays_byte_identical(tmp_path: Path) -> None:
    # Criterion 3: deterministic replay produces the same stride observation
    # and mismatch classification. Identical synthetic receipts are built
    # twice in two different runtime roots, with timestamps far from the
    # evidence-freshness boundary so wall-clock drift cannot flip a signal.
    rows = [
        _run(
            classification="bounded_replan_progress",
            outcome="outcome_progress",
            minutes_ago=300,
        ),
        _run(
            classification="bounded_progress_report",
            outcome="outcome_progress",
            minutes_ago=45,
        ),
    ]
    roots = [tmp_path / "runtime_alpha", tmp_path / "runtime_beta"]
    for root in roots:
        _write_run_index(root, rows)

    projections = set()
    for root in roots:
        for _ in range(2):
            observation = build_stride_observation(
                root,
                goal_id=GOAL_ID,
                agent_id=AGENT_ID,
            )
            evaluation = evaluate_stride_observation(observation)
            projections.add(
                json.dumps([observation, evaluation], sort_keys=True)
            )

    assert len(projections) == 1
