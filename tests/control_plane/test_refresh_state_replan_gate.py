"""Write-time gate: maintenance writebacks are rejected while replan is due."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.status.autonomous_replan_projection import (
    AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD,
)
from loopx.state_refresh import (
    enforce_open_replan_writeback,
    refresh_state_run,
)
from loopx.control_plane.work_items.semantic_replan_writeback import (
    qualify_replan_writeback,
)

GOAL_ID = "replan-gate-fixture"
AGENT_ID = "codex-replan-gate-agent"
STATE_TEXT = "# Active Goal State\n"


def _completed_advancement_chain_state() -> str:
    """Five completed slices with explicit lineage and no succession warning.

    The final non-advancement anchor keeps this fixture focused on the outcome
    checkpoint rule instead of the independent completed-without-successor
    rule.
    """

    lines = ["## Agent Todo", ""]
    for index in range(5):
        successor_id = (
            f"todo_completed_slice_{index + 1}"
            if index < 4
            else "todo_completed_outcome_anchor"
        )
        lines.extend(
            [
                f"- [x] [P1] Completed bounded slice {index}.",
                (
                    "  <!-- loopx:todo "
                    f"todo_id=todo_completed_slice_{index} status=done "
                    "task_class=advancement_task "
                    f"claimed_by={AGENT_ID} successor_todo_ids={successor_id} "
                    f"completed_at=2026-08-13T11%3A{30 + index:02d}%3A00%2B08%3A00 -->"
                ),
            ]
        )
    lines.extend(
        [
            "- [x] [P2] Persist the completed-chain lineage anchor.",
            (
                "  <!-- loopx:todo "
                "todo_id=todo_completed_outcome_anchor status=done "
                "task_class=continuous_monitor "
                f"claimed_by={AGENT_ID} "
                "completed_at=2026-08-13T11%3A35%3A00%2B08%3A00 -->"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _completed_advancement_without_successor_state() -> str:
    return f"""\
## Agent Todo

- [x] [P0] Completed a bounded advancement slice.
  <!-- loopx:todo todo_id=todo_unsettled_completion status=done task_class=advancement_task claimed_by={AGENT_ID} no_followup=false completion_continuation=active_goal completion_turn_key=turn-unsettled completed_at=2026-08-13T11%3A30%3A00%2B08%3A00 -->
