"""Thin pytest: turn driver — signed action, disposition routing, transaction
plan identity, independent validation, execution committed, replan deltas.

Covers GH-C70 core assertions.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from loopx.control_plane.quota.turn_envelope import build_turn_envelope
from loopx.control_plane.turn_driver import (
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
from loopx.control_plane.turn_driver.loop_controller import ValidatedTurnReceipt
from loopx.control_plane.turn_driver.transaction import (
    LOOPX_TURN_EXECUTION_SCHEMA_VERSION,
    LOOPX_TURN_RESULT_SCHEMA_VERSION,
    LOOPX_TURN_TRANSACTION_PLAN_SCHEMA_VERSION,
    TRANSACTION_PHASES,
    LoopXTurnResultKind,
)
from loopx.host_mode_planner import build_host_mode_plan

REPO_ROOT = Path(__file__).resolve().parents[1]

_PRIVATE_RE = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"\bBearer" + r"\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]


def _public_safe(obj: object) -> bool:
    text = json.dumps(obj, sort_keys=True) if not isinstance(obj, str) else obj
    return not any(p.search(text) for p in _PRIVATE_RE)


def _qd(**kw: object) -> dict:
    d = {
        "ok": True, "goal_id": "g", "agent_id": "a",
        "agent_identity": {"agent_id": "a"},
        "decision": "run", "should_run": True,
        "effective_action": "normal_run", "state": "eligible",
        "recommended_action": "Advance.",
        "selected_todo": {"todo_id": "t001", "text": "Advance."},
        "interaction_contract": {
            "schema_version": "loopx_interaction_contract_v0",
            "mode": "normal_run",
            "user_channel": {"action_required": False, "notify": "DONT_NOTIFY"},
            "agent_channel": {"must_attempt": True, "delivery_allowed": True, "quiet_noop_allowed": False},
            "cli_channel": {"spend_after_validation": True},
        },
        "open_count": 0, "action_required": False,
    }
    d.update(kw)
    return d


def _lineage(g="g", a="a", t="t001"):
    return {"goal_id": g, "agent_id": a, "todo_id": t}


class TestSignedActionSelection:
    def test_different_decisions_produce_different_hashes(self):
        a = build_turn_envelope(_qd(effective_action="normal_run"))
        b = build_turn_envelope(_qd(effective_action="quiet_noop"))
        assert a["action_signature"]["matches"] is True
        assert b["action_signature"]["matches"] is True
        assert a["action_signature"]["source_hash"] != b["action_signature"]["source_hash"]
        assert a["action_signature"]["source_hash"] == a["action_signature"]["envelope_hash"]
        assert a["compaction"]["within_budget"] is True
        assert _public_safe(a)

    def test_envelope_compaction_under_budget(self):
        e = build_turn_envelope(_qd())
        assert e["compaction"]["within_budget"] is True


class TestTurnPlanRoutes:
    def test_visible_hosts_ready_for_host(self):
        envelope = build_turn_envelope(_qd())
        for host in ("codex-cli", "claude-code"):
            plan = build_loopx_turn_plan(envelope, host=host, execution_mode="interactive-visible")
            assert plan["ok"] is True
            assert plan["route"]["kind"] == LoopXTurnRoute.READY_FOR_HOST.value
            assert plan["route"]["would_invoke_host"] is True
            assert plan["route"]["host_invocation_allowed"] is False
            assert plan["host"]["kind"] == host

    def test_generic_cli_requires_headless_isolation(self):
        envelope = build_turn_envelope(_qd())
        plan = build_loopx_turn_plan(envelope, host="generic-cli", execution_mode="isolated-headless")
        assert plan["ok"] is True
        assert plan["host"]["execution_mode"] == "isolated-headless"
        assert plan["host"]["explicit_isolation"] is True
        assert _public_safe(plan)


class TestTransactionPlan:
    def test_schema_and_phases(self):
        txn = build_loopx_turn_transaction_plan(
            planned=True, lineage=_lineage(), host="codex-cli",
            execution_mode="interactive-visible", session_action="start_new",
            scheduler_owner="agent_cli_loop")
        assert txn["schema_version"] == LOOPX_TURN_TRANSACTION_PLAN_SCHEMA_VERSION
        assert txn["status"] == "planned"
        for phase in ("host_execute", "typed_result", "validation", "durable_writeback", "quota_spend"):
            assert phase in txn["phases"]
        assert txn["receipt_seed"]["status"] == "not_executed"
        assert txn["receipt_seed"]["next_phase"] == "host_execute"
        settlement = txn["settlement_plan"]
        assert settlement["identity"]["goal_id"] == "g"
        ordered_steps = settlement["ordered_steps"]
        assert [step["kind"] for step in ordered_steps] == [
            "validation",
            "durable_writeback",
            "quota_spend",
            "terminal_closeout",
        ]
        assert ordered_steps[-1]["conditional"] is True
        for step in ordered_steps:
            assert step["idempotency_key_ref"] == "$.identity.effect_id"
        assert _public_safe(txn)

    def test_same_lineage_different_host_diff_turn_key_same_settlement_identity(self):
        lineage = _lineage()
        a = build_loopx_turn_transaction_plan(
            planned=True, lineage=lineage, host="codex-cli",
            execution_mode="interactive-visible", session_action="start_new",
            scheduler_owner="agent_cli_loop")
        b = build_loopx_turn_transaction_plan(
            planned=True, lineage=lineage, host="generic-cli",
            execution_mode="isolated-headless", session_action="start_new",
            scheduler_owner="outer_controller")
        assert a["turn_key"] != b["turn_key"]
        assert a["settlement_plan"]["identity"]["goal_id"] == b["settlement_plan"]["identity"]["goal_id"] == "g"

    def test_not_planned_is_not_applicable(self):
        txn = build_loopx_turn_transaction_plan(
            planned=False, lineage=_lineage(), host="codex-cli",
            execution_mode="interactive-visible", session_action="none")
        assert txn["status"] == "not_applicable"
        assert txn["phases"] == []
        assert txn["receipt_seed"]["next_phase"] is None


class TestIndependentValidation:
    def test_pass_validator(self):
        v = build_loopx_turn_command_validator(
            [sys.executable, "-c", "import sys; sys.exit(0)"],
            project=REPO_ROOT, timeout_seconds=10.0)
        assert callable(v)
        envelope = build_turn_envelope(_qd())
        plan = build_loopx_turn_plan(envelope, host="codex-cli", execution_mode="interactive-visible")
        result = {"schema_version": LOOPX_TURN_RESULT_SCHEMA_VERSION,
                  "turn_key": plan["transaction"]["turn_key"],
                  "result_kind": "validated_progress",
                  "completed_phases": ["host_execute", "typed_result"]}
        passed = v(plan, result)
        assert passed["status"] == "passed"
        assert passed["exit_code"] == 0

    def test_fail_validator_with_recovery_kind(self):
        v = build_loopx_turn_command_validator(
            [sys.executable, "-c", "import sys; sys.exit(3)"],
            project=REPO_ROOT, timeout_seconds=10.0, failure_recovery_kind="repair_required")
        envelope = build_turn_envelope(_qd())
        plan = build_loopx_turn_plan(envelope, host="codex-cli", execution_mode="interactive-visible")
        result = {"schema_version": LOOPX_TURN_RESULT_SCHEMA_VERSION,
                  "turn_key": plan["transaction"]["turn_key"],
                  "result_kind": "validated_progress",
                  "completed_phases": ["host_execute", "typed_result"]}
        failed = v(plan, result)
        assert failed["status"] == "failed"
        assert failed["exit_code"] == 3
        assert failed.get("recovery_kind") == "repair_required"


class TestLoopDisposition:
    def test_run_now_no_prior_receipt(self):
        envelope = build_turn_envelope(_qd())
        d = decide_loop_disposition(turn_receipt=None, quota_decision=envelope)
        assert d["disposition"] == LoopDisposition.RUN_NOW.value
        assert d["spends_quota"] is False
        assert d["launches_host"] is False
        assert _public_safe(d)

    def test_terminal_no_followup(self):
        terminal = build_turn_envelope(_qd(should_run=False, effective_action="terminal_no_followup",
                                            state="terminal_no_followup", decision="stop"))
        d = decide_loop_disposition(turn_receipt=None, quota_decision=terminal)
        assert d["disposition"] == LoopDisposition.TERMINAL.value

    def test_wait_quiet_noop(self):
        wait_env = build_turn_envelope(_qd(should_run=False, effective_action="quiet_noop",
                                            state="waiting", decision="wait", quiet_noop_allowed=True))
        d = decide_loop_disposition(turn_receipt=None, quota_decision=wait_env)
        assert d["disposition"] == LoopDisposition.WAIT.value

    def test_replan_delta_requirements(self):
        replan_env = build_turn_envelope(_qd(effective_action="autonomous_replan", decision="run"))
        d = decide_loop_disposition(turn_receipt=None, quota_decision=replan_env)
        assert d["disposition"] == LoopDisposition.REPLAN.value
        assert d["replan_continuation"]["requires_bounded_delta"] is True
        assert "todo_delta" in d["replan_continuation"]["delta_kinds"]
        assert "vision_delta" in d["replan_continuation"]["delta_kinds"]
        assert d["replan_continuation"]["fresh_envelope_required"] is True
        assert _public_safe(d)

    def test_budget_exhaustion_replan(self):
        envelope = build_turn_envelope(_qd())
        plan = build_loopx_turn_plan(envelope, host="codex-cli", execution_mode="interactive-visible")
        txn = plan["transaction"]
        execution = {
            "schema_version": LOOPX_TURN_EXECUTION_SCHEMA_VERSION,
            "status": "committed", "result_kind": "validated_progress",
            "turn_key": txn["turn_key"],
            "receipt": {
                "schema_version": "loopx_turn_receipt_validation_v0", "ok": True,
                "turn_key": txn["turn_key"], "lineage": _lineage(),
                "settlement_effect_id": "effect-001", "result_kind": "validated_progress",
                "completed_phases": list(TRANSACTION_PHASES), "failed_phase": None, "status": "committed",
            },
            "effects": {"state_written": True, "quota_spent": True, "scheduler_acknowledged": True},
            "settlement_result": {"ok": True, "failure": None, "receipts": [
                {"step_kind": "validation", "effect_id": "effect-001", "status": "committed"},
                {"step_kind": "durable_writeback", "effect_id": "effect-001", "status": "committed"},
                {"step_kind": "quota_spend", "effect_id": "effect-001", "status": "committed"},
            ]},
            "scheduler": {"completed": True},
        }
        receipt = ValidatedTurnReceipt.from_execution(execution)
        assert receipt.result_kind == LoopXTurnResultKind.VALIDATED_PROGRESS
        budget = BoundedTurnBudget(lineage=_lineage(), max_turns=3, completed_turns=3)
        assert budget.remaining == 0
        d = decide_loop_disposition(turn_receipt=receipt, quota_decision=envelope,
                                     predecessor_turn_key=txn["turn_key"], bounded_turn_budget=budget)
        assert d["disposition"] == LoopDisposition.REPLAN.value


class TestHostRequest:
    def test_projects_same_identity(self):
        envelope = build_turn_envelope(_qd())
        plan = build_loopx_turn_plan(envelope, host="codex-cli", execution_mode="interactive-visible")
        req = build_loopx_turn_host_request(plan)
        assert req["schema_version"] == "loopx_turn_host_request_v0"
        assert req["turn_key"] == plan["transaction"]["turn_key"]
        assert req["route"] == LoopXTurnRoute.READY_FOR_HOST.value
        assert _public_safe(req)


class TestHostModePlan:
    def test_intent_to_mode_and_connector(self):
        plan = build_host_mode_plan(
            goal_id="g", user_intent="watch_each_turn",
            host_capabilities=["visible_session"],
            agent_id="a", registered_agents=["a"],
            available_capabilities=["shell", "network"],
            host_identity="codex-cli")
        assert plan["ok"] is True
        assert plan["selected_mode"] == "visible_tui"
        assert plan["selected_connector_id"] == "codex_cli_tui"
        assert plan["selected_capability_ready"] is True

    def test_headless_intent(self):
        plan = build_host_mode_plan(
            goal_id="g", user_intent="continue_without_ui",
            host_capabilities=["loopx_turn", "typed_host_adapter", "independent_validator"],
            agent_id="a", registered_agents=["a"],
            available_capabilities=["shell"], host_identity="generic-cli")
        assert plan["selected_mode"] == "isolated_headless_turn"
        assert plan["selected_capability_ready"] is True


class TestExecutionCommitted:
    def test_committed_when_effects_present(self):
        envelope = build_turn_envelope(_qd())
        plan = build_loopx_turn_plan(envelope, host="codex-cli", execution_mode="interactive-visible")
        txn = plan["transaction"]
        committed = {"schema_version": LOOPX_TURN_EXECUTION_SCHEMA_VERSION,
                     "status": "committed", "validation": {"status": "passed"},
                     "receipt": {"status": "committed"},
                     "effects": {"state_written": True, "quota_spent": True},
                     "turn_key": txn["turn_key"]}
        assert loopx_turn_execution_committed(committed) is True

    def test_not_committed_when_effects_missing(self):
        partial = {"schema_version": LOOPX_TURN_EXECUTION_SCHEMA_VERSION,
                   "status": "committed", "validation": {"status": "passed"},
                   "receipt": {"status": "committed"},
                   "effects": {"state_written": False, "quota_spent": False},
                   "turn_key": "k"}
        assert loopx_turn_execution_committed(partial) is False


class TestTurnReceiptValidation:
    def test_valid_receipt(self):
        txn = build_loopx_turn_transaction_plan(
            planned=True, lineage=_lineage(), host="codex-cli",
            execution_mode="interactive-visible", session_action="start_new",
            scheduler_owner="agent_cli_loop")
        result = {"schema_version": LOOPX_TURN_RESULT_SCHEMA_VERSION,
                  "turn_key": txn["turn_key"], "result_kind": "validated_progress",
                  "completed_phases": ["host_execute", "typed_result", "validation"]}
        receipt = validate_loopx_turn_receipt(txn, result)
        assert receipt["ok"] is True
        assert receipt["status"] == "validated"
        assert _public_safe(receipt)

    def test_bad_turn_key_fails(self):
        txn = build_loopx_turn_transaction_plan(
            planned=True, lineage=_lineage(), host="codex-cli",
            execution_mode="interactive-visible", session_action="start_new",
            scheduler_owner="agent_cli_loop")
        bad_result = {"schema_version": LOOPX_TURN_RESULT_SCHEMA_VERSION,
                      "turn_key": "sha256:" + "ab" * 32, "result_kind": "validated_progress",
                      "completed_phases": ["host_execute"]}
        receipt = validate_loopx_turn_receipt(txn, bad_result)
        assert receipt["ok"] is False


class TestPublicSafety:
    def test_all_payloads_public_safe(self):
        envelope = build_turn_envelope(_qd())
        plan = build_loopx_turn_plan(envelope, host="codex-cli", execution_mode="interactive-visible")
        host_req = build_loopx_turn_host_request(plan)
        txn = build_loopx_turn_transaction_plan(
            planned=True, lineage=_lineage(), host="codex-cli",
            execution_mode="interactive-visible", session_action="start_new",
            scheduler_owner="agent_cli_loop")
        for label, p in [("envelope", envelope), ("plan", plan), ("host_req", host_req), ("txn", txn)]:
            assert _public_safe(p), label
        assert "bearer" not in json.dumps(plan, ensure_ascii=False).lower()
