from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .boundary import reject_forbidden_material
from .contract import iso_comparable_datetime, validate_iso_date
from .gates import evaluate_finance_case_gates
from .replay import canonical_json_bytes, canonical_sha256

FINANCE_BETA_ATTRIBUTION_INPUT_SCHEMA_VERSION = "finance_beta_attribution_input_v1"
FINANCE_BETA_ATTRIBUTION_SCHEMA_VERSION = "finance_beta_attribution_v1"
FINANCE_BETA_ATTRIBUTION_REPLAY_SCHEMA_VERSION = "finance_beta_attribution_replay_v1"

EXPLAINED_BETA_COMPONENTS = (
    "market",
    "rate",
    "sector",
    "narrow_peer",
    "cycle",
    "event",
)
ATTRIBUTION_STATES = {"observed", "missing", "conflict"}


def _text(value: object, *, field: str, limit: int = 320) -> str:
    result = " ".join(str(value or "").split())
    if not result:
        raise ValueError(f"{field} is required")
    if len(result) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    reject_forbidden_material(result, path=field)
    return result


def _decimal(value: object, *, field: str) -> Decimal:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return result


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _evidence_refs(value: object, *, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{field} must be a list")
    if len(value) > 12:
        raise ValueError(f"{field} must contain at most 12 items")
    refs = [
        _text(item, field=f"{field}[{index}]", limit=120)
        for index, item in enumerate(value)
    ]
    if len(refs) != len(set(refs)):
        raise ValueError(f"{field} must use unique evidence refs")
    return refs


def _component(value: object, *, index: int) -> dict[str, Any]:
    field = f"components[{index}]"
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    allowed = {
        "component_id",
        "observation_state",
        "contribution",
        "evidence_refs",
        "reason",
    }
    if set(value) - allowed:
        raise ValueError(f"{field} has unsupported fields")
    state = _text(
        value.get("observation_state"),
        field=f"{field}.observation_state",
        limit=24,
    )
    if state not in ATTRIBUTION_STATES:
        raise ValueError(
            f"{field}.observation_state must be one of {sorted(ATTRIBUTION_STATES)}"
        )
    contribution = value.get("contribution")
    if state == "observed":
        normalized_contribution = _decimal(contribution, field=f"{field}.contribution")
    else:
        if contribution is not None:
            raise ValueError(f"{field}.contribution is only valid when state=observed")
        normalized_contribution = None
    refs = _evidence_refs(value.get("evidence_refs"), field=f"{field}.evidence_refs")
    if state == "observed" and not refs:
        raise ValueError(f"{field} observed contributions require evidence_refs")
    if state == "conflict" and len(refs) < 2:
        raise ValueError(f"{field} conflicts require at least two evidence_refs")
    return {
        "component_id": _text(
            value.get("component_id"), field=f"{field}.component_id", limit=40
        ),
        "observation_state": state,
        "contribution": (
            _decimal_text(normalized_contribution)
            if normalized_contribution is not None
            else None
        ),
        "evidence_refs": refs,
        "reason": _text(value.get("reason"), field=f"{field}.reason"),
    }


def _case_reference(value: object) -> dict[str, Any]:
    """Validate the case/subject identity an attribution claims to explain."""
    if not isinstance(value, Mapping):
        raise ValueError("case_reference must be an object")
    allowed = {"case_id", "subject_ref", "observation_window"}
    if set(value) - allowed:
        raise ValueError("case_reference has unsupported fields")
    window = value.get("observation_window")
    if not isinstance(window, Mapping) or set(window) - {"start", "end"}:
        raise ValueError("case_reference.observation_window must have start and end")
    start = validate_iso_date(
        window.get("start"),
        field="case_reference.observation_window.start",
    )
    end = validate_iso_date(
        window.get("end"),
        field="case_reference.observation_window.end",
    )
    if iso_comparable_datetime(start) > iso_comparable_datetime(end):
        raise ValueError(
            "case_reference.observation_window.start must not be after end"
        )
    return {
        "case_id": _text(
            value.get("case_id"),
            field="case_reference.case_id",
            limit=96,
        ),
        "subject_ref": _text(
            value.get("subject_ref"), field="case_reference.subject_ref", limit=96
        ),
        "observation_window": {
            "start": start,
            "end": end,
        },
    }


def build_finance_beta_attribution(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("finance beta attribution input must be an object")
    reject_forbidden_material(value)
    allowed = {
        "schema_version",
        "attribution_id",
        "attribution_model_id",
        "component_order_frozen",
        "unit",
        "case_reference",
        "gate_evaluation_input",
        "total_move",
        "components",
    }
    if set(value) - allowed:
        raise ValueError("finance beta attribution input has unsupported fields")
    if value.get("schema_version") != FINANCE_BETA_ATTRIBUTION_INPUT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {FINANCE_BETA_ATTRIBUTION_INPUT_SCHEMA_VERSION}"
        )
    if value.get("component_order_frozen") is not True:
        raise ValueError("component_order_frozen must be true")
    if value.get("unit") != "return_fraction":
        raise ValueError("unit must be return_fraction")
    case_reference = _case_reference(value.get("case_reference"))
    # Evaluate the gate contract this attribution is bound to, so a failing or
    # missing gate cannot be presented as a research-complete attribution.
    gate_evaluation = evaluate_finance_case_gates(value.get("gate_evaluation_input"))
    contract = gate_evaluation["contract"]
    if gate_evaluation["case_id"] != case_reference["case_id"]:
        raise ValueError(
            "case_reference.case_id must match gate_evaluation_input.case_id"
        )
    if gate_evaluation["subject_ref"] != case_reference["subject_ref"]:
        raise ValueError(
            "case_reference.subject_ref must match gate_evaluation_input.subject_ref"
        )
    # Bind the observation window to the contract's frozen evaluation window so a
    # not-a-date or future window cannot be presented as research-complete. The
    # window must sit within [point_in_time, evaluation_as_of].
    window_start = iso_comparable_datetime(
        case_reference["observation_window"]["start"]
    )
    window_end = iso_comparable_datetime(case_reference["observation_window"]["end"])
    contract_start = iso_comparable_datetime(contract["point_in_time"])
    contract_cutoff = iso_comparable_datetime(contract["evaluation_as_of"])
    if window_start < contract_start:
        raise ValueError(
            "case_reference.observation_window.start must not precede "
            "contract.point_in_time"
        )
    if window_end > contract_cutoff:
        raise ValueError(
            "case_reference.observation_window.end must not exceed "
            "contract.evaluation_as_of"
        )
    gate_disposition = gate_evaluation["disposition"]
    gate_eligible = gate_disposition == "eligible_for_research_successor"
    total_move = _decimal(value.get("total_move"), field="total_move")
    raw_components = value.get("components")
    if not isinstance(raw_components, Sequence) or isinstance(
        raw_components, (str, bytes, bytearray)
    ):
        raise ValueError("components must be a list")
    components = [
        _component(item, index=index) for index, item in enumerate(raw_components)
    ]
    component_ids = [item["component_id"] for item in components]
    if component_ids != list(EXPLAINED_BETA_COMPONENTS):
        raise ValueError(
            "components must exactly match the frozen market/rate/sector/"
            "narrow_peer/cycle/event order"
        )

    missing = [
        item["component_id"]
        for item in components
        if item["observation_state"] == "missing"
    ]
    conflicts = [
        item["component_id"]
        for item in components
        if item["observation_state"] == "conflict"
    ]
    components_complete = not missing and not conflicts
    explained = (
        sum(
            (
                Decimal(str(item["contribution"]))
                for item in components
                if item["contribution"] is not None
            ),
            Decimal(0),
        )
        if components_complete
        else None
    )
    residual = total_move - explained if explained is not None else None
    residual_gate = next(
        (
            item
            for item in gate_evaluation["gate_results"]
            if item["gate_id"] == "de_beta_residual"
        ),
        None,
    )
    if residual_gate is None:
        raise ValueError("gate_evaluation_input must include the de_beta_residual gate")
    if residual_gate["observation_state"] == "observed":
        if residual is None:
            raise ValueError(
                "de_beta_residual cannot be observed while components are incomplete"
            )
        observed_residual = _decimal(
            residual_gate["value"],
            field="de_beta_residual observation",
        )
        if observed_residual != residual:
            raise ValueError(
                "de_beta_residual observation must match the computed residual"
            )
    completeness = (
        "complete"
        if components_complete and gate_disposition != "insufficient_evidence"
        else "insufficient_evidence"
    )
    attribution = {
        "ok": True,
        "schema_version": FINANCE_BETA_ATTRIBUTION_SCHEMA_VERSION,
        "attribution_id": _text(
            value.get("attribution_id"), field="attribution_id", limit=96
        ),
        "attribution_model_id": _text(
            value.get("attribution_model_id"),
            field="attribution_model_id",
            limit=96,
        ),
        "contract": contract,
        "case_reference": case_reference,
        "gate_evaluation_receipt": {
            "case_id": gate_evaluation["case_id"],
            "disposition": gate_evaluation["disposition"],
            "gate_eligible": gate_eligible,
            "first_blocking_gate": gate_evaluation["first_blocking_gate"],
            "evaluation_sha256": canonical_sha256(gate_evaluation),
        },
        "unit": "return_fraction",
        "total_move": _decimal_text(total_move),
        "components": components
        + [
            {
                "component_id": "residual",
                "observation_state": (
                    "computed" if components_complete else "not_computable"
                ),
                "contribution": _decimal_text(residual)
                if residual is not None
                else None,
                "evidence_refs": [],
                "reason": (
                    "Computed as total_move minus all six explained components."
                    if components_complete
                    else (
                        "Residual is unavailable while an explained component "
                        "is missing or conflicting."
                    )
                ),
            }
        ],
        "explained_sum": _decimal_text(explained) if explained is not None else None,
        "residual": _decimal_text(residual) if residual is not None else None,
        "disposition": gate_disposition,
        "completeness": completeness,
        "gate_eligible": gate_eligible,
        "missing_component_ids": missing,
        "conflicting_component_ids": conflicts,
        "boundary": {
            "public_evidence_only_state": contract["public_evidence_only_state"],
            "outcome_blind_state": contract["outcome_blind_state"],
            "investment_advice": False,
            "trading_allowed": False,
            "automatic_promotion_allowed": False,
        },
    }
    replay = {
        "schema_version": FINANCE_BETA_ATTRIBUTION_REPLAY_SCHEMA_VERSION,
        "contract_sha256": canonical_sha256(contract),
        "input_sha256": canonical_sha256(value),
        "attribution_sha256": canonical_sha256(attribution),
        "canonicalization": "json_sort_keys_compact_ascii_v1",
    }
    return {**attribution, "replay": replay}


def replay_finance_beta_attribution(
    value: object,
    expected: object,
) -> dict[str, Any]:
    if not isinstance(expected, Mapping):
        raise ValueError("expected attribution must be an object")
    replayed = build_finance_beta_attribution(value)
    expected_replay = expected.get("replay")
    if not isinstance(expected_replay, Mapping):
        raise ValueError("expected attribution requires a replay receipt")
    for field in ("contract_sha256", "input_sha256", "attribution_sha256"):
        if expected_replay.get(field) != replayed["replay"][field]:
            raise ValueError(f"replay {field} mismatch")
    if canonical_json_bytes(expected) != canonical_json_bytes(replayed):
        raise ValueError("replay attribution bytes mismatch")
    return {
        "ok": True,
        "schema_version": FINANCE_BETA_ATTRIBUTION_REPLAY_SCHEMA_VERSION,
        "replay_verified": True,
        "contract_sha256": replayed["replay"]["contract_sha256"],
        "input_sha256": replayed["replay"]["input_sha256"],
        "attribution_sha256": replayed["replay"]["attribution_sha256"],
    }
