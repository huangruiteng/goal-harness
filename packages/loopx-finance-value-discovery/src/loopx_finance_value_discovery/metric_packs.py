from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .boundary import reject_forbidden_material
from .contract import validate_finance_case_input
from .replay import (
    build_finance_case_evaluation,
    canonical_json_bytes,
    canonical_sha256,
)

FINANCE_METRIC_PACK_INPUT_SCHEMA_VERSION = "finance_metric_pack_input_v1"
FINANCE_METRIC_PACK_EVALUATION_SCHEMA_VERSION = "finance_metric_pack_evaluation_v1"
FINANCE_METRIC_PACK_REPLAY_SCHEMA_VERSION = "finance_metric_pack_replay_v1"

COMMON_GATE_IDS = {
    "source_lineage",
    "point_in_time",
    "identity",
    "evidence_quality",
    "valuation",
    "terminal_risk",
}
REQUIRED_COMMON_GATE_RULES = (
    {
        "gate_id": "source_lineage",
        "value_type": "boolean",
        "operator": "eq",
        "reference_value": True,
    },
    {
        "gate_id": "point_in_time",
        "value_type": "boolean",
        "operator": "eq",
        "reference_value": True,
    },
)

_METRIC_PACKS: dict[str, dict[str, Any]] = {
    "software_platforms_v1": {
        "pack_id": "software_platforms_v1",
        "description": "Recurring software and platform economics.",
        "metrics": [
            {
                "metric_id": "recurring_revenue_growth",
                "value_type": "number",
                "allowed_operators": ["gt", "gte"],
            },
            {
                "metric_id": "gross_margin",
                "value_type": "number",
                "allowed_operators": ["gt", "gte"],
            },
            {
                "metric_id": "free_cash_flow_conversion",
                "value_type": "number",
                "allowed_operators": ["gt", "gte"],
            },
            {
                "metric_id": "sbc_dilution",
                "value_type": "number",
                "allowed_operators": ["lt", "lte"],
            },
        ],
    },
    "cyclical_industrials_v1": {
        "pack_id": "cyclical_industrials_v1",
        "description": "Cyclical industrial operating and balance-sheet quality.",
        "metrics": [
            {
                "metric_id": "organic_revenue_growth",
                "value_type": "number",
                "allowed_operators": ["gt", "gte"],
            },
            {
                "metric_id": "incremental_margin",
                "value_type": "number",
                "allowed_operators": ["gt", "gte"],
            },
            {
                "metric_id": "free_cash_flow_conversion",
                "value_type": "number",
                "allowed_operators": ["gt", "gte"],
            },
            {
                "metric_id": "net_debt_to_ebitda",
                "value_type": "number",
                "allowed_operators": ["lt", "lte"],
            },
        ],
    },
}


def list_finance_metric_packs() -> dict[str, Any]:
    return {
        "ok": True,
        "schema_version": "finance_metric_pack_catalog_v1",
        "packs": [
            deepcopy(_METRIC_PACKS[pack_id]) for pack_id in sorted(_METRIC_PACKS)
        ],
        "truth_contract": {
            "packs_define_metric_semantics": True,
            "case_contract_owns_thresholds": True,
            "common_engine_owns_missing_and_conflict": True,
            "human_owns_promotion": True,
        },
    }


def _metric_pack(pack_id: object) -> dict[str, Any]:
    if not isinstance(pack_id, str) or pack_id not in _METRIC_PACKS:
        raise ValueError(f"pack_id must be one of {sorted(_METRIC_PACKS)}")
    return deepcopy(_METRIC_PACKS[pack_id])


