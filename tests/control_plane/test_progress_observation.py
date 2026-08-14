from __future__ import annotations

import pytest

from loopx.control_plane.work_items.progress_observation import (
    build_replan_action_packet,
    build_replan_context,
    normalize_progress_observation,
    semantic_progress_delta,
    typed_progress_repeat_trigger,
)

AGENT_ID = "codex-progress-agent"


def _observation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "typed_progress_observation_v0",
        "work_item_id": "todo-progress",
        "surface_id": "surface-auth",
        "hypothesis_id": "hypothesis-boundary",
        "probe_kind": "probe-route-map",
        "result_class": "unchanged",
        "evidence_ids": ["evidence-route-map"],
    }
    value.update(overrides)
    return value


def _run(generated_at: str, observation: dict[str, object]) -> dict[str, object]:
    return {
        "generated_at": generated_at,
        "agent_id": AGENT_ID,
        "progress_observation": normalize_progress_observation(observation),
    }


def test_normalization_rejects_prose_in_semantic_identifiers() -> None:
    with pytest.raises(ValueError, match="opaque"):
        normalize_progress_observation(
            _observation(surface_id="look at the same route again")
        )


def test_two_equivalent_typed_observations_trigger_replan_without_text() -> None:
    runs = [
        _run("2026-08-13T01:01:00Z", _observation()),
        _run("2026-08-13T01:00:00Z", _observation()),
    ]

    trigger = typed_progress_repeat_trigger(runs, agent_id=AGENT_ID)

    assert trigger is not None
    assert trigger["kind"] == "typed_progress_repeat"
    assert trigger["run_count"] == 2
    assert trigger["progress_baseline"]["surface_id"] == "surface-auth"


def test_text_changes_cannot_hide_an_equivalent_typed_repeat() -> None:
    runs = [
        {
            **_run("2026-08-13T01:01:00Z", _observation()),
            "classification": "completely_different_words",
            "recommended_action": "Use new wording.",
        },
        {
            **_run("2026-08-13T01:00:00Z", _observation()),
            "classification": "source_audit_progress",
            "recommended_action": "Repeat old wording.",
        },
    ]

    assert typed_progress_repeat_trigger(runs, agent_id=AGENT_ID) is not None


def test_new_probe_family_is_a_semantic_delta_but_new_evidence_alone_is_not() -> None:
    baseline = normalize_progress_observation(_observation())
    new_probe = normalize_progress_observation(
        _observation(result_class="advanced", probe_kind="probe-permission-graph")
    )
    evidence_only = normalize_progress_observation(
        _observation(
            result_class="advanced",
            evidence_ids=["evidence-new-output"],
        )
    )

    assert semantic_progress_delta(new_probe, baseline=baseline)["delta_kinds"] == [
        "new_probe_family"
    ]
    assert semantic_progress_delta(evidence_only, baseline=baseline)["accepted"] is False


def test_repeated_blocker_cannot_close_replan() -> None:
    baseline = normalize_progress_observation(
        _observation(
            result_class="blocked",
            blocker_id="blocker-permission",
        )
    )
    repeated = normalize_progress_observation(
        _observation(
            result_class="blocked",
            blocker_id="blocker-permission",
        )
    )
    novel = normalize_progress_observation(
        _observation(
            result_class="blocked",
            blocker_id="blocker-missing-runtime",
        )
    )

    assert semantic_progress_delta(repeated, baseline=baseline)["accepted"] is False
    assert semantic_progress_delta(novel, baseline=baseline)["delta_kinds"] == [
        "new_concrete_blocker"
    ]


def test_exhaustion_requires_coverage_proof() -> None:
    incomplete = normalize_progress_observation(
        _observation(
            result_class="exploration_exhausted",
            coverage_scope_id="scope-public-entrypoints",
            coverage_complete=False,
        )
    )
    complete = normalize_progress_observation(
        _observation(
            result_class="exploration_exhausted",
            coverage_scope_id="scope-public-entrypoints",
            coverage_complete=True,
        )
    )

    assert semantic_progress_delta(incomplete, baseline=None)["accepted"] is False
    assert semantic_progress_delta(complete, baseline=None)["delta_kinds"] == [
        "coverage_backed_exploration_exhausted"
    ]
    assert semantic_progress_delta(complete, baseline=incomplete)["delta_kinds"] == [
        "coverage_backed_exploration_exhausted"
    ]