"""


def _terminal_no_followup_vision() -> dict:
    return {
        "state": "no_followup",
        "vision_patch": {"acceptance_summary": "The bounded goal is complete."},
        "path_delta": {
            "outcome": "stop",
            "evidence_refs": ["evidence:terminal-coverage"],
        },
    }


def _durable_runs(count: int) -> list[dict]:
    return [
        {
            "classification": "source_audit_progress",
            "generated_at": f"2026-08-13T00:{index:02d}:00+00:00",
            "agent_id": AGENT_ID,
            "progress_scope": "agent_lane",
            "delivery_outcome": "surface_only",
        }
        for index in reversed(range(count))
    ]


def _call_gate(
    *,
    runs: list[dict],
    progress_observation: dict | None = None,
) -> None:
    enforce_open_replan_writeback(
        newest_first_runs=runs,
        state_text=STATE_TEXT,
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
        progress_observation=progress_observation,
    )


def _current_obligation_id(
    runs: list[dict],
    *,
    state_text: str = STATE_TEXT,
) -> str:
    obligation, _ = qualify_replan_writeback(
        newest_first_runs=runs,
        state_text=state_text,
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
    )
    assert obligation is not None
    return str(obligation["obligation_id"])


def test_maintenance_writeback_rejected_when_replan_due() -> None:
    with pytest.raises(ValueError) as exc:
        _call_gate(runs=_durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD))
    message = str(exc.value)
    assert "autonomous replan obligation" in message
    assert "typed semantic delta" in message
    assert "Host-projected replan context" in message


def test_typed_surface_delta_satisfies_periodic_obligation() -> None:
    semantic_delta = enforce_open_replan_writeback(
        newest_first_runs=_durable_runs(
            AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD
        ),
        state_text=STATE_TEXT,
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
        progress_observation={
            "schema_version": "typed_progress_observation_v0",
            "work_item_id": "todo-replan-slice",
            "surface_id": "surface-new",
            "result_class": "advanced",
            "evidence_ids": ["evidence-new-surface"],
        },
    )
    assert semantic_delta is not None
    assert semantic_delta["satisfying_outcomes"] == ["new_surface"]


def test_writeback_allowed_when_replan_not_due() -> None:
    _call_gate(runs=_durable_runs(5))


def test_refresh_state_run_rejects_maintenance_writeback(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = (
        project
        / ".codex"
        / "goals"
        / GOAL_ID
        / "ACTIVE_GOAL_STATE.md"
    )
    state.parent.mkdir(parents=True)
    state.write_text(STATE_TEXT, encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state.relative_to(project)),
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime_root = tmp_path / "runtime"
    runs_index = (
        runtime_root
        / "goals"
        / GOAL_ID
        / "runs"
        / "index.jsonl"
    )
    runs_index.parent.mkdir(parents=True)
    with runs_index.open("w", encoding="utf-8") as handle:
        for run in _durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD):
            handle.write(json.dumps(run) + "\n")

    with pytest.raises(ValueError) as exc:
        refresh_state_run(
            registry_path=registry_path,
            runtime_root_override=str(runtime_root),
            goal_id=GOAL_ID,
            project=project,
            state_file=None,
            classification="source_audit_progress",
            recommended_action="Observe the fixture.",
            delivery_batch_scale="single_surface",
            delivery_outcome="surface_only",
            agent_id=AGENT_ID,
            vision_unchanged_reason="无新攻击面，审计维持",
            dry_run=False,
            sync_global=False,
        )
    message = str(exc.value)
    assert "typed semantic delta" in message


def _prior_periodic_ack() -> dict:
    return {
        "classification": "autonomous_replan_recorded",
        "generated_at": "2026-08-13T11:26:03+08:00",
        "agent_id": AGENT_ID,
        "autonomous_replan_ack": {
            "schema_version": "autonomous_replan_ack_v0",
            "recorded": True,
            "source": "fixture",
            "semantic_delta": {
                "schema_version": "replan_semantic_delta_v0",
                "accepted": True,
                "outcomes": ["new_runnable_successor"],
                "satisfying_outcomes": ["new_runnable_successor"],
                "required_any_of": ["new_runnable_successor"],
                "obligation_id": "replan-85f352144255e4d9",
            },
        },
    }


def _open_vision_after_prior_ack() -> dict:
    return {
        "classification": "goal_vision_checkpoint",
        "generated_at": "2026-08-13T11:27:00+08:00",
        "agent_id": AGENT_ID,
        "agent_vision": {
            "schema_version": "goal_vision_replan_contract_v0",
            "agent_id": AGENT_ID,
            "state": "active",
            "vision_patch": {
                "vision_summary": "Qualify the active outcome.",
                "acceptance_summary": "Close the current outcome with evidence.",
                "advancement_policy": "repeat_until_closed",
                "replan_trigger_summary": "The current outcome path has drifted.",
            },
            "todo_delta": [],
        },
        "vision_checkpoint": {
            "schema_version": "vision_checkpoint_v0",
            "agent_id": AGENT_ID,
            "required": True,
            "satisfied": True,
            "decision": "unchanged",
            "triggers": [
                {
                    "kind": "material_delivery_outcome",
                    "delivery_outcome": "outcome_progress",
                }
            ],
        },
    }


def _rotated_vision_runs() -> list[dict]:
    return [
        _open_vision_after_prior_ack(),
        _prior_periodic_ack(),
        *_durable_runs(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD),
    ]


def test_rotated_vision_obligation_rejects_first_maintenance_writeback() -> None:
    """#3155: a prior periodic ACK cannot hide a new vision/frontier duty."""

    with pytest.raises(ValueError, match="required vision outcome"):
        enforce_open_replan_writeback(
            newest_first_runs=_rotated_vision_runs(),
            state_text=_completed_advancement_chain_state(),
            agent_id=AGENT_ID,
            goal_id=GOAL_ID,
        )


def test_rotated_vision_obligation_contains_all_three_acceptance_gaps() -> None:
    """The write gate sees quota's vision, checkpoint, and completed-chain truth."""

    obligation, semantic_delta = qualify_replan_writeback(
        newest_first_runs=_rotated_vision_runs(),
        state_text=_completed_advancement_chain_state(),
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
    )

    assert semantic_delta is not None
    assert semantic_delta["accepted"] is False
    assert semantic_delta["outcomes"] == []
    assert obligation is not None
    assert [trigger["kind"] for trigger in obligation["triggers"]] == [
        "vision_acceptance_gap",
        "vision_outcome_checkpoint_required",
        "vision_outcome_checkpoint_required",
    ]
    assert obligation["triggers"][1]["text"].startswith(
        "a material milestone closed without a fresh evidence-linked"
    )
    assert obligation["triggers"][2]["text"].startswith(
        "a completed advancement Todo chain"
    )
    assert obligation["triggers"][2]["completed_todo_count"] == 5
    assert obligation["triggers"][2]["completed_todo_threshold"] == 5


