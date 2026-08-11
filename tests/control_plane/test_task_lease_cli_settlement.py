from __future__ import annotations

from pathlib import Path

from loopx.cli import build_parser
from loopx.cli_commands.task_lease import handle_task_lease_command
from loopx.control_plane.effect_program import (
    SettlementFailureKind,
    SettlementReceipt,
    SettlementResult,
    SettlementStepKind,
)


def _run_acquire(
    monkeypatch,
    result: SettlementResult[dict],
) -> dict:
    captured: list[dict] = []
    import loopx.cli_commands.task_lease as task_lease_cli

    monkeypatch.setattr(
        task_lease_cli,
        "execute_task_lease_settlement",
        lambda **kwargs: result,
    )
    args = build_parser().parse_args(
        [
            "task-lease",
            "acquire",
            "--goal-id",
            "cli-settlement-goal",
            "--todo-id",
            "todo_cli_settlement",
            "--owner",
            "codex-cli-agent",
            "--idempotency-key",
            "cli-settlement-key",
            "--ttl-seconds",
            "300",
        ]
    )
    handle_task_lease_command(
        args,
        registry_path=Path("/tmp/registry.json"),
        runtime_root_arg=None,
        output_format=lambda _args: "json",
        print_payload=lambda payload, _fmt, _render: captured.append(payload),
    )
    return captured[0]


def test_cli_acquire_routes_through_typed_settlement(monkeypatch) -> None:
    lease = {
        "goal_id": "cli-settlement-goal",
        "todo_id": "todo_cli_settlement",
        "owner": "codex-cli-agent",
        "version": 1,
    }
    result = SettlementResult.pure(
        lease,
        receipts=(
            SettlementReceipt(
                step_kind=SettlementStepKind.DURABLE_WRITEBACK,
                status="committed",
                effect_id="goal:agent:todo:key",
                source_ref="lease-path",
            ),
        ),
    )
    payload = _run_acquire(monkeypatch, result)
    assert payload["ok"] is True
    assert payload["action"] == "acquire"
    assert payload["acquired"] is True
    assert payload["lease"]["version"] == 1
    assert payload["settlement"]["effect_id"] == "goal:agent:todo:key"
    assert payload["settlement"]["receipts"][0]["status"] == "committed"


def test_cli_acquire_idempotent_replay_payload(monkeypatch) -> None:
    lease = {"todo_id": "todo_cli_settlement", "owner": "codex-cli-agent"}
    result = SettlementResult.pure(
        lease,
        receipts=(
            SettlementReceipt(
                step_kind=SettlementStepKind.DURABLE_WRITEBACK,
                status="idempotent",
                effect_id="goal:agent:todo:key",
                source_ref="lease-path",
            ),
        ),
    )
    payload = _run_acquire(monkeypatch, result)
    assert payload["ok"] is True
    assert payload["acquired"] is False
    assert payload["idempotent"] is True


def test_cli_acquire_typed_failure_payload(monkeypatch) -> None:
    result = SettlementResult.failed(
        kind=SettlementFailureKind.INVALID_IDENTITY,
        step_kind=SettlementStepKind.DURABLE_WRITEBACK,
        reason="idempotency key was reused with different acquire parameters",
        details={"task_lease_error_code": "idempotency_key_reuse"},
    )
    payload = _run_acquire(monkeypatch, result)
    assert payload["ok"] is False
    assert payload["error_code"] == "idempotency_key_reuse"
    assert payload["settlement"]["failure"]["step"] == "durable_writeback"
    assert payload["settlement"]["failure"]["kind"] == "invalid_identity"
    assert payload["settlement"]["failure"]["code"] == "idempotency_key_reuse"
    assert "idempotency" in payload["error"]
