from __future__ import annotations

from typing import Any

from ..runtime.agent_scoped_evidence_log import (
    build_agent_scoped_evidence_log_command,
)
from ..runtime.time import parse_timestamp

AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW = 20
REPLAN_REQUIRED_READ_VALIDATION_SCHEMA_VERSION = (
    "replan_required_read_validation_v0"
)
REPLAN_REQUIRED_READ_LIMIT = 24


def autonomous_replan_ack_recorded(run: dict[str, Any]) -> bool:
    ack = run.get("autonomous_replan_ack")
    if not isinstance(ack, dict) or ack.get("recorded") is not True:
        return False
    delta_contract = ack.get("delta_contract")
    if not isinstance(delta_contract, dict):
        return False
    return delta_contract.get("delta_present") is True


def watch_lane_continuation_todo_ids(
    delta_contract: dict[str, Any] | None,
) -> list[str]:
    """Return the exact Todo evidence carried by a validated watch delta."""

    if not isinstance(delta_contract, dict):
        return []
    todo_ids: list[str] = []
    for item in delta_contract.get("auto_evidence") or []:
        if not isinstance(item, dict) or item.get("kind") != "watch_lane_continuation":
            continue
        for raw_todo_id in item.get("todo_ids") or []:
            todo_id = str(raw_todo_id or "").strip()
            if todo_id and todo_id not in todo_ids:
                todo_ids.append(todo_id)
    return todo_ids


