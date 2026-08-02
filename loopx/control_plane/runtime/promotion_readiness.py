from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

PROMOTION_READINESS_CLASSIFICATION = "canary_promotion_readiness_smoke_group"
PROMOTION_READINESS_DELIVERY_BATCH_SCALE = "multi_surface"
PROMOTION_READINESS_DELIVERY_OUTCOME = "surface_only"
PROMOTION_READINESS_RUNTIME_DIR = Path("release") / "promotion-readiness" / "runs"
PROMOTION_READINESS_RUNTIME_INDEX = PROMOTION_READINESS_RUNTIME_DIR / "index.jsonl"
PROMOTION_READINESS_RECOMMENDED_ACTION = (
    "Canary promotion-readiness smoke passed; promotion may proceed after "
    "doctor/status reports fresh evidence."
)
PROMOTION_READINESS_RECOMMENDED_ACTION_DASHBOARD_SKIPPED = (
    "Canary promotion-readiness smoke passed for the installed release boundary; "
    "dashboard readiness was skipped because apps/presentation/dashboard is not "
    "shipped in the release snapshot."
)

PROMOTION_READINESS_PROXY_NOTE = (
    "canary readiness from runtime ledger or legacy goal history; exact evidence stays "
    "in append-only artifacts"
)
PROMOTION_READINESS_WRITEBACK_COMMAND = (
    "python3 examples/canary/canary-promotion-readiness-smoke.py"
)
PROMOTION_READINESS_WARNING_MESSAGE = PROMOTION_READINESS_WRITEBACK_COMMAND

ParseTimestamp = Callable[[Any], Any]
FreshnessBuilder = Callable[[dict[str, Any]], dict[str, Any]]
LatestReadinessEvent = Callable[[Path], dict[str, Any]]


def build_promotion_readiness_summary(
    history: dict[str, Any],
    *,
    parse_timestamp: ParseTimestamp,
    readiness_classifications: set[str],
    add_promotion_readiness_freshness: FreshnessBuilder,
    latest_promotion_readiness_event: LatestReadinessEvent,
    freshness_hours: int,
    runtime_root: Path | None = None,
    proxy_note: str = PROMOTION_READINESS_PROXY_NOTE,
) -> dict[str, Any]:
    latest: dict[str, Any] | None = None
    latest_at = None
    sample_count = 0
    source = "run_history"
    for run in history.get("runs") or []:
        if not isinstance(run, dict):
            continue
        classification = str(run.get("classification") or "")
        if classification not in readiness_classifications:
            continue
        sample_count += 1
        generated_at = parse_timestamp(run.get("generated_at"))
        if generated_at is None:
            continue
        if latest_at is None or generated_at > latest_at:
            latest_at = generated_at
            latest = run

    if runtime_root is not None:
        full_scan_latest = latest_promotion_readiness_event(runtime_root)
        full_scan_generated_at = parse_timestamp(full_scan_latest.get("generated_at"))
        runtime_release_authority = (
            full_scan_latest.get("source") == "runtime_release_ledger"
        )
        if full_scan_latest.get("available") and (
            runtime_release_authority
            or latest_at is None
            or (
                full_scan_generated_at is not None
                and full_scan_generated_at > latest_at
            )
        ):
            latest = full_scan_latest
            latest_at = full_scan_generated_at
            source = str(full_scan_latest.get("source") or "run_history_full_scan")

    if latest is None:
        readiness = add_promotion_readiness_freshness(
            {
                "available": False,
                "source": source,
                "reason": (
                    "no canary promotion readiness run found in full run history"
                    if runtime_root is not None
                    else "no canary promotion readiness run found in sampled history"
                ),
            }
        )
    else:
        readiness = add_promotion_readiness_freshness(
            {
                "available": True,
                "source": source,
                "goal_id": latest.get("goal_id"),
                "evidence_scope": latest.get("evidence_scope"),
                "dashboard_readiness": latest.get("dashboard_readiness"),
                "generated_at": latest.get("generated_at"),
                "classification": latest.get("classification"),
                "delivery_batch_scale": latest.get("delivery_batch_scale"),
                "delivery_outcome": latest.get("delivery_outcome"),
                "recommended_action": latest.get("recommended_action"),
                "json_exists": bool(latest.get("json_exists")),
                "markdown_exists": bool(latest.get("markdown_exists")),
            }
        )
    readiness.update(
        {
            "sample_run_count": sample_count,
            "proxy_note": proxy_note,
            "freshness_window_hours": freshness_hours,
        }
    )
    return readiness


def promotion_readiness_warning(status_payload: dict[str, Any]) -> dict[str, Any] | None:
    readiness = (
        status_payload.get("promotion_readiness_summary")
        if isinstance(status_payload.get("promotion_readiness_summary"), dict)
        else {}
    )
    if not readiness:
        return None
    freshness_status = str(readiness.get("freshness_status") or "unknown")
    requires_readiness_run = readiness.get("requires_readiness_run") is True
    available = readiness.get("available")
    if available is not False and not requires_readiness_run and freshness_status == "fresh":
        return None

    return {
        "source": readiness.get("source") or "run_history",
        "available": available,
        "freshness_status": freshness_status,
        "requires_readiness_run": requires_readiness_run,
        "freshness_window_hours": readiness.get("freshness_window_hours"),
        "age_hours": readiness.get("age_hours"),
        "sample_run_count": readiness.get("sample_run_count"),
        "goal_id": readiness.get("goal_id"),
        "generated_at": readiness.get("generated_at"),
        "classification": readiness.get("classification"),
        "dashboard_readiness": readiness.get("dashboard_readiness"),
        "json_exists": readiness.get("json_exists"),
        "markdown_exists": readiness.get("markdown_exists"),
        "reason": readiness.get("reason"),
        "message": PROMOTION_READINESS_WARNING_MESSAGE,
    }
