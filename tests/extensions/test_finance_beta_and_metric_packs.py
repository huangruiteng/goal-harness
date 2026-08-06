from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = ROOT / "packages" / "loopx-finance-value-discovery"
EXTENSION_SRC = EXTENSION_ROOT / "src"
BETA_EXAMPLE = EXTENSION_ROOT / "examples" / "beta-attribution-v1.json"
PACK_EXAMPLE = EXTENSION_ROOT / "examples" / "software-metric-pack-v1.json"
sys.path.insert(0, str(EXTENSION_SRC))

from loopx_finance_value_discovery.attribution import (  # noqa: E402
    build_finance_beta_attribution,
    replay_finance_beta_attribution,
)
from loopx_finance_value_discovery.cli import run  # noqa: E402
from loopx_finance_value_discovery.metric_packs import (  # noqa: E402
    build_finance_metric_pack_evaluation,
    list_finance_metric_packs,
    replay_finance_metric_pack_evaluation,
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_complete_beta_attribution_computes_residual_and_replays() -> None:
    payload = _json(BETA_EXAMPLE)
    attribution = build_finance_beta_attribution(payload)

    assert attribution["schema_version"] == "finance_beta_attribution_v1"
    assert attribution["disposition"] == "eligible_for_research_successor"
    assert attribution["completeness"] == "complete"
    assert attribution["explained_sum"] == "-0.11"
    assert attribution["residual"] == "0.01"
    assert [item["component_id"] for item in attribution["components"]] == [
        "market",
        "rate",
        "sector",
        "narrow_peer",
        "cycle",
        "event",
        "residual",
    ]
    assert attribution["components"][-1]["observation_state"] == "computed"
    assert attribution["boundary"]["trading_allowed"] is False
    assert attribution["boundary"]["automatic_promotion_allowed"] is False
    assert (
        replay_finance_beta_attribution(payload, attribution)["replay_verified"] is True
    )


@pytest.mark.parametrize("state", ["missing", "conflict"])
def test_incomplete_beta_components_never_fabricate_a_residual(state: str) -> None:
    payload = _json(BETA_EXAMPLE)
    component = payload["components"][3]
    component["observation_state"] = state
    component["contribution"] = None
    component["evidence_refs"] = (
        [] if state == "missing" else ["peer-source-a", "peer-source-b"]
    )
    component["reason"] = "The narrow-peer contribution is not resolved."
    blocked = False
    for observation in payload["gate_evaluation_input"]["observations"]:
        if observation["gate_id"] == "de_beta_residual":
            observation.update(
                {
                    "observation_state": state,
                    "value": None,
                    "evidence_refs": (
                        []
                        if state == "missing"
                        else ["residual-source-a", "residual-source-b"]
                    ),
                    "reason": "The residual is not resolved.",
                }
            )
            blocked = True
        elif blocked:
            observation.update(
                {
                    "observation_state": "not_run",
                    "value": None,
                    "evidence_refs": [],
                    "reason": "Not run after the unresolved residual gate.",
                }
            )

    attribution = build_finance_beta_attribution(payload)

    assert attribution["disposition"] == "insufficient_evidence"
    assert attribution["completeness"] == "insufficient_evidence"
    assert attribution["explained_sum"] is None
    assert attribution["residual"] is None
    assert attribution["components"][-1]["observation_state"] == "not_computable"
    field = (
        "missing_component_ids" if state == "missing" else "conflicting_component_ids"
    )
    assert attribution[field] == ["narrow_peer"]


def test_beta_component_order_and_replay_input_are_frozen() -> None:
    payload = _json(BETA_EXAMPLE)
    expected = build_finance_beta_attribution(payload)

    reordered = deepcopy(payload)
    reordered["components"][0], reordered["components"][1] = (
        reordered["components"][1],
        reordered["components"][0],
    )
    with pytest.raises(ValueError, match="exactly match"):
        build_finance_beta_attribution(reordered)

    mutated = deepcopy(payload)
    mutated["components"][0]["contribution"] = -0.05
    residual_observation = next(
        observation
        for observation in mutated["gate_evaluation_input"]["observations"]
        if observation["gate_id"] == "de_beta_residual"
    )
    residual_observation["value"] = 0.02
    with pytest.raises(ValueError, match="replay"):
        replay_finance_beta_attribution(mutated, expected)


def test_software_pack_adds_semantics_but_contract_owns_thresholds() -> None:
    payload = _json(PACK_EXAMPLE)
    evaluation = build_finance_metric_pack_evaluation(payload)

    assert evaluation["schema_version"] == "finance_metric_pack_evaluation_v1"
    assert evaluation["pack"]["pack_id"] == "software_platforms_v1"
    assert evaluation["disposition"] == "rejected"
    assert (
        evaluation["case_evaluation"]["first_blocking_gate"]["gate_id"]
        == "sbc_dilution"
    )
    contract_gate = evaluation["case_evaluation"]["contract"]["gates"][-1]
    assert contract_gate["reference_value"] == 0.04
    assert "reference_value" not in evaluation["pack"]["metrics"][-1]
    assert evaluation["boundary"]["automatic_promotion_allowed"] is False
    assert (
        replay_finance_metric_pack_evaluation(payload, evaluation)["replay_verified"]
        is True
    )


def test_metric_pack_catalog_is_deterministic_and_not_mutable_by_callers() -> None:
    first = list_finance_metric_packs()
    assert [item["pack_id"] for item in first["packs"]] == [
        "cyclical_industrials_v1",
        "software_platforms_v1",
    ]
    first["packs"][0]["metrics"][0]["metric_id"] = "tampered"

    second = list_finance_metric_packs()
    assert second["packs"][0]["metrics"][0]["metric_id"] == ("organic_revenue_growth")


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["case_input"]["contract"]["gates"].append(
                {
                    "gate_id": "provider_owned_threshold",
                    "value_type": "number",
                    "operator": "gte",
                    "reference_value": 1,
                }
            ),
            "unsupported gate ids",
        ),
        (
            lambda payload: (
                payload["case_input"]["contract"]["gates"].pop(2),
                payload["case_input"]["observations"].pop(2),
            ),
            "missing required metrics",
        ),
        (
            lambda payload: payload["case_input"]["contract"]["gates"][2].update(
                {"operator": "lte"}
            ),
            "operator must be one of",
        ),
    ],
)
def test_metric_pack_rejects_contract_drift(mutator, message: str) -> None:
    payload = _json(PACK_EXAMPLE)
    mutator(payload)
    with pytest.raises(ValueError, match=message):
        build_finance_metric_pack_evaluation(payload)


