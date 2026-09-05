from __future__ import annotations

from loopx.control_plane.goals.terminal_contract import (
    CLOSEOUT_OWNER_VALUES,
    TERMINAL_CONTRACT_SCHEMA_VERSION,
    TERMINAL_EVIDENCE_KIND_VALUES,
    TERMINAL_OWNERSHIP_VALUES,
    build_terminal_contract,
    is_host_owned_terminal,
    terminal_contract_summary,
    validate_terminal_contract,
)


def test_build_terminal_contract_for_ark_managed_agent() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )

    assert contract["schema_version"] == TERMINAL_CONTRACT_SCHEMA_VERSION
    assert contract["terminal_ownership"] == "host"
    assert contract["task_todo_closeout"] == "host_owned"
    assert contract["loopx_goal_closeout"] == "host_owned"
    assert contract["final_evidence_writeback"] == "host_owned"
    assert contract["bound_goal_id"] == "goal-123"
    assert contract["bound_agent_id"] == "agent-1"
    assert contract["host_surface"] == "ark-managed-agent"
    assert contract["terminal_evidence"]["kind"] == "host_submission_confirmation"


def test_build_terminal_contract_for_claude_code() -> None:
    contract = build_terminal_contract(
        host_surface="claude-code",
        goal_id="goal-456",
        agent_id="agent-2",
    )

    assert contract["terminal_ownership"] == "agent"
    assert contract["task_todo_closeout"] == "agent_required"
    assert contract["loopx_goal_closeout"] == "agent_required"
    assert contract["final_evidence_writeback"] == "agent_required"
    assert contract["terminal_evidence"]["kind"] == "not_applicable"


def test_build_terminal_contract_for_manual() -> None:
    contract = build_terminal_contract(
        host_surface="manual",
        goal_id="goal-789",
        agent_id=None,
    )

    assert contract["terminal_ownership"] == "not_applicable"
    assert contract["task_todo_closeout"] == "not_applicable"
    assert contract["loopx_goal_closeout"] == "not_applicable"
    assert contract["final_evidence_writeback"] == "not_applicable"


def test_build_terminal_contract_for_deepseek_harness_native() -> None:
    contract = build_terminal_contract(
        host_surface="deepseek-harness-native",
        goal_id="goal-ds",
        agent_id="agent-ds",
    )

    assert contract["terminal_ownership"] == "host"
    assert contract["loopx_goal_closeout"] == "host_owned"


def test_validate_terminal_contract_valid_host() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )
    errors = validate_terminal_contract(contract)
    assert errors == []


def test_validate_terminal_contract_valid_agent() -> None:
    contract = build_terminal_contract(
        host_surface="claude-code",
        goal_id="goal-456",
        agent_id="agent-2",
    )
    errors = validate_terminal_contract(contract)
    assert errors == []


def test_validate_terminal_contract_rejects_missing_schema_version() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )
    del contract["schema_version"]
    errors = validate_terminal_contract(contract)
    assert any("schema_version" in err for err in errors)


def test_validate_terminal_contract_rejects_invalid_ownership() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )
    contract["terminal_ownership"] = "invalid"
    errors = validate_terminal_contract(contract)
    assert any("terminal_ownership" in err for err in errors)


def test_validate_terminal_contract_rejects_host_owned_closeout_with_agent_ownership() -> None:
    contract = build_terminal_contract(
        host_surface="claude-code",
        goal_id="goal-456",
        agent_id="agent-2",
    )
    # Contradict the ownership: agent ownership but host-owned closeout
    contract["task_todo_closeout"] = "host_owned"
    errors = validate_terminal_contract(contract)
    assert any("cannot be host_owned" in err for err in errors)


def test_validate_terminal_contract_rejects_agent_required_closeout_with_host_ownership() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )
    # Contradict the ownership: host ownership but agent-required closeout
    contract["loopx_goal_closeout"] = "agent_required"
    errors = validate_terminal_contract(contract)
    assert any("cannot be agent_required" in err for err in errors)


def test_validate_terminal_contract_rejects_missing_goal_id() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )
    contract["bound_goal_id"] = ""
    errors = validate_terminal_contract(contract)
    assert any("bound_goal_id" in err for err in errors)


def test_validate_terminal_contract_rejects_invalid_evidence_kind() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )
    contract["terminal_evidence"] = {"kind": "invalid_kind"}
    errors = validate_terminal_contract(contract)
    assert any("terminal_evidence.kind" in err for err in errors)


def test_is_host_owned_terminal_returns_true_for_host() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )
    assert is_host_owned_terminal(contract) is True


def test_is_host_owned_terminal_returns_false_for_agent() -> None:
    contract = build_terminal_contract(
        host_surface="claude-code",
        goal_id="goal-456",
        agent_id="agent-2",
    )
    assert is_host_owned_terminal(contract) is False


def test_is_host_owned_terminal_returns_false_for_non_dict() -> None:
    assert is_host_owned_terminal(None) is False
    assert is_host_owned_terminal("not a dict") is False
    assert is_host_owned_terminal({}) is False


def test_terminal_contract_summary_renders_correctly() -> None:
    contract = build_terminal_contract(
        host_surface="ark-managed-agent",
        goal_id="goal-123",
        agent_id="agent-1",
    )
    summary = terminal_contract_summary(contract)
    assert "ownership=host" in summary
    assert "goal=goal-123" in summary
    assert "todo_closeout=host_owned" in summary
    assert "goal_closeout=host_owned" in summary
    assert "evidence_writeback=host_owned" in summary


def test_terminal_contract_summary_handles_invalid_contract() -> None:
    summary = terminal_contract_summary(None)
    assert "invalid" in summary


def test_all_ownership_values_are_valid() -> None:
    assert "agent" in TERMINAL_OWNERSHIP_VALUES
    assert "host" in TERMINAL_OWNERSHIP_VALUES
    assert "not_applicable" in TERMINAL_OWNERSHIP_VALUES


def test_all_closeout_owner_values_are_valid() -> None:
    assert "agent_required" in CLOSEOUT_OWNER_VALUES
    assert "host_owned" in CLOSEOUT_OWNER_VALUES
    assert "not_applicable" in CLOSEOUT_OWNER_VALUES


def test_all_evidence_kind_values_are_valid() -> None:
    assert "host_delivery_receipt" in TERMINAL_EVIDENCE_KIND_VALUES
    assert "host_submission_confirmation" in TERMINAL_EVIDENCE_KIND_VALUES
    assert "not_applicable" in TERMINAL_EVIDENCE_KIND_VALUES
