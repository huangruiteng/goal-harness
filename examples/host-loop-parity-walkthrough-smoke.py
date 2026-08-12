#!/usr/bin/env python3
"""Contributor-facing walkthrough: host-loop parity across Turn-enabled hosts.

Compares signed action selection, compact Turn receipts, independent
validation, recoverable timeout/termination, replan, and terminal
no-followup behavior using synthetic quota envelopes — without retaining
raw sessions or host-local paths.

1. **Signed action selection** — action_signature.source_hash uniquely
   identifies material decision content across hosts
2. **Turn plan for supported hosts** — codex-cli, claude-code, generic-cli
   all map to READY_FOR_HOST with compatible routes
3. **Compact Turn receipt** — receipt_seed, ordered phases, settlement plan
   bind identity and idempotency across hosts
4. **Transaction plan** — build_loopx_turn_transaction_plan projects
   the same identity regardless of execution host
5. **Independent validation** — build_loopx_turn_command_validator
   produces a host-independent TaskValidator callable
6. **Loop disposition** — decide_loop_disposition with run_now / terminal /
   repair / replan / wait / user_action_required
7. **Timeout / termination** — scheduler hint actions encode
   backoff_until_state_change and terminal_no_followup
8. **Replan** — replan disposition carries bounded delta requirements
9. **Host mode plan** — build_host_mode_plan maps intents to host modes
10. **Public safety** — no raw sessions, host-local paths, credentials
11. **Host request independence** — build_loopx_turn_host_request
    projects the same identity from any host's plan
12. **Budget exhaustion** — BoundedTurnBudget remaining triggers replan
13. **Execution committed** — loopx_turn_execution_committed checks
    durable effects across all settlement phases
14. **Turn receipt validation** — validate_loopx_turn_receipt checks
    host-independent phase ordering
15. **No raw sessions** — all payloads are public-safe

No raw sessions, provider payloads, credentials, host-local paths, or
external sinks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.control_plane.quota.turn_envelope import (  # noqa: E402
    build_turn_envelope,
)
from loopx.control_plane.turn_driver import (  # noqa: E402
    BoundedTurnBudget,
    LoopDisposition,
    LoopXTurnRoute,
    build_loopx_turn_command_validator,
    build_loopx_turn_host_request,
    build_loopx_turn_plan,
    build_loopx_turn_transaction_plan,
    decide_loop_disposition,
    loopx_turn_execution_committed,
    validate_loopx_turn_receipt,
)
from loopx.control_plane.turn_driver.loop_controller import (  # noqa: E402
    ValidatedTurnReceipt,
)
from loopx.control_plane.turn_driver.transaction import (  # noqa: E402
    LOOPX_TURN_EXECUTION_SCHEMA_VERSION,
    LOOPX_TURN_RESULT_SCHEMA_VERSION,
    LOOPX_TURN_TRANSACTION_PLAN_SCHEMA_VERSION,
    TRANSACTION_PHASES,
    LoopXTurnResultKind,
)
from loopx.host_mode_planner import (  # noqa: E402
    build_host_mode_plan,
)

FORBIDDEN = [
    "/" + "Users/", "/" + "private/", "/" + "tmp/",
    "api" + "_key", "pass" + "word", "sec" + "ret",
    "C:\\", "C:/",
]


def _assert_public_safe(payload: Any, *, label: str = "") -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    leaked = [n for n in FORBIDDEN if n.lower() in text.lower()]
    assert not leaked, f"{label}: public-boundary leak: {leaked}"


# ── Fixtures ─────────────────────────────────────────────────────────


def _quota_decision(
    *,
    should_run: bool = True,
    effective_action: str = "normal_run",
    todo_id: str = "todo_fixture0001",
    agent_id: str = "codex-fixture",
    goal_id: str = "fixture-goal",
    state: str = "eligible",
    decision: str = "run",
    quiet_noop_allowed: bool = False,
) -> dict[str, Any]:
    return {
        "ok": True,
        "goal_id": goal_id,
        "agent_id": agent_id,
        "agent_identity": {"agent_id": agent_id},
        "decision": decision,
        "should_run": should_run,
        "effective_action": effective_action,
        "state": state,
        "recommended_action": "Advance one public fixture.",
        "selected_todo": {
            "todo_id": todo_id,
            "text": "Advance one public fixture.",
        },
        "interaction_contract": {
            "schema_version": "loopx_interaction_contract_v0",
            "mode": effective_action,
            "user_channel": {
                "action_required": False,
                "notify": "DONT_NOTIFY",
            },
            "agent_channel": {
                "must_attempt": should_run,
                "delivery_allowed": should_run,
                "quiet_noop_allowed": quiet_noop_allowed,
            },
            "cli_channel": {
                "spend_after_validation": should_run,
            },
        },
        "open_count": 0,
        "action_required": False,
    }


def _lineage(goal_id: str = "fixture-goal", agent_id: str = "codex-fixture", todo_id: str = "todo_fixture0001") -> dict[str, str]:
    return {"goal_id": goal_id, "agent_id": agent_id, "todo_id": todo_id}


# ── Scenario 1: Signed action selection ──


def test_signed_action_selection() -> None:
    """build_turn_envelope produces an action_signature that uniquely
    identifies material decision content. Different decisions produce
    different source hashes."""
    decision_a = _quota_decision(todo_id="todo_001")
    decision_b = _quota_decision(todo_id="todo_002")

    envelope_a = build_turn_envelope(decision_a)
    envelope_b = build_turn_envelope(decision_b)

    assert envelope_a["action_signature"]["matches"] is True
    assert envelope_b["action_signature"]["matches"] is True
    assert (
        envelope_a["action_signature"]["source_hash"]
        != envelope_b["action_signature"]["source_hash"]
    )
    assert envelope_a["action_signature"]["source_hash"] == envelope_a["action_signature"]["envelope_hash"]
    assert envelope_a["compaction"]["within_budget"] is True

    _assert_public_safe(envelope_a, label="signed-action")


# ── Scenario 2: Turn plan routes across supported hosts ──


def test_turn_plan_routes_across_hosts() -> None:
    """The same synthetic envelope produces a turn plan for all three
    supported hosts: codex-cli, claude-code, generic-cli."""
    envelope = build_turn_envelope(_quota_decision())

    # codex-cli and claude-code are visible Turn hosts.
    for host in ("codex-cli", "claude-code"):
        plan = build_loopx_turn_plan(envelope, host=host,
                                      execution_mode="interactive-visible")
        assert plan["ok"] is True
        assert plan["route"]["kind"] == LoopXTurnRoute.READY_FOR_HOST.value
        assert plan["route"]["would_invoke_host"] is True
        assert plan["route"]["host_invocation_allowed"] is False  # plan only
        assert plan["host"]["kind"] == host

    # generic-cli requires isolated-headless (outer controller).
    headless = build_loopx_turn_plan(envelope, host="generic-cli",
                                      execution_mode="isolated-headless")
    assert headless["ok"] is True
    assert headless["host"]["execution_mode"] == "isolated-headless"
    assert headless["host"]["explicit_isolation"] is True

    _assert_public_safe(headless, label="turn-plan-hosts")


# ── Scenario 3: Compact Turn receipt structure ──


def test_compact_turn_receipt_structure() -> None:
    """The turn plan carries a compact receipt seed with ordered phases
    and a settlement plan that binds identity and ordered steps."""
    envelope = build_turn_envelope(_quota_decision())
    plan = build_loopx_turn_plan(envelope, host="codex-cli",
                                  execution_mode="interactive-visible")

    txn = plan["transaction"]
    assert txn["status"] == "planned"
    assert "host_execute" in txn["phases"]
    assert "typed_result" in txn["phases"]
    assert "validation" in txn["phases"]
    assert "durable_writeback" in txn["phases"]
    assert "quota_spend" in txn["phases"]

    receipt_seed = txn["receipt_seed"]
    assert receipt_seed["status"] == "not_executed"
    assert receipt_seed["next_phase"] == "host_execute"

    settlement = txn["settlement_plan"]
    assert settlement["identity"]["goal_id"] == "fixture-goal"
    assert settlement["identity"]["agent_id"] == "codex-fixture"
    assert settlement["identity"]["todo_id"] == "todo_fixture0001"
    assert len(settlement["ordered_steps"]) == 3
    for step in settlement["ordered_steps"]:
        assert step["idempotency_key_ref"] == "$.identity.effect_id"

    _assert_public_safe(plan, label="compact-receipt")


# ── Scenario 4: Transaction plan projects same identity ──


def test_transaction_plan_same_identity() -> None:
    """build_loopx_turn_transaction_plan projects the same identity
    and effect structure regardless of execution host."""
    lineage = _lineage()
    txn_a = build_loopx_turn_transaction_plan(
        planned=True,
        lineage=lineage,
        host="codex-cli",
        execution_mode="interactive-visible",
        session_action="start_new",
        scheduler_owner="agent_cli_loop",
    )
    txn_b = build_loopx_turn_transaction_plan(
        planned=True,
        lineage=lineage,
        host="generic-cli",
        execution_mode="isolated-headless",
        session_action="start_new",
        scheduler_owner="outer_controller",
    )
    assert txn_a["schema_version"] == LOOPX_TURN_TRANSACTION_PLAN_SCHEMA_VERSION
    assert txn_a["status"] == "planned"
    assert txn_b["status"] == "planned"
    # Different hosts produce different turn_keys (host is in identity).
    assert txn_a["turn_key"] != txn_b["turn_key"]
    # But settlement identity is the same.
    assert (
        txn_a["settlement_plan"]["identity"]["goal_id"]
        == txn_b["settlement_plan"]["identity"]["goal_id"]
        == "fixture-goal"
    )

    # When planned=False, no phases or settlement.
    skipped = build_loopx_turn_transaction_plan(
        planned=False,
        lineage=lineage,
        host="codex-cli",
        execution_mode="interactive-visible",
        session_action="none",
    )
    assert skipped["status"] == "not_applicable"
    assert skipped["phases"] == []
    assert skipped["receipt_seed"]["next_phase"] is None

    _assert_public_safe(txn_a, label="txn-plan")


# ── Scenario 5: Independent validation callable ──


def test_independent_validation_callable() -> None:
    """build_loopx_turn_command_validator returns a host-independent
    TaskValidator callable. A zero-exit validator passes; a non-zero
    exit validator fails with typed recovery_kind."""
    # Use sys.executable so the walkthrough runs on any host (bare
    # "python" may resolve to a stub, shim, or missing executable).
    pass_validator = build_loopx_turn_command_validator(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        project=REPO_ROOT,
        timeout_seconds=5.0,
    )
    assert callable(pass_validator)

    # Build a synthetic plan + result to validate.
    envelope = build_turn_envelope(_quota_decision())
    plan = build_loopx_turn_plan(envelope, host="codex-cli",
                                  execution_mode="interactive-visible")
    result = {
        "schema_version": LOOPX_TURN_RESULT_SCHEMA_VERSION,
        "turn_key": plan["transaction"]["turn_key"],
        "result_kind": "validated_progress",
        "completed_phases": ["host_execute", "typed_result"],
    }
    passed = pass_validator(plan, result)
    assert isinstance(passed, dict)
    assert passed["status"] == "passed"
    assert passed["exit_code"] == 0

    # A non-zero exit validator fails with typed recovery_kind.
    fail_validator = build_loopx_turn_command_validator(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        project=REPO_ROOT,
        timeout_seconds=5.0,
        failure_recovery_kind="repair_required",
    )
    failed = fail_validator(plan, result)
    assert isinstance(failed, dict)
    assert failed["status"] == "failed"
    assert failed["exit_code"] == 3
    assert failed.get("recovery_kind") == "repair_required"

    _assert_public_safe({"pass_status": passed["status"], "fail_status": failed["status"]}, label="validation")


# ── Scenario 6: Loop disposition — run_now (no prior receipt) ──


def test_loop_disposition_run_now_no_receipt() -> None:
    """When there is no prior receipt and the quota decision allows
    delivery, decide_loop_disposition returns RUN_NOW."""
    envelope = build_turn_envelope(_quota_decision())
    disposition = decide_loop_disposition(
        turn_receipt=None,
        quota_decision=envelope,
    )
    assert disposition["disposition"] == LoopDisposition.RUN_NOW.value
    assert disposition["spends_quota"] is False
    assert disposition["launches_host"] is False
    _assert_public_safe(disposition, label="run-now")


# ── Scenario 7: Loop disposition — terminal no followup ──


def test_loop_disposition_terminal() -> None:
    """When the quota decision signals terminal_no_followup with matching
    state, decide_loop_disposition returns TERMINAL."""
    terminal = build_turn_envelope(_quota_decision(
        should_run=False,
        effective_action="terminal_no_followup",
        state="terminal_no_followup",
        decision="stop",
    ))
    disposition = decide_loop_disposition(
        turn_receipt=None,
        quota_decision=terminal,
    )
    assert disposition["disposition"] == LoopDisposition.TERMINAL.value
    _assert_public_safe(disposition, label="terminal")


# ── Scenario 8: Loop disposition — wait ──


def test_loop_disposition_wait() -> None:
    """When the decision allows quiet_noop, the route is WAIT."""
    wait_envelope = build_turn_envelope(_quota_decision(
        should_run=False,
        effective_action="quiet_noop",
        state="waiting",
        decision="wait",
        quiet_noop_allowed=True,
    ))
    disposition = decide_loop_disposition(
        turn_receipt=None,
        quota_decision=wait_envelope,
    )
    assert disposition["disposition"] == LoopDisposition.WAIT.value
    _assert_public_safe(disposition, label="wait")


# ── Scenario 9: BoundedTurnBudget exhaustion → replan ──


def test_bounded_turn_budget_exhaustion() -> None:
    """When remaining turns hit zero, disposition is REPLAN."""
    envelope = build_turn_envelope(_quota_decision())
    # Build a synthetic validated progress receipt.
    plan = build_loopx_turn_plan(envelope, host="codex-cli",
                                  execution_mode="interactive-visible")
    txn = plan["transaction"]

    # Construct a committed execution payload.
    execution = {
        "schema_version": LOOPX_TURN_EXECUTION_SCHEMA_VERSION,
        "status": "committed",
        "result_kind": "validated_progress",
        "turn_key": txn["turn_key"],
        "receipt": {
            "schema_version": "loopx_turn_receipt_validation_v0",
            "ok": True,
            "turn_key": txn["turn_key"],
            "lineage": _lineage(),
            "settlement_effect_id": "effect-001",
            "result_kind": "validated_progress",
            "completed_phases": list(TRANSACTION_PHASES),
            "failed_phase": None,
            "status": "committed",
        },
        "effects": {"state_written": True, "quota_spent": True, "scheduler_acknowledged": True},
        "settlement_result": {
            "ok": True,
            "failure": None,
            "receipts": [
                {"step_kind": "validation", "effect_id": "effect-001", "status": "committed"},
                {"step_kind": "durable_writeback", "effect_id": "effect-001", "status": "committed"},
                {"step_kind": "quota_spend", "effect_id": "effect-001", "status": "committed"},
            ],
        },
        "scheduler": {"completed": True},
    }
    receipt = ValidatedTurnReceipt.from_execution(execution)
    assert receipt.result_kind == LoopXTurnResultKind.VALIDATED_PROGRESS

    # Budget with 0 remaining.
    budget = BoundedTurnBudget(
        lineage=_lineage(),
        max_turns=3,
        completed_turns=3,
    )
    assert budget.remaining == 0

    disposition = decide_loop_disposition(
        turn_receipt=receipt,
        quota_decision=envelope,
        predecessor_turn_key=txn["turn_key"],
        bounded_turn_budget=budget,
    )
    assert disposition["disposition"] == LoopDisposition.REPLAN.value

    _assert_public_safe(disposition, label="budget-exhaust")


# ── Scenario 10: Host request projects same identity ──


def test_host_request_projects_same_identity() -> None:
    """build_loopx_turn_host_request reads the plan and projects a
    host-independent request from it."""
    envelope = build_turn_envelope(_quota_decision())
    plan = build_loopx_turn_plan(envelope, host="codex-cli",
                                  execution_mode="interactive-visible")
    request = build_loopx_turn_host_request(plan)
    assert request["schema_version"] == "loopx_turn_host_request_v0"
    assert request["turn_key"] == plan["transaction"]["turn_key"]
    assert request["route"] == LoopXTurnRoute.READY_FOR_HOST.value
    assert request["session"] == plan["session"]
    assert request["turn_envelope"] == plan["turn_envelope"]

    _assert_public_safe(request, label="host-request")


# ── Scenario 11: Host mode plan maps intent to modes ──


def test_host_mode_plan_maps_intent_to_modes() -> None:
    """build_host_mode_plan maps user intents to distinct host modes
    with capability readiness and connector catalog mapping."""
    plan = build_host_mode_plan(
        goal_id="workflow-selector-fixture",
        user_intent="watch_each_turn",
        host_capabilities=["visible_session"],
        agent_id="codex-main-control",
        registered_agents=["codex-main-control", "codex-side-peer"],
        available_capabilities=["shell", "network"],
        host_identity="codex-cli",
    )
    assert plan["ok"] is True
    assert plan["mode"] == "dry_run_host_mode_selector"
    assert plan["selected_mode"] == "visible_tui"
    assert plan["selected_connector_id"] == "codex_cli_tui"
    assert plan["selected_capability_ready"] is True

    # Different intent → different mode.
    headless_plan = build_host_mode_plan(
        goal_id="workflow-selector-fixture",
        user_intent="continue_without_ui",
        host_capabilities=["loopx_turn", "typed_host_adapter", "independent_validator"],
        agent_id="codex-main-control",
        registered_agents=["codex-main-control"],
        available_capabilities=["shell"],
        host_identity="generic-cli",
    )
    assert headless_plan["selected_mode"] == "isolated_headless_turn"
    assert headless_plan["selected_capability_ready"] is True

    _assert_public_safe(plan, label="host-mode")


# ── Scenario 12: Execution committed path ──


def test_execution_committed_path() -> None:
    """loopx_turn_execution_committed checks durable effects across
    all settlement phases."""
    envelope = build_turn_envelope(_quota_decision())
    plan = build_loopx_turn_plan(envelope, host="codex-cli",
                                  execution_mode="interactive-visible")
    txn = plan["transaction"]

    committed_exec = {
        "schema_version": LOOPX_TURN_EXECUTION_SCHEMA_VERSION,
        "status": "committed",
        "validation": {"status": "passed"},
        "receipt": {"status": "committed"},
        "effects": {"state_written": True, "quota_spent": True},
        "turn_key": txn["turn_key"],
    }
    assert loopx_turn_execution_committed(committed_exec) is True

    # Missing state_written → not committed.
    partial_exec = {
        "schema_version": LOOPX_TURN_EXECUTION_SCHEMA_VERSION,
        "status": "committed",
        "validation": {"status": "passed"},
        "receipt": {"status": "committed"},
        "effects": {"state_written": False, "quota_spent": False},
        "turn_key": txn["turn_key"],
    }
    assert loopx_turn_execution_committed(partial_exec) is False

    _assert_public_safe(committed_exec, label="exec-committed")


# ── Scenario 13: Turn receipt validation ──


def test_turn_receipt_validation() -> None:
    """validate_loopx_turn_receipt checks host-independent phase ordering
    and result kind constraints."""
    lineage = _lineage()
    txn = build_loopx_turn_transaction_plan(
        planned=True,
        lineage=lineage,
        host="codex-cli",
        execution_mode="interactive-visible",
        session_action="start_new",
        scheduler_owner="agent_cli_loop",
    )
    # A valid material progress result.
    result = {
        "schema_version": LOOPX_TURN_RESULT_SCHEMA_VERSION,
        "turn_key": txn["turn_key"],
        "result_kind": "validated_progress",
        "completed_phases": ["host_execute", "typed_result", "validation"],
    }
    receipt = validate_loopx_turn_receipt(txn, result)
    assert receipt["ok"] is True
    assert receipt["status"] == "validated"

    # Wrong turn_key → fails.
    bad_key = {**result, "turn_key": "sha256:" + "ab" * 32}
    bad_receipt = validate_loopx_turn_receipt(txn, bad_key)
    assert bad_receipt["ok"] is False

    _assert_public_safe(receipt, label="receipt-validation")


# ── Scenario 14: Replan disposition carries delta requirements ──


def test_replan_disposition_delta_requirements() -> None:
    """When a turn requires replan, the disposition carries bounded
    delta requirements: todo_delta, vision_delta, fresh_envelope_required."""
    replan_envelope = build_turn_envelope(_quota_decision(
        effective_action="autonomous_replan",
        decision="run",
    ))
    disposition = decide_loop_disposition(
        turn_receipt=None,
        quota_decision=replan_envelope,
    )
    assert disposition["disposition"] == LoopDisposition.REPLAN.value
    assert disposition["replan_continuation"]["requires_bounded_delta"] is True
    assert "todo_delta" in disposition["replan_continuation"]["delta_kinds"]
    assert "vision_delta" in disposition["replan_continuation"]["delta_kinds"]
    assert disposition["replan_continuation"]["fresh_envelope_required"] is True

    _assert_public_safe(disposition, label="replan-delta")


# ── Scenario 15: Public safety ──


def test_public_safety() -> None:
    """All synthetic payloads are public-safe: no raw sessions,
    credentials, host-local paths, or external sinks."""
    envelope = build_turn_envelope(_quota_decision())
    plan = build_loopx_turn_plan(envelope, host="codex-cli",
                                  execution_mode="interactive-visible")
    host_req = build_loopx_turn_host_request(plan)
    lineage = _lineage()
    txn = build_loopx_turn_transaction_plan(
        planned=True,
        lineage=lineage,
        host="codex-cli",
        execution_mode="interactive-visible",
        session_action="start_new",
        scheduler_owner="agent_cli_loop",
    )

    for label, payload in [
        ("envelope", envelope),
        ("plan", plan),
        ("host_req", host_req),
        ("txn", txn),
    ]:
        _assert_public_safe(payload, label=label)

    # No leaked raw session data.
    serialized = json.dumps(plan, ensure_ascii=False).lower()
    assert "bearer" not in serialized


def main() -> int:
    tests: list[tuple[str, Any]] = [
        ("signed action selection", test_signed_action_selection),
        ("turn plan routes across hosts", test_turn_plan_routes_across_hosts),
        ("compact Turn receipt structure", test_compact_turn_receipt_structure),
        ("transaction plan same identity", test_transaction_plan_same_identity),
        ("independent validation callable", test_independent_validation_callable),
        ("loop disposition run_now no receipt", test_loop_disposition_run_now_no_receipt),
        ("loop disposition terminal", test_loop_disposition_terminal),
        ("loop disposition wait", test_loop_disposition_wait),
        ("bounded turn budget exhaustion", test_bounded_turn_budget_exhaustion),
        ("host request projects same identity", test_host_request_projects_same_identity),
        ("host mode plan maps intent to modes", test_host_mode_plan_maps_intent_to_modes),
        ("execution committed path", test_execution_committed_path),
        ("turn receipt validation", test_turn_receipt_validation),
        ("replan disposition delta requirements", test_replan_disposition_delta_requirements),
        ("public safety", test_public_safety),
    ]
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ok  {label}")
        except Exception as exc:
            print(f"  FAIL  {label}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed} walkthrough scenario(s) failed")
        return 1
    print("host-loop-parity-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