def test_metric_pack_requires_frozen_source_and_cutoff_prefix() -> None:
    missing_source = _json(PACK_EXAMPLE)
    missing_source["case_input"]["contract"]["gates"].pop(0)
    missing_source["case_input"]["observations"].pop(0)
    with pytest.raises(ValueError, match="must begin with source_lineage"):
        build_finance_metric_pack_evaluation(missing_source)

    reordered = _json(PACK_EXAMPLE)
    reordered["case_input"]["contract"]["gates"][0:2] = reversed(
        reordered["case_input"]["contract"]["gates"][0:2]
    )
    reordered["case_input"]["observations"][0:2] = reversed(
        reordered["case_input"]["observations"][0:2]
    )
    with pytest.raises(ValueError, match="must begin with source_lineage"):
        build_finance_metric_pack_evaluation(reordered)


@pytest.mark.parametrize(
    ("gate_id", "rule", "observed_value"),
    [
        (
            "source_lineage",
            {
                "value_type": "string",
                "operator": "eq",
                "reference_value": "provider-verified",
            },
            "provider-verified",
        ),
        (
            "point_in_time",
            {
                "value_type": "number",
                "operator": "gte",
                "reference_value": 1,
            },
            1,
        ),
        (
            "point_in_time",
            {
                "value_type": "boolean",
                "operator": "eq",
                "reference_value": False,
            },
            False,
        ),
    ],
)
def test_metric_pack_common_gates_reject_provider_semantic_drift(
    gate_id: str,
    rule: dict[str, object],
    observed_value: object,
) -> None:
    payload = _json(PACK_EXAMPLE)
    gate_index = next(
        index
        for index, gate in enumerate(payload["case_input"]["contract"]["gates"])
        if gate["gate_id"] == gate_id
    )
    payload["case_input"]["contract"]["gates"][gate_index].update(rule)
    payload["case_input"]["observations"][gate_index]["value"] = observed_value

    with pytest.raises(ValueError, match="provider-neutral semantics"):
        build_finance_metric_pack_evaluation(payload)


