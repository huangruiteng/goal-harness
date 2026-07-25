from __future__ import annotations

from typing import Any, Iterable, Mapping


RECOVERABLE_CODEX_TRANSPORT_FAILURE_CATEGORIES = frozenset(
    {
        "codex_network_or_api_unreachable",
        "codex_responses_stream_unavailable",
        "codex_reverse_channel_unavailable",
    }
)

RECOVERABLE_CODEX_TURN_FAILURE_CATEGORIES = frozenset(
    {
        "codex_exec_timeout",
        "codex_exec_first_action_timeout",
        "codex_exec_task_output_quiet_timeout",
        "codex_exec_bridge_idle_timeout",
    }
) | RECOVERABLE_CODEX_TRANSPORT_FAILURE_CATEGORIES
RECOVERABLE_CODEX_TURN_FAILURE_PREFIX = "LoopX recoverable Codex turn failure:"

RECOVERABLE_TRANSPORT_INFRA_FAILURE_LABELS = frozenset(
    {
        "skillsbench_runner_error",
        "skillsbench_codex_acp_jsonrpc_internal_error",
        "skillsbench_codex_acp_transport_error",
        "skillsbench_product_mode_transport_failure",
        "skillsbench_host_local_acp_codex_exec_failed",
        "skillsbench_runner_setup_error",
        "verifier_infrastructure_failure",
        "official_verifier_solution_failure",
    }
)


def recoverable_codex_turn_failure_message(category: str) -> str:
    return (
        RECOVERABLE_CODEX_TURN_FAILURE_PREFIX + " "
        f"{category}. Continue with the next scheduled product-mode round; "
        "raw task text, logs, and trajectory material were not recorded."
    )


def nonrecoverable_codex_turn_failure_category(
    counters: Mapping[str, Any],
) -> str:
    """Return the first typed fatal Codex category from public relay evidence."""

    failure_count = _count(
        counters,
        "host_local_acp_codex_exec_failure_trace_count",
    )
    fatal_count = _count(
        counters,
        "host_local_acp_codex_exec_fatal_failure_trace_count",
    )
    if (
        counters.get("host_local_acp_codex_exec_failure_trace_present") is not True
        or failure_count == 0
        or fatal_count == 0
    ):
        return ""

    categories: list[str] = []
    raw_categories = counters.get(
        "host_local_acp_codex_exec_failure_categories"
    )
    if isinstance(raw_categories, list):
        categories.extend(
            str(category)[:120]
            for category in raw_categories
            if isinstance(category, str) and category
        )
    first_category = counters.get(
        "host_local_acp_codex_exec_failure_category"
    )
    if (
        isinstance(first_category, str)
        and first_category
        and first_category not in categories
    ):
        categories.insert(0, first_category[:120])

    for category in categories:
        if category not in RECOVERABLE_CODEX_TURN_FAILURE_CATEGORIES:
            return category
    return ""


def recoverable_transport_after_bridge_attempt(
    counters: Mapping[str, Any],
    *,
    official_score_present: bool,
    task_facing_success_count: int,
) -> bool:
    categories = {
        str(category)
        for category in counters.get(
            "host_local_acp_codex_exec_failure_categories", []
        )
        if isinstance(category, str) and category
    }
    first_category = counters.get("host_local_acp_codex_exec_failure_category")
    if not categories and isinstance(first_category, str) and first_category:
        categories.add(first_category)

    failure_count = _count(counters, "host_local_acp_codex_exec_failure_trace_count")
    recoverable_count = _count(
        counters,
        "host_local_acp_codex_exec_recoverable_failure_trace_count",
    )
    fatal_count = _count(
        counters,
        "host_local_acp_codex_exec_fatal_failure_trace_count",
    )
    return bool(
        counters.get("host_local_acp_codex_exec_failure_trace_present") is True
        and failure_count > 0
        and categories
        and categories.issubset(RECOVERABLE_CODEX_TRANSPORT_FAILURE_CATEGORIES)
        and fatal_count == 0
        and recoverable_count in {0, failure_count}
        and official_score_present
        and task_facing_success_count > 0
    )


def without_recoverable_transport_infra_labels(labels: Iterable[str]) -> list[str]:
    return [
        label
        for label in labels
        if label not in RECOVERABLE_TRANSPORT_INFRA_FAILURE_LABELS
        and not label.startswith("skillsbench_host_local_acp_codex_exec_failed_")
    ]


def _count(counters: Mapping[str, Any], key: str) -> int:
    value = counters.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return 0
