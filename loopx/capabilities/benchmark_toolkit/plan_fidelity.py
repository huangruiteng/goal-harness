from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

BENCHMARK_PLAN_FIDELITY_SCHEMA_VERSION = "benchmark_plan_fidelity_v0"

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")


class BenchmarkPlanRole(str, Enum):
    """Stable semantic roles used to qualify a benchmark treatment plan."""

    TECHNICAL_WORK = "technical_work"
    INDEPENDENT_VALIDATION = "independent_validation"
    REVIEW_REFINE = "review_refine"


def _role(value: BenchmarkPlanRole | str) -> BenchmarkPlanRole:
    try:
        return BenchmarkPlanRole(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_benchmark_plan_role") from exc


def _token(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"invalid_{field}")
    text = value.strip()
    if not _TOKEN_RE.fullmatch(text):
        raise ValueError(f"invalid_{field}")
    return text


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"invalid_{field}")
    if value > 1024:
        raise ValueError(f"invalid_{field}")
    return value


def _normalize_role_action_kinds(
    value: Mapping[BenchmarkPlanRole | str, Sequence[str]],
) -> dict[BenchmarkPlanRole, tuple[str, ...]]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("invalid_role_action_kind_contract")
    normalized: dict[BenchmarkPlanRole, tuple[str, ...]] = {}
    token_owner: dict[str, BenchmarkPlanRole] = {}
    for raw_role, raw_tokens in value.items():
        role = _role(raw_role)
        if role in normalized:
            raise ValueError("duplicate_benchmark_plan_role")
        if isinstance(raw_tokens, (str, bytes)) or not isinstance(raw_tokens, Sequence):
            raise TypeError("invalid_role_action_kind_contract")
        tokens = tuple(
            sorted({_token(item, field="action_kind") for item in raw_tokens})
        )
        if not tokens:
            raise ValueError("invalid_role_action_kind_contract")
        for token in tokens:
            if token in token_owner:
                raise ValueError("action_kind_contract_overlap")
            token_owner[token] = role
        normalized[role] = tokens
    return normalized


def _normalize_required_role_counts(
    value: Mapping[BenchmarkPlanRole | str, int],
) -> dict[BenchmarkPlanRole, int]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("invalid_required_role_counts")
    normalized: dict[BenchmarkPlanRole, int] = {}
    for raw_role, raw_count in value.items():
        role = _role(raw_role)
        if role in normalized:
            raise ValueError("duplicate_required_benchmark_plan_role")
        normalized[role] = _positive_int(raw_count, field="required_role_count")
    return normalized


def build_benchmark_plan_fidelity_receipt(
    *,
    action_kinds: Sequence[str],
    role_action_kinds: Mapping[BenchmarkPlanRole | str, Sequence[str]],
    required_role_counts: Mapping[BenchmarkPlanRole | str, int],
) -> dict[str, Any]:
    """Reduce provider Todo action kinds to a public-safe plan-fidelity receipt.

    The provider declares exact action-kind tokens for each stable semantic role.
    LoopX intentionally performs no substring, title, or prose inference.
    """

    if isinstance(action_kinds, (str, bytes)) or not isinstance(action_kinds, Sequence):
        raise TypeError("invalid_action_kinds")
    observed_tokens = [_token(item, field="action_kind") for item in action_kinds]
    contract = _normalize_role_action_kinds(role_action_kinds)
    required = _normalize_required_role_counts(required_role_counts)
    if any(role not in contract for role in required):
        raise ValueError("required_role_missing_action_kind_contract")

    token_roles = {token: role for role, tokens in contract.items() for token in tokens}
    counts = {role: 0 for role in BenchmarkPlanRole}
    classified_count = 0
    for token in observed_tokens:
        role = token_roles.get(token)
        if role is None:
            continue
        counts[role] += 1
        classified_count += 1

    missing_roles = [
        role
        for role in BenchmarkPlanRole
        if role in required and counts[role] < required[role]
    ]
    qualified = not missing_roles
    return {
        "schema_version": BENCHMARK_PLAN_FIDELITY_SCHEMA_VERSION,
        "qualified": qualified,
        "classification": (
            "plan_role_contract_qualified"
            if qualified
            else "required_plan_role_missing"
        ),
        "observed_role_counts": {
            role.value: counts[role] for role in BenchmarkPlanRole
        },
        "required_role_counts": {
            role.value: required[role] for role in BenchmarkPlanRole if role in required
        },
        "classified_action_count": classified_count,
        "unclassified_action_count": len(observed_tokens) - classified_count,
        "blockers": [f"required_role_missing:{role.value}" for role in missing_roles],
        "exact_action_kind_matching": True,
        "public_boundary": {
            "todo_text_recorded": False,
            "raw_action_kinds_recorded": False,
            "path_recorded": False,
            "trajectory_recorded": False,
        },
        "write_performed": False,
    }