def test_cyclical_industrials_pack_uses_the_common_gate_engine() -> None:
    payload = _json(PACK_EXAMPLE)
    payload["pack_id"] = "cyclical_industrials_v1"
    metrics = [
        ("organic_revenue_growth", "gte", 0.03, 0.05),
        ("incremental_margin", "gte", 0.1, 0.12),
        ("free_cash_flow_conversion", "gte", 0.7, 0.8),
        ("net_debt_to_ebitda", "lte", 2.5, 1.9),
    ]
    payload["case_input"]["contract"]["gates"] = payload["case_input"]["contract"][
        "gates"
    ][:2]
    payload["case_input"]["observations"] = payload["case_input"]["observations"][:2]
    for metric_id, operator, threshold, observed_value in metrics:
        payload["case_input"]["contract"]["gates"].append(
            {
                "gate_id": metric_id,
                "value_type": "number",
                "operator": operator,
                "reference_value": threshold,
            }
        )
        payload["case_input"]["observations"].append(
            {
                "gate_id": metric_id,
                "observation_state": "observed",
                "value": observed_value,
                "evidence_refs": [f"{metric_id}-filing"],
                "reason": "Frozen public filing observation.",
            }
        )

    evaluation = build_finance_metric_pack_evaluation(payload)

    assert evaluation["disposition"] == "eligible_for_research_successor"
    assert evaluation["case_evaluation"]["first_blocking_gate"] is None