def test_refresh_state_run_rejects_maintenance_after_vision_obligation_rotation(
    tmp_path: Path,
) -> None:
    """#3155 end to end: quota/frontier truth also governs physical writes."""

    project = tmp_path / "project"
    state = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state.parent.mkdir(parents=True)
    state.write_text(_completed_advancement_chain_state(), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(project),
                        "state_file": str(state.relative_to(project)),
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime_root = tmp_path / "runtime"
    runs_index = runtime_root / "goals" / GOAL_ID / "runs" / "index.jsonl"
    runs_index.parent.mkdir(parents=True)
    with runs_index.open("w", encoding="utf-8") as handle:
        for run in reversed(_rotated_vision_runs()):
            handle.write(json.dumps(run) + "\n")

    before = state.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="required vision outcome"):
        refresh_state_run(
            registry_path=registry_path,
            runtime_root_override=str(runtime_root),
            goal_id=GOAL_ID,
            project=project,
            state_file=None,
            classification="source_audit_progress",
            recommended_action="Observe the same frontier.",
            delivery_batch_scale="single_surface",
            delivery_outcome="surface_only",
            agent_id=AGENT_ID,
            dry_run=False,
            sync_global=False,
        )
    assert state.read_text(encoding="utf-8") == before
    assert not list(runs_index.parent.glob("*.json"))


def test_rotated_vision_obligation_rejects_successor_only_delta() -> None:
    with pytest.raises(ValueError, match="required vision outcome"):
        enforce_open_replan_writeback(
            newest_first_runs=_rotated_vision_runs(),
            state_text=STATE_TEXT,
            agent_id=AGENT_ID,
            goal_id=GOAL_ID,
        )


def _state_with_replan_successor(
    obligation_id: str,
    *,
    status: str = "open",
) -> str:
    marker = " " if status == "open" else "x"
    return _completed_advancement_chain_state() + "\n" + "\n".join(
        [
            f"- [{marker}] [P0] Execute the newly selected bounded direction.",
            (
                "  <!-- loopx:todo todo_id=todo_rotated_replan_successor "
                f"status={status} task_class=advancement_task "
                f"claimed_by={AGENT_ID} "
                "action_kind=inspect target_key=surface%3Aselected-bounded-slice "
                f"replan_obligation_id={obligation_id} "
                "updated_at=2026-08-13T11%3A28%3A00%2B08%3A00 -->"
            ),
        ]
    ) + "\n"


def test_current_obligation_runnable_successor_is_the_semantic_receipt() -> None:
    """The #3155 vision/frontier duty closes without a second ACK ritual."""

    from loopx.control_plane.work_items.semantic_replan_writeback import (
        qualify_replan_writeback,
    )

    obligation, _ = qualify_replan_writeback(
        newest_first_runs=_rotated_vision_runs(),
        state_text=_completed_advancement_chain_state(),
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
    )
    assert obligation is not None

    after_transition, semantic_delta = qualify_replan_writeback(
        newest_first_runs=_rotated_vision_runs(),
        state_text=_state_with_replan_successor(obligation["obligation_id"]),
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
    )

    assert after_transition is None
    assert semantic_delta is None


def test_completed_or_wrong_obligation_successor_cannot_close_rotated_duty() -> None:
    from loopx.control_plane.work_items.semantic_replan_writeback import (
        qualify_replan_writeback,
    )

    for state_text in (
        _state_with_replan_successor("replan-0000000000000000"),
        _state_with_replan_successor(
            "replan-0000000000000000",
            status="done",
        ),
    ):
        obligation, semantic_delta = qualify_replan_writeback(
            newest_first_runs=_rotated_vision_runs(),
            state_text=state_text,
            agent_id=AGENT_ID,
            goal_id=GOAL_ID,
        )
        assert obligation is not None
        assert semantic_delta is not None
        assert semantic_delta["accepted"] is False


def test_rotated_vision_obligation_accepts_fresh_evidence_linked_path() -> None:
    semantic_delta = enforce_open_replan_writeback(
        newest_first_runs=_rotated_vision_runs(),
        state_text=_completed_advancement_chain_state(),
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
        agent_vision={
            "vision_patch": {
                "acceptance_summary": "Close the current outcome with evidence."
            },
            "path_delta": {
                "outcome": "replan",
                "evidence_refs": ["evidence:current-outcome"],
            },
        },
    )
    assert semantic_delta is not None
    assert semantic_delta["satisfying_outcomes"] == [
        "fresh_vision_path_outcome"
    ]