def _validate_pack_contract(
    pack: Mapping[str, Any],
    case_input: Mapping[str, Any],
) -> None:
    metrics = {
        str(item["metric_id"]): item
        for item in pack["metrics"]
        if isinstance(item, Mapping)
    }
    gates = case_input["contract"]["gates"]
    gate_order = [str(item["gate_id"]) for item in gates]
    required_gate_order = [str(item["gate_id"]) for item in REQUIRED_COMMON_GATE_RULES]
    if gate_order[: len(required_gate_order)] != required_gate_order:
        raise ValueError(
            "metric pack contract must begin with source_lineage then point_in_time"
        )
    if tuple(gates[: len(REQUIRED_COMMON_GATE_RULES)]) != REQUIRED_COMMON_GATE_RULES:
        raise ValueError(
            "metric pack source_lineage and point_in_time gates must use "
            "provider-neutral semantics"
        )
    gate_ids = {str(item["gate_id"]) for item in gates}
    unknown = gate_ids - COMMON_GATE_IDS - set(metrics)
    if unknown:
        raise ValueError(
            "metric pack contract has unsupported gate ids: "
            + ", ".join(sorted(unknown))
        )
    missing = set(metrics) - gate_ids
    if missing:
        raise ValueError(
            "metric pack contract is missing required metrics: "
            + ", ".join(sorted(missing))
        )
    for gate in gates:
        metric = metrics.get(str(gate["gate_id"]))
        if metric is None:
            continue
        if gate["value_type"] != metric["value_type"]:
            raise ValueError(
                f"metric {gate['gate_id']} must use value_type={metric['value_type']}"
            )
        if gate["operator"] not in metric["allowed_operators"]:
            raise ValueError(
                f"metric {gate['gate_id']} operator must be one of "
                f"{metric['allowed_operators']}"
            )


def build_finance_metric_pack_evaluation(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("finance metric pack input must be an object")
    reject_forbidden_material(value)
    allowed = {"schema_version", "pack_id", "case_input"}
    if set(value) - allowed:
        raise ValueError("finance metric pack input has unsupported fields")
    if value.get("schema_version") != FINANCE_METRIC_PACK_INPUT_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {FINANCE_METRIC_PACK_INPUT_SCHEMA_VERSION}"
        )
    pack = _metric_pack(value.get("pack_id"))
    raw_case_input = value.get("case_input")
    case_input = validate_finance_case_input(raw_case_input)
    _validate_pack_contract(pack, case_input)
    gate_evaluation = build_finance_case_evaluation(raw_case_input)
    evaluation = {
        "ok": True,
        "schema_version": FINANCE_METRIC_PACK_EVALUATION_SCHEMA_VERSION,
        "pack": pack,
        "case_evaluation": gate_evaluation,
        "disposition": gate_evaluation["disposition"],
        "boundary": gate_evaluation["boundary"],
    }
    replay = {
        "schema_version": FINANCE_METRIC_PACK_REPLAY_SCHEMA_VERSION,
        "input_sha256": canonical_sha256(value),
        "pack_sha256": canonical_sha256(pack),
        "evaluation_sha256": canonical_sha256(evaluation),
        "canonicalization": "json_sort_keys_compact_ascii_v1",
    }
    return {**evaluation, "replay": replay}


def replay_finance_metric_pack_evaluation(
    value: object,
    expected: object,
) -> dict[str, Any]:
    if not isinstance(expected, Mapping):
        raise ValueError("expected metric pack evaluation must be an object")
    replayed = build_finance_metric_pack_evaluation(value)
    expected_replay = expected.get("replay")
    if not isinstance(expected_replay, Mapping):
        raise ValueError("expected metric pack evaluation requires replay")
    for field in ("input_sha256", "pack_sha256", "evaluation_sha256"):
        if expected_replay.get(field) != replayed["replay"][field]:
            raise ValueError(f"replay {field} mismatch")
    if canonical_json_bytes(expected) != canonical_json_bytes(replayed):
        raise ValueError("replay metric pack evaluation bytes mismatch")
    return {
        "ok": True,
        "schema_version": FINANCE_METRIC_PACK_REPLAY_SCHEMA_VERSION,
        "replay_verified": True,
        "input_sha256": replayed["replay"]["input_sha256"],
        "pack_sha256": replayed["replay"]["pack_sha256"],
        "evaluation_sha256": replayed["replay"]["evaluation_sha256"],
    }