def compact_autonomous_replan_ack(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(run, dict) or not autonomous_replan_ack_recorded(run):
        return None
    ack = run.get("autonomous_replan_ack")
    if not isinstance(ack, dict):
        return None
    delta_contract = ack.get("delta_contract") if isinstance(ack, dict) else {}
    if not isinstance(delta_contract, dict):
        return None
    compact_delta: dict[str, Any] = {
        "schema_version": delta_contract.get("schema_version"),
        "delta_present": bool(delta_contract.get("delta_present")),
        "delta_kinds": [
            str(item)
            for item in (delta_contract.get("delta_kinds") or [])
            if str(item or "").strip()
        ],
    }
    watch_evidence: list[dict[str, Any]] = []
    todo_ids = watch_lane_continuation_todo_ids(delta_contract)[:4]
    if todo_ids:
        watch_evidence.append(
            {
                "kind": "watch_lane_continuation",
                "todo_ids": todo_ids,
            }
        )
    if watch_evidence:
        compact_delta["auto_evidence"] = watch_evidence
    stall_evidence = next(
        (
            item
            for item in (delta_contract.get("auto_evidence") or [])
            if isinstance(item, dict)
            and item.get("kind") == "blocker"
            and str(item.get("stall_fingerprint") or "").strip()
        ),
        None,
    )
    if stall_evidence:
        compact_delta.setdefault("auto_evidence", []).append(
            {
                key: stall_evidence[key]
                for key in (
                    "kind",
                    "todo_ids",
                    "stall_fingerprint",
                    "selected_todo_id",
                    "blocker_todo_id",
                    "evidence_hash",
                    "runnable_todo_ids",
                    "direction_signatures",
                )
                if key in stall_evidence
            }
        )
    result = {
        "schema_version": ack.get("schema_version"),
        "recorded": True,
        "source": ack.get("source"),
        "delta_contract": compact_delta,
    }
    agent_id = str(run.get("agent_id") or "").strip()
    if agent_id:
        result["agent_id"] = agent_id
    frontier_identity = str(ack.get("frontier_identity") or "").strip()
    if frontier_identity:
        result["frontier_identity"] = frontier_identity
    generated_at = str(run.get("generated_at") or "").strip()
    if generated_at:
        result["generated_at"] = generated_at
    return result


def latest_blocked_successor_frontier_identity(
    latest_runs: list[dict[str, Any]] | None,
    *,
    agent_id: str | None = None,
) -> str | None:
    return _latest_monitor_replan_frontier_identity(
        latest_runs,
        agent_id=agent_id,
        include_generic_watch=False,
    )


def latest_monitor_replan_frontier_identity(
    latest_runs: list[dict[str, Any]] | None,
    *,
    agent_id: str | None = None,
    watch_todo_ids: list[str] | None = None,
) -> str | None:
    """Return the latest monitor identity that a durable replan ACK must bind."""

    return _latest_monitor_replan_frontier_identity(
        latest_runs,
        agent_id=agent_id,
        include_generic_watch=True,
        watch_todo_ids=watch_todo_ids,
    )


def _latest_monitor_replan_frontier_identity(
    latest_runs: list[dict[str, Any]] | None,
    *,
    agent_id: str | None,
    include_generic_watch: bool,
    watch_todo_ids: list[str] | None = None,
) -> str | None:
    normalized_agent_id = str(agent_id or "").strip()
    normalized_watch_todo_ids = {
        str(todo_id or "").strip()
        for todo_id in (watch_todo_ids or [])
        if str(todo_id or "").strip()
    }
    evidence_linked_watch = (
        include_generic_watch and len(normalized_watch_todo_ids) == 1
    )
    intervening_material_runs = 0
    for run in latest_runs or []:
        if not isinstance(run, dict):
            continue
        target = (
            run.get("monitor_target")
            if isinstance(run.get("monitor_target"), dict)
            else {}
        )
        if normalized_agent_id:
            run_agent_id = str(run.get("agent_id") or "").strip()
            target_agent_id = str(target.get("agent_id") or "").strip()
            if run_agent_id and target_agent_id and run_agent_id != target_agent_id:
                if normalized_agent_id in {run_agent_id, target_agent_id}:
                    return None
                continue
            attributed_agent_id = run_agent_id or target_agent_id
            if not attributed_agent_id:
                return None
            if attributed_agent_id != normalized_agent_id:
                continue
        classification = str(run.get("classification") or "").strip()
        if classification != "quota_monitor_poll":
            if evidence_linked_watch:
                intervening_material_runs += 1
                if (
                    intervening_material_runs
                    >= AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW
                ):
                    return None
                continue
            return None
        if target.get("monitor_mode") != (
            "blocked_successor_wait_without_material_transition"
        ):
            if not (
                include_generic_watch
                and target.get("monitor_mode")
                == "monitor_quiet_until_material_transition"
            ):
                continue
            target_identity = str(target.get("target_id") or "").strip()
            return target_identity or None
        if intervening_material_runs:
            return None
        frontier_identity = str(target.get("frontier_identity") or "").strip()
        return frontier_identity or None
    return None


def autonomous_replan_ack_matches_frontier(
    ack: dict[str, Any] | None,
    obligation: dict[str, Any] | None,
) -> bool:
    if not isinstance(obligation, dict):
        return True
    frontier_identity = str(obligation.get("frontier_identity") or "").strip()
    if not frontier_identity:
        return True
    if not isinstance(ack, dict):
        return False
    if str(ack.get("frontier_identity") or "").strip() != frontier_identity:
        return False

    ack_generated_at = parse_timestamp(
        ack.get("generated_at") or ack.get("recorded_at")
    )
    trigger_times = [
        parsed
        for trigger in obligation.get("triggers") or []
        if isinstance(trigger, dict)
        if (
            parsed := parse_timestamp(
                trigger.get("latest_generated_at") or trigger.get("generated_at")
            )
        )
        is not None
    ]
    if ack_generated_at is not None and trigger_times:
        return ack_generated_at >= max(trigger_times)
    return True


def autonomous_replan_ack_matches_agent(
    ack: dict[str, Any] | None,
    *,
    agent_id: str | None,
) -> bool:
    if not isinstance(ack, dict):
        return False
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return True
    ack_agent_id = str(ack.get("agent_id") or "").strip()
    return bool(ack_agent_id and ack_agent_id == normalized_agent_id)


def _replan_obligation_triggered_at(
    obligation: dict[str, Any],
) -> str | None:
    candidates = [
        parse_timestamp(obligation.get("triggered_at")),
        *[
            parsed
            for trigger in obligation.get("triggers") or []
            if isinstance(trigger, dict)
            if (
                parsed := parse_timestamp(
                    trigger.get("latest_generated_at")
                    or trigger.get("generated_at")
                    or trigger.get("triggered_at")
                )
            )
            is not None
        ],
    ]
    timestamps = [item for item in candidates if item is not None]
    if not timestamps:
        return None
    return max(timestamps).isoformat().replace("+00:00", "Z")


def _replan_requires_agent_evidence_log(
    obligation: dict[str, Any],
) -> bool:
    policy = obligation.get("replan_novelty_policy")
    if not isinstance(policy, dict):
        return False
    return str(
        policy.get("evidence_source") or policy.get("evidence") or ""
    ).strip() == "agent_scoped_evidence_log"


def _ack_is_prior_watch_continuation_for_obligation(
    ack: dict[str, Any],
    obligation: dict[str, Any],
) -> bool:
    """Return whether a prior ACK is typed evidence for this exact watch frontier."""

    ack_frontier = str(ack.get("frontier_identity") or "").strip()
    obligation_frontier = str(obligation.get("frontier_identity") or "").strip()
    if not ack_frontier or ack_frontier != obligation_frontier:
        return False
    delta_contract = ack.get("delta_contract")
    if not isinstance(delta_contract, dict):
        return False
    delta_kinds = {
        str(item or "").strip()
        for item in delta_contract.get("delta_kinds") or []
        if str(item or "").strip()
    }
    return "watch_lane_continuation" in delta_kinds


def validate_replan_required_read_receipt(
    ack: dict[str, Any] | None,
    *,
    replan_obligation: dict[str, Any] | None,
    receipts: list[dict[str, Any]] | None,
    goal_id: str,
    agent_id: str | None,
) -> dict[str, Any] | None:
    """Validate one ACK against the fresh evidence-log read it requires."""

    if not isinstance(replan_obligation, dict) or not (
        _replan_requires_agent_evidence_log(replan_obligation)
    ):
        return None
    safe_agent_id = str(agent_id or "").strip()
    if not isinstance(ack, dict) or not safe_agent_id:
        return None
    acked_at = parse_timestamp(ack.get("generated_at") or ack.get("recorded_at"))
    triggered_at_text = _replan_obligation_triggered_at(replan_obligation)
    triggered_at = parse_timestamp(triggered_at_text)
    if (
        acked_at is not None
        and triggered_at is not None
        and acked_at < triggered_at
        and _ack_is_prior_watch_continuation_for_obligation(
            ack,
            replan_obligation,
        )
    ):
        # Only typed watch continuation evidence for the same stable frontier
        # may predate the obligation. Ordinary replan ACKs must still satisfy
        # this obligation by identity even when projection clocks are reordered.
        return None
    required_read_id = str(replan_obligation.get("obligation_id") or "").strip()
    command = build_agent_scoped_evidence_log_command(
        goal_id=goal_id,
        agent_id=safe_agent_id,
        limit=REPLAN_REQUIRED_READ_LIMIT,
        required_read_id=required_read_id or None,
    )
    matched_receipt: dict[str, Any] | None = None
    if acked_at is not None and (triggered_at is not None or required_read_id):
        matched_receipt = next(
            (
                receipt
                for receipt in receipts or []
                if isinstance(receipt, dict)
                and receipt.get("schema_version")
                == "evidence_log_read_receipt_v0"
                and str(receipt.get("goal_id") or "") == str(goal_id)
                and str(receipt.get("agent_id") or "") == safe_agent_id
                and str(receipt.get("command") or "") == command
                and isinstance(
                    read_window := receipt.get("read_window"),
                    dict,
                )
                and read_window.get("mode") == "thin"
                and read_window.get("limit") == REPLAN_REQUIRED_READ_LIMIT
                and (
                    not required_read_id
                    or str(receipt.get("required_read_id") or "") == required_read_id
                )
                and (
                    recorded_at := parse_timestamp(receipt.get("recorded_at"))
                )
                is not None
                and (
                    bool(required_read_id)
                    or triggered_at is None
                    or triggered_at <= recorded_at
                )
                and recorded_at <= acked_at
            ),
            None,
        )
    satisfied = matched_receipt is not None
    reason = (
        "required evidence-log read receipt is missing or stale; run "
        f"`{command}` after this obligation trigger before ACK writeback"
    )
    result: dict[str, Any] = {
        "schema_version": REPLAN_REQUIRED_READ_VALIDATION_SCHEMA_VERSION,
        "enforcement": "hard",
        "accepted": satisfied,
        "required_read_satisfied": satisfied,
        "triggered_at": triggered_at_text,
        "acknowledged_at": (
            acked_at.isoformat().replace("+00:00", "Z")
            if acked_at is not None
            else None
        ),
        "required_read": {
            "kind": "agent_scoped_evidence_log",
            "goal_id": goal_id,
            "agent_id": safe_agent_id,
            "command": command,
            "required_read_id": required_read_id or None,
        },
    }
    if matched_receipt:
        result["matched_receipt"] = matched_receipt
        if str(matched_receipt.get("status") or "").strip() == "failed":
            result["warnings"] = [
                {
                    "kind": "evidence_log_read_failed",
                    "reason": str(
                        matched_receipt.get("error")
                        or "evidence log read attempted but failed"
                    ).strip(),
                }
            ]
        return result
    claim = {
        "kind": "required_read_not_executed",
        "reason": reason,
    }
    result["warnings"] = [claim]
    result["rejected_claims"] = [claim]
    return result


def latest_autonomous_replan_ack_for_projection(
    latest_runs: list[dict[str, Any]] | None,
    *,
    neutral_classifications: set[str],
) -> dict[str, Any] | None:
    """Return a recent durable replan ACK within the material review window."""

    material_run_count = 0
    for run in latest_runs or []:
        if not isinstance(run, dict):
            continue
        replan_ack = compact_autonomous_replan_ack(run)
        if replan_ack:
            return replan_ack
        classification = str(run.get("classification") or "").strip()
        if not classification:
            continue
        if classification in neutral_classifications:
            continue
        if classification == "quota_monitor_poll":
            continue
        material_run_count += 1
        if material_run_count >= AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW:
            return None
    return None
