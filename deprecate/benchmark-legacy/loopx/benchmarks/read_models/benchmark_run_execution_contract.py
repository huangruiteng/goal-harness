from __future__ import annotations

from typing import Any

from ...control_plane.runtime.public_safety import (
    public_safe_compact_list,
    public_safe_compact_text,
)


def compact_benchmark_run_execution_contract(
    source: dict[str, Any],
    *,
    max_list_items: int,
) -> dict[str, Any]:
    sections = (
        (
            "benchmark_loop_contract",
            _compact_fields(
                source.get("benchmark_loop_contract"),
                text_fields=(
                    "schema_version",
                    "route",
                    "protocol_id",
                    "claim_blocker",
                ),
                bool_fields=(
                    "official_feedback_forwarded",
                    "official_feedback_blinded",
                    "blind_loop",
                    "product_mode",
                    "strict_treatment_claim_allowed",
                ),
                int_fields=("max_rounds_budget",),
                text_limit=120,
                max_list_items=max_list_items,
            ),
        ),
        (
            "claim_boundary",
            _compact_fields(
                source.get("claim_boundary"),
                text_fields=("public_claim_allowed",),
                bool_fields=(
                    "bridge_connectivity_claim_allowed",
                    "case_success_claim_allowed",
                    "official_score_claim_allowed",
                    "leaderboard_claim_allowed",
                ),
                list_fields=("forbidden_claims",),
                text_limit=180,
                max_list_items=max_list_items,
            ),
        ),
        (
            "agent",
            _compact_fields(
                source.get("agent"),
                text_fields=("name", "import_path", "model"),
                list_fields=("kwargs_keys",),
                text_limit=120,
                max_list_items=max_list_items,
            ),
        ),
        (
            "model_control",
            _compact_fields(
                source.get("model_control"),
                text_fields=(
                    "schema_version",
                    "requested_model",
                    "reported_model",
                    "control_method",
                    "control_status",
                    "actual_model_source",
                ),
                bool_fields=("actual_model_verified",),
                list_fields=("warning_labels",),
                text_limit=140,
                max_list_items=max_list_items,
            ),
        ),
    )
    return {field: value for field, value in sections if value}


def _compact_fields(
    value: Any,
    *,
    text_fields: tuple[str, ...] = (),
    bool_fields: tuple[str, ...] = (),
    int_fields: tuple[str, ...] = (),
    list_fields: tuple[str, ...] = (),
    text_limit: int,
    max_list_items: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    for field in text_fields:
        text = public_safe_compact_text(value.get(field), limit=text_limit)
        if text:
            compact[field] = text
    for field in bool_fields:
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    for field in int_fields:
        number = value.get(field)
        if isinstance(number, int) and not isinstance(number, bool):
            compact[field] = number
    for field in list_fields:
        items = public_safe_compact_list(value.get(field), limit=max_list_items)
        if items:
            compact[field] = items
    return compact
