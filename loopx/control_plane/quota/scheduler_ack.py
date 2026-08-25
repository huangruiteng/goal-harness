from __future__ import annotations

from pathlib import Path
from typing import Any

from .decision_summary import compact_quota_decision, quota_decision_agent_id
from ..runtime.time import now_local_iso
from ..scheduler.ack import (
    scheduler_backoff_packet,
)
from ..scheduler.state import (
    CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
    CODEX_APP_SURFACE,
    normalize_scheduler_rrule,
    scheduler_state_path,
    load_scheduler_state,
)
from ..scheduler.heartbeat_commit import (
    commit_scheduler_heartbeat,
    scheduler_state_digest,
)
from ..todos.contract import normalize_todo_claimed_by


QUOTA_SCHEDULER_ACK_CLASSIFICATION = "quota_scheduler_ack"
QUOTA_SCHEDULER_FAILURE_CLASSIFICATION = "quota_scheduler_host_update_failure"


def _commit_scheduler_state(
    *,
    runtime_root: Path,
    goal_id: str,
    agent_id: str,
    surface: str,
    state_key: str,
    outcome: str,
    state: dict[str, Any] | None = None,
    facts: dict[str, Any] | None = None,
    ack: dict[str, Any] | None = None,
    failure: dict[str, Any] | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    current = load_scheduler_state(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        surface=surface,
        state_key=state_key,
    )
    result = commit_scheduler_heartbeat(
        runtime_root=runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        surface=surface,
        state_key=state_key,
        outcome=outcome,
        state=state,
        facts=facts,
        ack=ack,
        failure=failure,
        expected_state_digest=scheduler_state_digest(current),
        execute=execute,
    )
    if result.get("status") == "conflict":
        raise ValueError(
            str(result.get("reason") or "scheduler heartbeat commit conflicted")
        )
    return dict(result)


def _scheduler_hint_facts(
    before: dict[str, Any],
    *,
    stateful_backoff: dict[str, Any],
    codex_app: dict[str, Any],
    generated_at: str,
    source: str,
    applied_rrule: str | None = None,
    expected_rrule: str | None = None,
    observed_host_rrule: str | None = None,
    failure_kind: str | None = None,
    ack_needed: bool | None = None,
    apply_needed: bool | None = None,
    host_match_observed: bool = False,
) -> dict[str, Any]:
    progression_minutes = stateful_backoff.get("progression_minutes")
    if not isinstance(progression_minutes, list) or not progression_minutes:
        progression_minutes = codex_app.get("example_progression_minutes")
    if not isinstance(progression_minutes, list) or not progression_minutes:
        raise ValueError("current scheduler hint has no progression_minutes")
    try:
        progression_index = int(stateful_backoff.get("progression_index") or 0)
    except (TypeError, ValueError):
        raise ValueError(
            "current scheduler hint has an invalid progression_index"
        ) from None
    if progression_index < 0 or progression_index >= len(progression_minutes):
        raise ValueError("current scheduler hint progression_index is out of range")
    reset_token = str(stateful_backoff.get("reset_token") or "").strip()
    identity_signature = str(stateful_backoff.get("identity_signature") or "").strip()
    if not reset_token or not identity_signature:
        raise ValueError("current scheduler hint has incomplete scheduler identity")
    current_rrule = normalize_scheduler_rrule(stateful_backoff.get("current_rrule"))
    prior_failures = stateful_backoff.get("host_update_failures")
    if not isinstance(prior_failures, list):
        prior_failures = []
    legacy_failure = stateful_backoff.get("host_update_failure")
    if isinstance(legacy_failure, dict) and legacy_failure not in prior_failures:
        prior_failures = [*prior_failures, legacy_failure]
    return {
        "progression_minutes": progression_minutes,
        "progression_index": progression_index,
        "reset_token": reset_token,
        "identity_signature": identity_signature,
        "expected_rrule": normalize_scheduler_rrule(expected_rrule) or current_rrule,
        "applied_rrule": normalize_scheduler_rrule(applied_rrule) or current_rrule,
        "observed_host_rrule": normalize_scheduler_rrule(observed_host_rrule),
        "cadence_class": str(
            (before.get("scheduler_hint") or {}).get("cadence_class")
            if isinstance(before.get("scheduler_hint"), dict)
            else "default"
        ),
        "ack_needed": ack_needed,
        "apply_needed": apply_needed,
        "failure_kind": failure_kind,
        "generated_at": generated_at,
        "source": source,
        "host_match_observed": host_match_observed,
        "prior_host_update_failures": prior_failures,
    }


def _project_scheduler_ack_record(
    before: dict[str, Any],
    *,
    result: dict[str, Any],
    applied_rrule: str,
    surface: str,
    state_key: str,
    plan: dict[str, Any],
    generated_at: str,
    reason_summary: str | None,
) -> dict[str, Any]:
    state = result.get("state")
    scheduler_state = (
        {key: value for key, value in state.items() if key != "heartbeat_commit"}
        if isinstance(state, dict)
        else None
    )
    reason = str(reason_summary or "").strip() or (
        f"acknowledged Codex App scheduler RRULE {applied_rrule}; no quota spend"
    )
    event: dict[str, Any] = {
        "event_type": QUOTA_SCHEDULER_ACK_CLASSIFICATION,
        "surface": surface,
        "state_key": state_key,
        "applied_rrule": applied_rrule,
        "before": compact_quota_decision(before),
        "scheduler_state": scheduler_state,
    }
    if result.get("stale_hint_accepted") or plan.get("stale_hint_accepted"):
        event.update(
            {
                "expected_rrule": plan.get("expected_rrule"),
                "stale_hint_accepted": True,
                "stale_hint_tolerance_minutes": plan.get(
                    "stale_hint_tolerance_minutes", 2
                ),
            }
        )
    return {
        "generated_at": generated_at,
        "goal_id": before.get("goal_id"),
        "classification": QUOTA_SCHEDULER_ACK_CLASSIFICATION,
        "agent_id": quota_decision_agent_id(before),
        "recommended_action": reason,
        "health_check": "scheduler ack state updated; no quota spend",
        "delivery_outcome": "surface_only",
        "scheduler_ack_event": event,
    }


def _now_local() -> str:
    return now_local_iso()


def scheduler_ack_failure(
    *,
    goal_id: str,
    agent_id: str | None,
    execute: bool,
    surface: str,
    state_key: str,
    applied_rrule: str | None,
    reason: str,
    before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "mode": "scheduler-ack",
        "dry_run": not execute,
        "goal_id": goal_id,
        "agent_id": normalize_todo_claimed_by(agent_id),
        "surface": surface,
        "state_key": state_key,
        "applied_rrule": applied_rrule,
        "appended": False,
        "registry_mutated": False,
        "reason": reason,
        "before": before,
        "after": None,
    }


def _annotate_current_hint(
    payload: dict[str, Any], *, use_current_hint: bool
) -> dict[str, Any]:
    if use_current_hint:
        payload["used_current_hint"] = True
        payload["current_hint_source"] = "quota.should-run.scheduler_hint"
    return payload


def _resolve_scheduler_ack_current_hint(
    before: dict[str, Any],
    *,
    surface: str,
    applied_rrule: str | None,
    reset_token: str | None,
    identity_signature: str | None,
) -> tuple[str | None, str | None, str | None]:
    scheduler_hint = (
        before.get("scheduler_hint")
        if isinstance(before.get("scheduler_hint"), dict)
        else {}
    )
    surface_packet = (
        scheduler_hint.get(surface)
        if isinstance(scheduler_hint.get(surface), dict)
        else {}
    )
    stateful_backoff = (
        surface_packet.get("stateful_backoff")
        if isinstance(surface_packet.get("stateful_backoff"), dict)
        else {}
    )
    ack_hint = (
        surface_packet.get("ack_hint")
        if isinstance(surface_packet.get("ack_hint"), dict)
        else {}
    )
    ack_args = ack_hint.get("args") if isinstance(ack_hint.get("args"), dict) else {}
    resolved_rrule = (
        str(applied_rrule or "").strip()
        or str(ack_args.get("applied_rrule") or "").strip()
        or str(surface_packet.get("recommended_rrule") or "").strip()
    )
    resolved_reset = (
        str(stateful_backoff.get("reset_token") or "").strip()
        or str(ack_args.get("reset_token") or "").strip()
        or str(reset_token or "").strip()
    )
    resolved_identity = (
        str(stateful_backoff.get("identity_signature") or "").strip()
        or str(ack_args.get("identity_signature") or "").strip()
        or str(identity_signature or "").strip()
    )
    return resolved_rrule, resolved_reset, resolved_identity


def record_quota_scheduler_ack_for_decision(
    before: dict[str, Any],
    *,
    runtime_root: Path,
    goal_id: str,
    agent_id: str | None,
    execute: bool = False,
    surface: str = CODEX_APP_SURFACE,
    state_key: str = CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
    applied_rrule: str | None = None,
    reset_token: str | None = None,
    identity_signature: str | None = None,
    reason_summary: str | None = None,
    generated_at: str | None = None,
    use_current_hint: bool = False,
    host_match_observed: bool = False,
) -> dict[str, Any]:
    safe_agent_id = normalize_todo_claimed_by(agent_id)
    if host_match_observed and (
        not str(applied_rrule or "").strip()
        or not str(reset_token or "").strip()
        or not str(identity_signature or "").strip()
    ):
        return scheduler_ack_failure(
            goal_id=goal_id,
            agent_id=safe_agent_id,
            execute=execute,
            surface=surface,
            state_key=state_key,
            applied_rrule=applied_rrule,
            reason=(
                "host-match scheduler ACK requires applied RRULE, reset token, "
                "and identity signature"
            ),
            before=before,
        )
    if use_current_hint and not host_match_observed:
        applied_rrule, reset_token, identity_signature = (
            _resolve_scheduler_ack_current_hint(
                before,
                surface=surface,
                applied_rrule=applied_rrule,
                reset_token=reset_token,
                identity_signature=identity_signature,
            )
        )
    _, codex_app, stateful_backoff = scheduler_backoff_packet(before)
    if not safe_agent_id:
        return _annotate_current_hint(
            scheduler_ack_failure(
                goal_id=goal_id,
                agent_id=safe_agent_id,
                execute=execute,
                surface=surface,
                state_key=state_key,
                applied_rrule=applied_rrule,
                reason="`loopx quota scheduler-ack` requires --agent-id",
                before=before,
            ),
            use_current_hint=use_current_hint,
        )
    if str(stateful_backoff.get("state_key") or "") != state_key:
        reason = "--state-key does not match the current scheduler hint"
        return _annotate_current_hint(
            scheduler_ack_failure(
                goal_id=goal_id,
                agent_id=safe_agent_id,
                execute=execute,
                surface=surface,
                state_key=state_key,
                applied_rrule=applied_rrule,
                reason=reason,
                before=before,
            ),
            use_current_hint=use_current_hint,
        )
    if reset_token and str(reset_token).strip() != str(
        stateful_backoff.get("reset_token") or ""
    ):
        reason = "--reset-token does not match the current scheduler hint"
        return _annotate_current_hint(
            scheduler_ack_failure(
                goal_id=goal_id,
                agent_id=safe_agent_id,
                execute=execute,
                surface=surface,
                state_key=state_key,
                applied_rrule=applied_rrule,
                reason=reason,
                before=before,
            ),
            use_current_hint=use_current_hint,
        )
    if identity_signature and str(identity_signature).strip() != str(
        stateful_backoff.get("identity_signature") or ""
    ):
        reason = "--identity-signature does not match the current scheduler hint"
        return _annotate_current_hint(
            scheduler_ack_failure(
                goal_id=goal_id,
                agent_id=safe_agent_id,
                execute=execute,
                surface=surface,
                state_key=state_key,
                applied_rrule=applied_rrule,
                reason=reason,
                before=before,
            ),
            use_current_hint=use_current_hint,
        )
    safe_generated_at = generated_at or _now_local()
    apply_needed = stateful_backoff.get("apply_needed") is True
    ack_needed = stateful_backoff.get("ack_needed") is True
    expected_rrule = normalize_scheduler_rrule(
        codex_app.get("recommended_rrule") or stateful_backoff.get("current_rrule")
    )
    applied_rrule = normalize_scheduler_rrule(applied_rrule)
    if (apply_needed or ack_needed) and not applied_rrule:
        return _annotate_current_hint(
            scheduler_ack_failure(
                goal_id=goal_id,
                agent_id=safe_agent_id,
                execute=execute,
                surface=surface,
                state_key=state_key,
                applied_rrule=applied_rrule,
                reason=(
                    "`loopx quota scheduler-ack` requires --applied-rrule "
                    "when an ack is needed"
                ),
                before=before,
            ),
            use_current_hint=use_current_hint,
        )
    ack_plan = {
        "expected_rrule": expected_rrule,
        "applied_rrule": applied_rrule,
        "host_match_ack": ack_needed and not apply_needed,
    }
    try:
        facts = _scheduler_hint_facts(
            before,
            stateful_backoff=stateful_backoff,
            codex_app=codex_app,
            generated_at=safe_generated_at,
            source=QUOTA_SCHEDULER_ACK_CLASSIFICATION,
            applied_rrule=applied_rrule,
            expected_rrule=expected_rrule,
            ack_needed=ack_needed,
            apply_needed=apply_needed,
            host_match_observed=host_match_observed,
        )
    except ValueError as exc:
        return _annotate_current_hint(
            scheduler_ack_failure(
                goal_id=goal_id,
                agent_id=safe_agent_id,
                execute=execute,
                surface=surface,
                state_key=state_key,
                applied_rrule=applied_rrule,
                reason=str(exc),
                before=before,
            ),
            use_current_hint=use_current_hint,
        )

    state_path = scheduler_state_path(
        runtime_root,
        goal_id=goal_id,
        agent_id=safe_agent_id,
        surface=surface,
        state_key=state_key,
    )
    try:
        scheduler_commit = _commit_scheduler_state(
            runtime_root=runtime_root,
            goal_id=goal_id,
            agent_id=safe_agent_id,
            surface=surface,
            state_key=state_key,
            outcome="ack",
            facts=facts,
            ack={
                "applied_rrule": facts["applied_rrule"],
                "expected_rrule": expected_rrule,
                "stale_hint_accepted": False,
                "stale_hint_tolerance_minutes": int(
                    ack_plan.get("stale_hint_tolerance_minutes", 2)
                ),
                "classification": QUOTA_SCHEDULER_ACK_CLASSIFICATION,
            },
            execute=execute,
        )
    except ValueError as exc:
        return _annotate_current_hint(
            scheduler_ack_failure(
                goal_id=goal_id,
                agent_id=safe_agent_id,
                execute=execute,
                surface=surface,
                state_key=state_key,
                applied_rrule=applied_rrule,
                reason=str(exc),
                before=before,
            ),
            use_current_hint=use_current_hint,
        )

    record = _project_scheduler_ack_record(
        before,
        result=scheduler_commit,
        applied_rrule=str(facts["applied_rrule"]),
        surface=surface,
        state_key=state_key,
        plan=ack_plan,
        generated_at=safe_generated_at,
        reason_summary=reason_summary,
    )
    already_applied = scheduler_commit.get("status") == "skipped"
    output_before = compact_quota_decision(before) if execute else before
    payload = {
        "ok": True,
        "mode": "scheduler-ack",
        "dry_run": not execute,
        "goal_id": goal_id,
        "agent_id": safe_agent_id,
        "surface": surface,
        "state_key": state_key,
        "applied_rrule": record["scheduler_ack_event"]["applied_rrule"],
        "classification": QUOTA_SCHEDULER_ACK_CLASSIFICATION,
        "generated_at": safe_generated_at,
        "appended": False,
        "registry_mutated": False,
        "scheduler_state_mutated": execute
        and scheduler_commit.get("status")
        in {
            "written",
            "replayed",
        },
        "scheduler_commit": scheduler_commit,
        "already_applied": already_applied,
        "scheduler_ack_event": record["scheduler_ack_event"],
        "health_check": record["health_check"],
        "delivery_outcome": record["delivery_outcome"],
        "scheduler_state_path": str(state_path),
        "before": output_before,
        # Preserve the legacy CLI projection for a no-op ACK. Older callers
        # use `after` to carry the unchanged compact decision in this case.
        "after": output_before if already_applied else None,
        "post_ack_contract": {
            "next_action": "wait_for_next_scheduler_tick_or_material_state_transition",
            "do_not_apply_successor_rrule_from_ack_response": True,
            "next_rrule_source": "future_quota_should-run_only",
        },
        "reason": (
            f"{'updated' if execute else 'dry-run preview'} scheduler state ack: "
            f"{goal_id}/{safe_agent_id} applied "
            f"{record['scheduler_ack_event']['applied_rrule']}"
        ),
    }
    if ack_plan.get("host_match_ack"):
        payload["host_match_ack"] = True
        payload["reason"] = (
            f"{'updated' if execute else 'dry-run preview'} scheduler state from "
            f"matching host RRULE: {goal_id}/{safe_agent_id} observed "
            f"{record['scheduler_ack_event']['applied_rrule']}"
        )
    if use_current_hint:
        payload["used_current_hint"] = True
        payload["current_hint_source"] = "quota.should-run.scheduler_hint"
    return payload


def record_quota_scheduler_failure_for_decision(
    before: dict[str, Any],
    *,
    runtime_root: Path,
    goal_id: str,
    agent_id: str | None,
    execute: bool = False,
    surface: str = CODEX_APP_SURFACE,
    state_key: str = CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
    failed_rrule: str | None = None,
    observed_host_rrule: str | None = None,
    failure_kind: str = "host_tool_failure",
    generated_at: str | None = None,
) -> dict[str, Any]:
    safe_agent_id = normalize_todo_claimed_by(agent_id)
    if not safe_agent_id:
        return scheduler_ack_failure(
            goal_id=goal_id,
            agent_id=agent_id,
            execute=execute,
            surface=surface,
            state_key=state_key,
            applied_rrule=failed_rrule,
            reason="quota scheduler-fail-current requires a scoped --agent-id",
            before=before,
        )
    _, codex_app, stateful_backoff = scheduler_backoff_packet(before)
    target_rrule = normalize_scheduler_rrule(
        failed_rrule
        or codex_app.get("recommended_rrule")
        or stateful_backoff.get("current_rrule")
    )
    current_rrule = normalize_scheduler_rrule(stateful_backoff.get("current_rrule"))
    host_observation = (
        stateful_backoff.get("host_observation")
        if isinstance(stateful_backoff.get("host_observation"), dict)
        else {}
    )
    observed_rrule = normalize_scheduler_rrule(
        observed_host_rrule or host_observation.get("current_rrule")
    )
    if str(stateful_backoff.get("state_key") or "") != state_key:
        reason = "--state-key does not match the current scheduler hint"
    elif stateful_backoff.get("apply_needed") is not True:
        reason = (
            "scheduler host update failure is not recordable because no host "
            "update is needed"
        )
    elif not target_rrule or target_rrule != current_rrule:
        reason = "--failed-rrule does not match the current scheduler target"
    else:
        reason = ""
    if reason:
        payload = scheduler_ack_failure(
            goal_id=goal_id,
            agent_id=safe_agent_id,
            execute=execute,
            surface=surface,
            state_key=state_key,
            applied_rrule=target_rrule,
            reason=reason,
            before=before,
        )
        payload["mode"] = "scheduler-fail-current"
        payload["failed_rrule"] = target_rrule
        return payload

    safe_generated_at = generated_at or _now_local()
    try:
        facts = _scheduler_hint_facts(
            before,
            stateful_backoff=stateful_backoff,
            codex_app=codex_app,
            generated_at=safe_generated_at,
            source=QUOTA_SCHEDULER_FAILURE_CLASSIFICATION,
            expected_rrule=target_rrule,
            applied_rrule=observed_rrule,
            observed_host_rrule=observed_rrule,
            failure_kind=str(failure_kind or "host_tool_failure").strip(),
            apply_needed=stateful_backoff.get("apply_needed") is True,
        )
    except ValueError as exc:
        payload = scheduler_ack_failure(
            goal_id=goal_id,
            agent_id=safe_agent_id,
            execute=execute,
            surface=surface,
            state_key=state_key,
            applied_rrule=target_rrule,
            reason=str(exc),
            before=before,
        )
        payload["mode"] = "scheduler-fail-current"
        payload["failed_rrule"] = target_rrule
        return payload
    state_path = scheduler_state_path(
        runtime_root,
        goal_id=goal_id,
        agent_id=safe_agent_id,
        surface=surface,
        state_key=state_key,
    )
    try:
        scheduler_commit = _commit_scheduler_state(
            runtime_root=runtime_root,
            goal_id=goal_id,
            agent_id=safe_agent_id,
            surface=surface,
            state_key=state_key,
            outcome="failure",
            facts=facts,
            failure={
                "target_rrule": target_rrule,
                "observed_host_rrule": observed_rrule,
                "failure_kind": facts["failure_kind"],
                "apply_needed": facts["apply_needed"],
            },
            execute=execute,
        )
    except ValueError as exc:
        payload = scheduler_ack_failure(
            goal_id=goal_id,
            agent_id=safe_agent_id,
            execute=execute,
            surface=surface,
            state_key=state_key,
            applied_rrule=target_rrule,
            reason=str(exc),
            before=before,
        )
        payload["mode"] = "scheduler-fail-current"
        payload["failed_rrule"] = target_rrule
        return payload
    committed_state = scheduler_commit.get("state")
    scheduler_state = (
        {
            key: value
            for key, value in committed_state.items()
            if key != "heartbeat_commit"
        }
        if isinstance(committed_state, dict)
        else None
    )
    failure_record = (
        scheduler_state.get("host_update_failure")
        if isinstance(scheduler_state, dict)
        and isinstance(scheduler_state.get("host_update_failure"), dict)
        else None
    )
    return {
        "ok": True,
        "mode": "scheduler-fail-current",
        "dry_run": not execute,
        "goal_id": goal_id,
        "agent_id": safe_agent_id,
        "surface": surface,
        "state_key": state_key,
        "failed_rrule": target_rrule,
        "observed_host_rrule": observed_rrule,
        "failure_kind": facts["failure_kind"],
        "classification": QUOTA_SCHEDULER_FAILURE_CLASSIFICATION,
        "generated_at": safe_generated_at,
        "appended": False,
        "registry_mutated": False,
        "scheduler_state_mutated": execute
        and scheduler_commit.get("status")
        in {
            "written",
            "replayed",
        },
        "scheduler_commit": scheduler_commit,
        "scheduler_failure_event": {
            "event_type": QUOTA_SCHEDULER_FAILURE_CLASSIFICATION,
            "surface": surface,
            "state_key": state_key,
            "before": compact_quota_decision(before),
            "scheduler_state": scheduler_state,
            "host_update_failure": failure_record,
        },
        "scheduler_state_path": str(state_path),
        "health_check": (
            "scheduler host update failure cached; repeated retained target/host "
            "pairs suppressed; no quota spend"
        ),
        "delivery_outcome": "surface_only",
        "before": compact_quota_decision(before) if execute else before,
        "after": None,
        "failure_count": scheduler_commit.get("failure_count"),
        "reason": (
            f"{'recorded' if execute else 'dry-run preview'} scheduler host update "
            f"failure for {goal_id}/{safe_agent_id}: {target_rrule}"
        ),
    }
