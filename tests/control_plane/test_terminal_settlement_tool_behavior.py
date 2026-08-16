from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loopx.control_plane.testing.model_tool_behavior import (
    ScriptedDoubaoExecTransport,
    ScriptedExecToolAction,
)
from loopx.control_plane.testing.terminal_settlement_tool_behavior import (
    TERMINAL_SETTLEMENT_FIXTURE_TODO_ID,
    DoubaoTerminalSettlementToolBehaviorActor,
    _build_fixture,
)


def _latest_quota_packet(request: Mapping[str, Any]) -> dict[str, Any]:
    for message in reversed(request["messages"]):
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(message["content"])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and "interaction_contract" in payload:
            return payload
    raise AssertionError("scripted model did not receive the real quota packet")


def _writeback_action(request: Mapping[str, Any]) -> ScriptedExecToolAction:
    packet = _latest_quota_packet(request)
    command = packet["interaction_contract"]["cli_channel"]["next_cli_actions"][0]
    command = (
        command.replace("<validated_progress>", "terminal_settlement_validated")
        .replace("<scale>", "single_surface")
        .replace("<outcome>", "outcome_progress")
        .replace('"${LOOPX_TURN:?}"', "turn-test-001")
    )
    return ScriptedExecToolAction(command=command)


def _spend_action(request: Mapping[str, Any]) -> ScriptedExecToolAction:
    packet = _latest_quota_packet(request)
    command = packet["interaction_contract"]["cli_channel"]["next_cli_actions"][1]
    return ScriptedExecToolAction(
        command=command.replace('"${LOOPX_TURN:?}"', "turn-test-001")
    )


def _terminal_action(request: Mapping[str, Any]) -> ScriptedExecToolAction:
    packet = _latest_quota_packet(request)
    steps = packet["interaction_contract"]["cli_channel"]["settlement_plan"][
        "ordered_steps"
    ]
    command = next(
        item["command_template"]
        for item in steps
        if item["kind"] == "terminal_closeout"
    )
    return ScriptedExecToolAction(
        command=command.replace('"${LOOPX_TURN:?}"', "turn-test-001").replace(
            "'<validated evidence>'",
            "'fixture-settlement-proof'",
        )
    )


def test_real_tool_loop_settles_final_todo_after_spend(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-test-001",
                )
            ),
            ScriptedExecToolAction(command="cat fixture/settlement-proof.json"),
            _writeback_action,
            _spend_action,
            _terminal_action,
        ]
    )

    receipt = DoubaoTerminalSettlementToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="terminal-settlement-tool-loop-001",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["failure_code"] is None, str(receipt["failure_code"])
    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "delivery_validation",
        "durable_writeback",
        "quota_spend",
        "terminal_closeout",
    ]
    assert receipt["settlement_receipt_steps"] == [
        "validation",
        "durable_writeback",
        "quota_spend",
        "terminal_closeout",
    ]
    assert receipt["terminal_order_observed"] is True
    assert receipt["selected_todo_id"] == TERMINAL_SETTLEMENT_FIXTURE_TODO_ID
    assert receipt["decision"] == "execute"
    assert receipt["boundary"] == {
        "raw_prompt_persisted": False,
        "raw_provider_response_persisted": False,
        "raw_command_persisted": False,
        "filesystem_writes_executed": True,
        "writes_limited_to_temporary_fixture": True,
        "external_writes_executed": False,
        "shell_commands_executed": False,
        "read_only_host_commands_executed": True,
    }
    assert "settlement-proof.json" not in json.dumps(receipt, sort_keys=True)

    first = transport.requests[0]
    assert first["messages"][1] == {"role": "user", "content": fixture.task_body}
    assert TERMINAL_SETTLEMENT_FIXTURE_TODO_ID not in fixture.task_body
    quota_result = _latest_quota_packet(transport.requests[2])
    assert quota_result["selected_todo"]["todo_id"] == (
        TERMINAL_SETTLEMENT_FIXTURE_TODO_ID
    )


def test_tool_loop_rejects_terminal_closeout_before_spend(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-test-001",
                )
            ),
            ScriptedExecToolAction(command="cat fixture/settlement-proof.json"),
            _terminal_action,
        ]
    )

    receipt = DoubaoTerminalSettlementToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="terminal-closeout-before-spend",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "terminal_closeout_before_spend"
    assert receipt["settlement_receipt_steps"] == []
    assert receipt["tool_call_receipts"][-1]["redacted_command_shape"] == {
        "parseable": True,
        "token_count_bucket": 12,
        "executable_family": "control_plane",
        "workspace_operation": "other",
        "git_operation": None,
        "python_module": None,
        "contains_loopx": True,
        "loopx_command_path": "todo",
        "loopx_command_action": "complete",
        "operator_before_loopx": False,
        "operator_after_loopx": False,
        "has_environment_assignment": False,
        "mentions_proof_target": False,
        "multiline": False,
    }


def test_tool_loop_rejects_spend_before_writeback(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-test-001",
                )
            ),
            ScriptedExecToolAction(command="cat fixture/settlement-proof.json"),
            _spend_action,
        ]
    )

    receipt = DoubaoTerminalSettlementToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="terminal-spend-before-writeback",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "quota_spend_before_writeback"
    assert receipt["settlement_receipt_steps"] == []
