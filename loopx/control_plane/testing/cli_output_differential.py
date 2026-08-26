from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Literal

from ..quota.turn_envelope import (
    ACTION_SIGNATURE_COVERAGE_V0,
    ACTION_SIGNATURE_COVERAGE_V1,
    ACTION_SIGNATURE_COVERAGE_V2,
    ACTION_SIGNATURE_COVERAGE_V3,
)


CLI_OUTPUT_PROBE_SCHEMA_VERSION = "loopx_cli_output_probe_v0"
CLI_OUTPUT_FIXTURE_CONTRACT_VERSION = "loopx_cli_output_public_fixture_v0"
CLI_OUTPUT_DIFFERENTIAL_SCHEMA_VERSION = "loopx_cli_output_differential_v0"
ACTION_PORTFOLIO_SCHEMA_VERSION_V0 = "quota_action_portfolio_v0"
ACTION_PORTFOLIO_SCHEMA_VERSION_V1 = "quota_action_portfolio_v1"
ACTION_PORTFOLIO_SCHEMA_VERSION_V2 = "quota_action_portfolio_v2"
PLANNING_HORIZON_SCHEMA_VERSION_V0 = "quota_planning_horizon_v0"
PLANNING_INVENTORY_DETAIL_SCHEMA_VERSION_V0 = (
    "todo_planning_inventory_detail_v0"
)

Metric = Literal["chars", "utf8_bytes", "lines", "compact_payload_chars"]


def select_cli_output_base_ref(
    requested_ref: str,
    *,
    main_ref: str,
    is_ancestor: Callable[[str, str], bool],
) -> str:
    """Choose main for a sync commit that brings main into a stale PR base."""
    if requested_ref == main_ref:
        return requested_ref
    head_contains_main = is_ancestor(main_ref, "HEAD")
    requested_contains_main = is_ancestor(main_ref, requested_ref)
    if head_contains_main and not requested_contains_main:
        return main_ref
    return requested_ref


@dataclass(frozen=True)
class GrowthAllowance:
    ratio: float
    json: dict[Metric, int]
    markdown: dict[Metric, int]


_GROWTH_ALLOWANCE_BY_POLICY: dict[str, GrowthAllowance] = {
    "absolute_hot_path": GrowthAllowance(
        ratio=0.005,
        json={"chars": 64, "utf8_bytes": 128, "lines": 2, "compact_payload_chars": 64},
        markdown={
            "chars": 32,
            "utf8_bytes": 64,
            "lines": 1,
            "compact_payload_chars": 0,
        },
    ),
    "baseline_and_growth": GrowthAllowance(
        ratio=0.005,
        json={
            "chars": 128,
            "utf8_bytes": 256,
            "lines": 2,
            "compact_payload_chars": 128,
        },
        markdown={
            "chars": 64,
            "utf8_bytes": 128,
            "lines": 1,
            "compact_payload_chars": 0,
        },
    ),
    "explicit_limit_cold_path": GrowthAllowance(
        ratio=0.01,
        json={
            "chars": 256,
            "utf8_bytes": 512,
            "lines": 5,
            "compact_payload_chars": 256,
        },
        markdown={
            "chars": 128,
            "utf8_bytes": 256,
            "lines": 2,
            "compact_payload_chars": 0,
        },
    ),
    "explicit_opt_in_cold_path": GrowthAllowance(
        ratio=0.01,
        json={
            "chars": 256,
            "utf8_bytes": 512,
            "lines": 5,
            "compact_payload_chars": 256,
        },
        markdown={
            "chars": 128,
            "utf8_bytes": 256,
            "lines": 2,
            "compact_payload_chars": 0,
        },
    ),
}

# quota_action_portfolio_v1/v2 migrations add a bounded executable portfolio
# and then inline the small action context needed to interpret each choice.
# This allowance applies only to a declared schema transition; once v2 is the
# baseline, ordinary policy budgets apply again.
_ACTION_PORTFOLIO_V0_MIGRATION_GROWTH_ALLOWANCE: dict[Metric, int] = {
    "chars": 1_600,
    "utf8_bytes": 1_600,
    "lines": 42,
    "compact_payload_chars": 1_280,
}

# quota_planning_horizon_v0 adds one bounded read-only strategic context to the
# default agent path and TurnEnvelope. This allowance applies only while the
# schema and action-signature coverage move to v0/v3; after merge the candidate
# becomes the new baseline and ordinary growth limits apply again.
_PLANNING_HORIZON_V0_MIGRATION_GROWTH_ALLOWANCE: dict[Metric, int] = {
    "chars": 3_200,
    "utf8_bytes": 3_200,
    "lines": 84,
    "compact_payload_chars": 2_800,
}