@pytest.mark.parametrize(
    ("progress_observation", "agent_vision", "expected_outcome"),
    [
        (
            {
                "schema_version": "typed_progress_observation_v0",
                "result_class": "blocked",
                "blocker_id": "blocker-current-path",
                "evidence_ids": ["evidence-current-blocker"],
            },
            None,
            "new_concrete_blocker",
        ),
        (
            {
                "schema_version": "typed_progress_observation_v0",
                "result_class": "exploration_exhausted",
                "coverage_scope_id": "coverage-current-goal",
                "coverage_complete": True,
                "evidence_ids": ["evidence-current-coverage"],
            },
            None,
            "coverage_backed_exploration_exhausted",
        ),
        (
            {
                "schema_version": "typed_progress_observation_v0",
                "result_class": "no_followup",
                "coverage_scope_id": "coverage-current-goal",
                "evidence_ids": ["evidence-current-coverage"],
            },
            _terminal_no_followup_vision(),
            "coverage_backed_no_followup",
        ),
    ],
)
def test_rotated_vision_obligation_accepts_terminal_progress(
    progress_observation: dict,
    agent_vision: dict | None,
    expected_outcome: str,
) -> None:
    runs = _rotated_vision_runs()
    state_text = _completed_advancement_chain_state()
    semantic_delta = enforce_open_replan_writeback(
        newest_first_runs=runs,
        state_text=state_text,
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
        progress_observation=progress_observation,
        agent_vision=agent_vision,
    )

    assert semantic_delta is not None
    assert semantic_delta["satisfying_outcomes"] == [expected_outcome]


def test_semantic_no_followup_cannot_replace_todo_lifecycle_settlement() -> None:
    with pytest.raises(ValueError, match="first run loopx todo complete"):
        enforce_open_replan_writeback(
            newest_first_runs=[],
            state_text=_completed_advancement_without_successor_state(),
            agent_id=AGENT_ID,
            goal_id=GOAL_ID,
            progress_observation={
                "schema_version": "typed_progress_observation_v0",
                "result_class": "no_followup",
                "coverage_scope_id": "coverage-current-goal",
                "evidence_ids": ["evidence-current-coverage"],
            },
            agent_vision=_terminal_no_followup_vision(),
        )


def test_persisted_semantic_no_followup_ack_cannot_retire_todo_gap() -> None:
    state_text = _completed_advancement_without_successor_state()
    obligation_id = _current_obligation_id([], state_text=state_text)
    semantic_ack = {
        "classification": "bounded_replan_terminal",
        "generated_at": "2026-08-13T12:00:00+08:00",
        "agent_id": AGENT_ID,
        "autonomous_replan_ack": {
            "schema_version": "autonomous_replan_ack_v0",
            "recorded": True,
            "source": "refresh_state_semantic_delta",
            "semantic_delta": {
                "schema_version": "replan_semantic_delta_v0",
                "accepted": True,
                "outcomes": ["coverage_backed_no_followup"],
                "satisfying_outcomes": ["coverage_backed_no_followup"],
                "required_any_of": ["coverage_backed_no_followup"],
                "obligation_id": obligation_id,
            },
        },
    }

    remaining, _ = qualify_replan_writeback(
        newest_first_runs=[semantic_ack],
        state_text=state_text,
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
    )

    assert remaining is not None
    assert remaining["triggers"][0]["kind"] == (
        "completed_advancement_without_successor"
    )
    assert "loopx todo complete --no-follow-up" in remaining["recommended_action"]
    assert "do not invent a user gate" in remaining["recommended_action"]


@pytest.mark.parametrize(
    "outcome",
    [
        "fresh_vision_path_outcome",
        "new_concrete_blocker",
        "coverage_backed_exploration_exhausted",
        "coverage_backed_no_followup",
    ],
)
def test_matching_non_successor_ack_clears_rotated_vision_obligation(
    outcome: str,
) -> None:
    runs = _rotated_vision_runs()
    state_text = _completed_advancement_chain_state()
    obligation_id = _current_obligation_id(runs, state_text=state_text)
    semantic_ack = {
        "classification": "bounded_replan_progress",
        "generated_at": "2026-08-13T12:00:00+08:00",
        "agent_id": AGENT_ID,
        "autonomous_replan_ack": {
            "schema_version": "autonomous_replan_ack_v0",
            "recorded": True,
            "source": "refresh_state_semantic_delta",
            "semantic_delta": {
                "schema_version": "replan_semantic_delta_v0",
                "accepted": True,
                "outcomes": [outcome],
                "satisfying_outcomes": [outcome],
                "required_any_of": [
                    "fresh_vision_path_outcome",
                    "new_runnable_successor",
                    "new_concrete_blocker",
                    "coverage_backed_exploration_exhausted",
                    "coverage_backed_no_followup",
                ],
                "obligation_id": obligation_id,
            },
        },
    }

    remaining, _ = qualify_replan_writeback(
        newest_first_runs=[semantic_ack, *runs],
        state_text=state_text,
        agent_id=AGENT_ID,
        goal_id=GOAL_ID,
    )

    assert remaining is None