@pytest.mark.parametrize(
    ("result_class", "terminal_fields", "delta_kind"),
    [
        (
            "exploration_exhausted",
            {"coverage_complete": True},
            "coverage_backed_exploration_exhausted",
        ),
        (
            "no_followup",
            {},
            "coverage_backed_no_followup",
        ),
    ],
)
def test_terminal_coverage_requires_a_semantically_new_scope(
    result_class: str,
    terminal_fields: dict[str, object],
    delta_kind: str,
) -> None:
    baseline = normalize_progress_observation(
        _observation(
            result_class=result_class,
            coverage_scope_id="scope-public-entrypoints",
            **terminal_fields,
        )
    )
    repeated = normalize_progress_observation(dict(baseline))
    evidence_only = normalize_progress_observation(
        _observation(
            result_class=result_class,
            coverage_scope_id="scope-public-entrypoints",
            evidence_ids=["evidence-new-output"],
            **terminal_fields,
        )
    )
    new_scope = normalize_progress_observation(
        _observation(
            result_class=result_class,
            coverage_scope_id="scope-public-cli",
            **terminal_fields,
        )
    )

    assert baseline["fingerprint"] == repeated["fingerprint"]
    assert baseline["fingerprint"] != evidence_only["fingerprint"]
    assert semantic_progress_delta(repeated, baseline=baseline)["accepted"] is False
    assert (
        semantic_progress_delta(evidence_only, baseline=baseline)["accepted"] is False
    )
    assert semantic_progress_delta(new_scope, baseline=baseline)["delta_kinds"] == [
        delta_kind
    ]


def test_terminal_result_class_change_is_a_semantic_delta() -> None:
    baseline = normalize_progress_observation(
        _observation(
            result_class="exploration_exhausted",
            coverage_scope_id="scope-public-entrypoints",
            coverage_complete=True,
        )
    )
    no_followup = normalize_progress_observation(
        _observation(
            result_class="no_followup",
            coverage_scope_id="scope-public-entrypoints",
        )
    )

    assert semantic_progress_delta(no_followup, baseline=baseline)["delta_kinds"] == [
        "coverage_backed_no_followup"
    ]


def test_no_followup_ignores_coverage_complete_churn() -> None:
    baseline = normalize_progress_observation(
        _observation(
            result_class="no_followup",
            coverage_scope_id="scope-public-entrypoints",
            coverage_complete=False,
        )
    )
    coverage_flag_only = normalize_progress_observation(
        _observation(
            result_class="no_followup",
            coverage_scope_id="scope-public-entrypoints",
            coverage_complete=True,
        )
    )

    assert (
        semantic_progress_delta(coverage_flag_only, baseline=baseline)["accepted"]
        is False
    )


def test_host_projects_evidence_context_and_minimal_action_packet() -> None:
    runs = [
        _run("2026-08-13T01:01:00Z", _observation()),
        _run("2026-08-13T01:00:00Z", _observation()),
    ]
    trigger = typed_progress_repeat_trigger(runs, agent_id=AGENT_ID)
    assert trigger is not None
    obligation = {
        "obligation_id": "replan-0123456789abcdef",
        "triggers": [trigger],
    }

    context = build_replan_context(
        obligation,
        goal_id="goal-progress",
        agent_id=AGENT_ID,
        newest_first_runs=runs,
    )
    enriched = {**obligation, "replan_context": context}
    packet = build_replan_action_packet(enriched)

    assert context["evidence_source"] == "agent_scoped_evidence_log"
    assert context["delivery"] == "host_projected"
    assert context["delivery_receipt"]["status"] == "delivered"
    assert context["coverage_ledger"][0]["fingerprint"] == trigger[
        "progress_fingerprint"
    ]
    assert set(packet) == {
        "schema_version",
        "decision",
        "obligation_id",
        "uncovered_frontier",
        "required_outcome",
        "writeback_contract",
        "allowed_terminal",
    }
    assert packet["writeback_contract"] == {}
    assert packet["allowed_terminal"] == [
        "exploration_exhausted",
        "blocked",
        "no_followup",
    ]