# todo_planning_inventory_detail_v0 adds planning/claim semantics only to the
# explicit agent-Todo detail variants. The allowance is bound to the declared
# none-to-v0 schema migration; after merge the ordinary cold-path budget
# applies again.
_PLANNING_INVENTORY_DETAIL_V0_MIGRATION_GROWTH_ALLOWANCE: dict[Metric, int] = {
    "chars": 1_280,
    "utf8_bytes": 1_280,
    "lines": 36,
    "compact_payload_chars": 1_024,
}


def _rows_by_id(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if receipt.get("schema_version") != CLI_OUTPUT_PROBE_SCHEMA_VERSION:
        raise ValueError("CLI output probe receipt has an unsupported schema_version")
    if receipt.get("fixture_contract_version") != CLI_OUTPUT_FIXTURE_CONTRACT_VERSION:
        raise ValueError(
            "CLI output probe receipt has an unsupported fixture_contract_version"
        )
    rows = receipt.get("rows")
    if not isinstance(rows, list):
        raise ValueError("CLI output probe receipt rows must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("row_id"), str):
            raise ValueError("CLI output probe row must be an object with row_id")
        row_id = row["row_id"]
        if row_id in indexed:
            raise ValueError(f"duplicate CLI output probe row_id: {row_id}")
        indexed[row_id] = row
    return indexed


def _growth_limit(*, policy: str, output_format: str, metric: Metric, base: int) -> int:
    allowance = _GROWTH_ALLOWANCE_BY_POLICY.get(policy)
    if allowance is None:
        raise ValueError(f"unsupported CLI output qualification policy: {policy}")
    floors = allowance.json if output_format == "json" else allowance.markdown
    return max(floors[metric], math.ceil(base * allowance.ratio))


def _removed(base: dict[str, Any], candidate: dict[str, Any], field: str) -> list[str]:
    base_values = {str(value) for value in base.get(field, [])}
    candidate_values = {str(value) for value in candidate.get(field, [])}
    return sorted(base_values - candidate_values)


def _action_signature_migration(
    base: dict[str, Any], candidate: dict[str, Any]
) -> str | None:
    base_coverages = base.get("action_signature_coverages")
    candidate_coverages = candidate.get("action_signature_coverages")
    allowed_migrations = {
        (ACTION_SIGNATURE_COVERAGE_V0, ACTION_SIGNATURE_COVERAGE_V1),
        (ACTION_SIGNATURE_COVERAGE_V0, ACTION_SIGNATURE_COVERAGE_V2),
        (ACTION_SIGNATURE_COVERAGE_V1, ACTION_SIGNATURE_COVERAGE_V2),
        (ACTION_SIGNATURE_COVERAGE_V0, ACTION_SIGNATURE_COVERAGE_V3),
        (ACTION_SIGNATURE_COVERAGE_V1, ACTION_SIGNATURE_COVERAGE_V3),
        (ACTION_SIGNATURE_COVERAGE_V2, ACTION_SIGNATURE_COVERAGE_V3),
    }
    if not (
        isinstance(base_coverages, list)
        and len(base_coverages) == 1
        and isinstance(candidate_coverages, list)
        and len(candidate_coverages) == 1
    ):
        return None
    migration = (base_coverages[0], candidate_coverages[0])
    if migration not in allowed_migrations:
        return None
    return f"{migration[0]} -> {migration[1]}"


def _action_portfolio_schema_migration(
    base: dict[str, Any], candidate: dict[str, Any]
) -> str | None:
    base_versions = base.get("action_portfolio_schema_versions")
    candidate_versions = candidate.get("action_portfolio_schema_versions")
    allowed_migrations = {
        ((), (ACTION_PORTFOLIO_SCHEMA_VERSION_V0,)),
        ((), (ACTION_PORTFOLIO_SCHEMA_VERSION_V1,)),
        ((), (ACTION_PORTFOLIO_SCHEMA_VERSION_V2,)),
        (
            (ACTION_PORTFOLIO_SCHEMA_VERSION_V0,),
            (ACTION_PORTFOLIO_SCHEMA_VERSION_V1,),
        ),
        (
            (ACTION_PORTFOLIO_SCHEMA_VERSION_V0,),
            (ACTION_PORTFOLIO_SCHEMA_VERSION_V2,),
        ),
        (
            (ACTION_PORTFOLIO_SCHEMA_VERSION_V1,),
            (ACTION_PORTFOLIO_SCHEMA_VERSION_V2,),
        ),
    }
    migration = (tuple(base_versions or []), tuple(candidate_versions or []))
    if migration in allowed_migrations:
        before = base_versions[0] if base_versions else "none"
        after = candidate_versions[0] if candidate_versions else "none"
        return f"{before} -> {after}"
    return None


def _planning_horizon_schema_migration(
    base: dict[str, Any], candidate: dict[str, Any]
) -> str | None:
    base_versions = tuple(base.get("planning_horizon_schema_versions") or [])
    candidate_versions = tuple(
        candidate.get("planning_horizon_schema_versions") or []
    )
    if base_versions == () and candidate_versions == (
        PLANNING_HORIZON_SCHEMA_VERSION_V0,
    ):
        return f"none -> {PLANNING_HORIZON_SCHEMA_VERSION_V0}"
    return None


def _planning_inventory_detail_schema_migration(
    base: dict[str, Any], candidate: dict[str, Any]
) -> str | None:
    base_versions = tuple(
        base.get("planning_inventory_detail_schema_versions") or []
    )
    candidate_versions = tuple(
        candidate.get("planning_inventory_detail_schema_versions") or []
    )
    if base_versions == () and candidate_versions == (
        PLANNING_INVENTORY_DETAIL_SCHEMA_VERSION_V0,
    ):
        return f"none -> {PLANNING_INVENTORY_DETAIL_SCHEMA_VERSION_V0}"
    return None


def _compare_row(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    row_id = str(base["row_id"])
    failures: list[str] = []
    review_signals: list[str] = []
    policy = str(base.get("qualification_policy") or "")
    output_format = str(base.get("format") or "")
    if candidate.get("qualification_policy") != policy:
        failures.append("qualification_policy changed")
    if candidate.get("format") != output_format:
        failures.append("format changed")

    base_signature = base.get("action_signature_sha256")
    signature_changed = bool(
        base_signature
        and candidate.get("action_signature_sha256") != base_signature
    )
    signature_migration = (
        _action_signature_migration(base, candidate) if signature_changed else None
    )
    base_portfolio_versions = base.get("action_portfolio_schema_versions")
    candidate_portfolio_versions = candidate.get("action_portfolio_schema_versions")
    portfolio_schema_changed = base_portfolio_versions != candidate_portfolio_versions
    portfolio_schema_migration = (
        _action_portfolio_schema_migration(base, candidate)
        if portfolio_schema_changed
        else None
    )
    base_horizon_versions = base.get("planning_horizon_schema_versions")
    candidate_horizon_versions = candidate.get("planning_horizon_schema_versions")
    horizon_schema_changed = base_horizon_versions != candidate_horizon_versions
    horizon_schema_migration = (
        _planning_horizon_schema_migration(base, candidate)
        if horizon_schema_changed
        else None
    )
    base_inventory_detail_versions = base.get(
        "planning_inventory_detail_schema_versions"
    )
    candidate_inventory_detail_versions = candidate.get(
        "planning_inventory_detail_schema_versions"
    )
    inventory_detail_schema_changed = (
        base_inventory_detail_versions != candidate_inventory_detail_versions
    )
    inventory_detail_schema_migration = (
        _planning_inventory_detail_schema_migration(base, candidate)
        if inventory_detail_schema_changed
        else None
    )
    portfolio_growth_migration = bool(
        output_format == "json"
        and (
            portfolio_schema_migration
            or (
                signature_migration
                and signature_migration.endswith(
                    f" -> {ACTION_SIGNATURE_COVERAGE_V2}"
                )
            )
        )
    )
    horizon_growth_migration = bool(
        output_format == "json"
        and (
            horizon_schema_migration
            or (
                signature_migration
                and signature_migration.endswith(
                    f" -> {ACTION_SIGNATURE_COVERAGE_V3}"
                )
            )
        )
    )
    inventory_detail_growth_migration = bool(
        output_format == "json" and inventory_detail_schema_migration
    )

    deltas: dict[str, int | None] = {}
    allowances: dict[str, int | None] = {}
    for metric in ("chars", "utf8_bytes", "lines", "compact_payload_chars"):
        base_value = base.get(metric)
        candidate_value = candidate.get(metric)
        if not isinstance(base_value, int) or not isinstance(candidate_value, int):
            deltas[metric] = None
            allowances[metric] = None
            continue
        delta = candidate_value - base_value
        allowance = _growth_limit(
            policy=policy,
            output_format=output_format,
            metric=metric,
            base=base_value,
        )
        if portfolio_growth_migration:
            allowance = max(
                allowance,
                _ACTION_PORTFOLIO_V0_MIGRATION_GROWTH_ALLOWANCE[metric],
            )
        if horizon_growth_migration:
            allowance = max(
                allowance,
                _PLANNING_HORIZON_V0_MIGRATION_GROWTH_ALLOWANCE[metric],
            )
        if inventory_detail_growth_migration:
            allowance = max(
                allowance,
                _PLANNING_INVENTORY_DETAIL_V0_MIGRATION_GROWTH_ALLOWANCE[
                    metric
                ],
            )
        deltas[metric] = delta
        allowances[metric] = allowance
        if delta > allowance:
            failures.append(f"{metric} grew by {delta}; allowance is {allowance}")

    for field in ("semantic_json_keys",):
        missing = _removed(base, candidate, field)
        if missing:
            preview = ", ".join(missing[:5])
            suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
            failures.append(f"{field} removed: {preview}{suffix}")

    for field in ("json_shape_paths", "markdown_headings"):
        missing = _removed(base, candidate, field)
        if missing:
            preview = ", ".join(missing[:5])
            suffix = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
            review_signals.append(f"{field} removed: {preview}{suffix}")

    base_anchor = base.get("markdown_anchor")
    if base_anchor and candidate.get("markdown_anchor") != base_anchor:
        failures.append("markdown_anchor changed")
    if signature_changed:
        if signature_migration is None:
            failures.append("action_signature semantic digest changed")
        else:
            review_signals.append(
                f"action_signature coverage migrated: {signature_migration}"
            )
    if portfolio_schema_changed:
        if portfolio_schema_migration is None:
            failures.append("action_portfolio schema coverage changed")
        else:
            review_signals.append(
                f"action_portfolio schema migrated: {portfolio_schema_migration}"
            )
    if horizon_schema_changed:
        if horizon_schema_migration is None:
            failures.append("planning_horizon schema coverage changed")
        else:
            review_signals.append(
                f"planning_horizon schema migrated: {horizon_schema_migration}"
            )
    if inventory_detail_schema_changed:
        if inventory_detail_schema_migration is None:
            failures.append("planning inventory detail schema coverage changed")
        else:
            review_signals.append(
                "planning inventory detail schema migrated: "
                f"{inventory_detail_schema_migration}"
            )

    return {
        "row_id": row_id,
        "status": "failed" if failures else "passed",
        "deltas": deltas,
        "allowances": allowances,
        "failures": failures,
        "review_signals": review_signals,
    }


def compare_cli_output_receipts(
    base_receipt: dict[str, Any],
    candidate_receipt: dict[str, Any],
) -> dict[str, Any]:
    base_rows = _rows_by_id(base_receipt)
    candidate_rows = _rows_by_id(candidate_receipt)
    results: list[dict[str, Any]] = []
    for row_id in sorted(base_rows.keys() | candidate_rows.keys()):
        base = base_rows.get(row_id)
        candidate = candidate_rows.get(row_id)
        if base is None:
            results.append(
                {
                    "row_id": row_id,
                    "status": "candidate_only",
                    "deltas": {},
                    "allowances": {},
                    "failures": [],
                    "review_signals": [],
                }
            )
        elif candidate is None:
            results.append(
                {
                    "row_id": row_id,
                    "status": "failed",
                    "deltas": {},
                    "allowances": {},
                    "failures": ["qualified base row is missing from candidate"],
                    "review_signals": [],
                }
            )
        else:
            results.append(_compare_row(base, candidate))

    failed_rows = [row for row in results if row["status"] == "failed"]
    review_rows = [row for row in results if row["review_signals"]]
    return {
        "schema_version": CLI_OUTPUT_DIFFERENTIAL_SCHEMA_VERSION,
        "ok": not failed_rows,
        "base_row_count": len(base_rows),
        "candidate_row_count": len(candidate_rows),
        "compared_row_count": len(results),
        "failed_row_count": len(failed_rows),
        "review_required": bool(review_rows),
        "review_row_count": len(review_rows),
        "candidate_only_row_count": sum(
            row["status"] == "candidate_only" for row in results
        ),
        "rows": results,
    }