def test_direct_cli_beta_pack_and_catalog(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["attribute-beta", "--input-json", str(BETA_EXAMPLE)]) == 0
    beta = json.loads(capsys.readouterr().out)
    expected_beta = tmp_path / "beta.json"
    expected_beta.write_text(json.dumps(beta), encoding="utf-8")
    assert (
        run(
            [
                "replay-beta",
                "--input-json",
                str(BETA_EXAMPLE),
                "--expected-json",
                str(expected_beta),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["replay_verified"] is True

    assert run(["evaluate-pack", "--input-json", str(PACK_EXAMPLE)]) == 0
    pack = json.loads(capsys.readouterr().out)
    expected_pack = tmp_path / "pack.json"
    expected_pack.write_text(json.dumps(pack), encoding="utf-8")
    assert (
        run(
            [
                "replay-pack",
                "--input-json",
                str(PACK_EXAMPLE),
                "--expected-json",
                str(expected_pack),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["replay_verified"] is True

    assert run(["list-packs"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["truth_contract"][
            "case_contract_owns_thresholds"
        ]
        is True
    )


def _fail_gate_evaluation_input(payload: dict) -> dict:
    """Flip the bound gate case into a failing/blocking disposition.

    evidence_quality becomes the first blocking gate; every gate after it must
    be not_run, while earlier gates keep their passing observation.
    """
    gei = payload["gate_evaluation_input"]
    blocked = False
    for obs in gei["observations"]:
        if obs["gate_id"] == "evidence_quality":
            obs.update(
                {
                    "observation_state": "missing",
                    "value": None,
                    "evidence_refs": [],
                    "reason": "Evidence quality gate is unresolved.",
                }
            )
            blocked = True
        elif blocked:
            obs.update(
                {"observation_state": "not_run", "value": None, "evidence_refs": []}
            )
    return payload


def test_attribution_cannot_be_reused_under_another_case() -> None:
    payload = _json(BETA_EXAMPLE)
    payload["case_reference"]["case_id"] = "some-other-case"
    with pytest.raises(ValueError, match="case_id must match"):
        build_finance_beta_attribution(payload)


def test_attribution_cannot_be_reused_for_another_subject() -> None:
    # Keeping the passing case_id but swapping the subject to a different
    # security must not reuse the gate pass as research-complete.
    payload = _json(BETA_EXAMPLE)
    payload["case_reference"]["subject_ref"] = "unrelated-security-XYZ"
    with pytest.raises(ValueError, match="subject_ref must match"):
        build_finance_beta_attribution(payload)


@pytest.mark.parametrize(
    ("window", "match"),
    [
        ({"start": "not-a-date", "end": "2026-07-27"}, "start must be an ISO-8601"),
        ({"start": "2026-07-23", "end": "still-not-a-date"}, "end must be an ISO-8601"),
        ({"start": "2999-01-01", "end": "2999-12-31"}, "end must not exceed"),
        ({"start": "2020-01-01", "end": "2026-07-27"}, "start must not precede"),
        ({"start": "2026-07-27", "end": "2026-07-23"}, "start must not be after end"),
    ],
)
def test_attribution_rejects_invalid_or_out_of_window_observation(
    window: dict[str, str],
    match: str,
) -> None:
    # observation_window must be real ISO dates inside the contract's frozen
    # [point_in_time, evaluation_as_of] window; not-a-date and future windows
    # cannot be presented as research-complete.
    payload = _json(BETA_EXAMPLE)
    payload["case_reference"]["observation_window"] = window
    with pytest.raises(ValueError, match=match):
        build_finance_beta_attribution(payload)


def test_attribution_rejects_offset_aware_observation_after_cutoff() -> None:
    payload = _json(BETA_EXAMPLE)
    payload["case_reference"]["observation_window"] = {
        "start": "2026-07-27T23:00:00-04:00",
        "end": "2026-07-27T23:30:00-04:00",
    }
    payload["gate_evaluation_input"]["contract"]["point_in_time"] = (
        "2026-07-28T03:00:00Z"
    )
    payload["gate_evaluation_input"]["contract"]["evaluation_as_of"] = (
        "2026-07-28T03:15:00Z"
    )

    with pytest.raises(ValueError, match="end must not exceed"):
        build_finance_beta_attribution(payload)


def test_gate_input_requires_subject_ref() -> None:
    payload = _json(BETA_EXAMPLE)
    del payload["gate_evaluation_input"]["subject_ref"]
    with pytest.raises(ValueError, match="subject_ref is required"):
        build_finance_beta_attribution(payload)


def test_attribution_rejects_residual_gate_value_that_disagrees_with_arithmetic() -> (
    None
):
    payload = _json(BETA_EXAMPLE)
    payload["total_move"] = -0.1
    residual_observation = next(
        observation
        for observation in payload["gate_evaluation_input"]["observations"]
        if observation["gate_id"] == "de_beta_residual"
    )
    residual_observation["value"] = 0.18

    with pytest.raises(ValueError, match="must match the computed residual"):
        build_finance_beta_attribution(payload)


def test_failed_gate_preserves_rejection_separate_from_component_completeness() -> None:
    payload = _json(BETA_EXAMPLE)
    blocked = False
    for observation in payload["gate_evaluation_input"]["observations"]:
        if observation["gate_id"] == "evidence_quality":
            observation["value"] = 1
            observation["reason"] = "Observed evidence fails the frozen threshold."
            blocked = True
        elif blocked:
            observation.update(
                {
                    "observation_state": "not_run",
                    "value": None,
                    "evidence_refs": [],
                    "reason": "Not run after the failed evidence-quality gate.",
                }
            )

    attribution = build_finance_beta_attribution(payload)

    assert attribution["disposition"] == "rejected"
    assert attribution["completeness"] == "complete"
    assert attribution["residual"] == "0.01"


def test_missing_gate_cannot_be_presented_as_research_complete() -> None:
    payload = _fail_gate_evaluation_input(_json(BETA_EXAMPLE))
    attribution = build_finance_beta_attribution(payload)

    # Even with all six components observed, missing gate evidence keeps the
    # attribution incomplete without hiding the deterministic arithmetic.
    assert attribution["gate_eligible"] is False
    assert attribution["disposition"] == "insufficient_evidence"
    assert attribution["completeness"] == "insufficient_evidence"
    assert attribution["residual"] == "0.01"
    assert (
        attribution["gate_evaluation_receipt"]["disposition"] == "insufficient_evidence"
    )


def test_attribution_binds_case_reference_and_gate_receipt() -> None:
    payload = _json(BETA_EXAMPLE)
    attribution = build_finance_beta_attribution(payload)

    assert (
        attribution["case_reference"]["case_id"]
        == (payload["gate_evaluation_input"]["case_id"])
    )
    assert attribution["gate_evaluation_receipt"]["gate_eligible"] is True
    assert attribution["gate_evaluation_receipt"]["evaluation_sha256"]
