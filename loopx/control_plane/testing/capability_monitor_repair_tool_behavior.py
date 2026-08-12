from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from ...heartbeat_prompt import build_heartbeat_prompt
from ..quota.turn_envelope import quota_action_signature_document
from .doubao_model_behavior_actor import (
    ARK_API_KEY_ENV,
    DOUBAO_2_1_PRO_MODEL,
    DOUBAO_MODEL_ENV,
    DoubaoActorTransport,
    _direct_ark_transport,
)
from .model_tool_behavior import (
    DoubaoExecToolClient,
    argument_value,
    digest_text,
    execute_loopx_cli,
    loopx_command_tokens,
)
from .selected_todo_tool_behavior import (
    SELECTED_TODO_TOOL_FIXTURE_AGENT_ID,
    SELECTED_TODO_TOOL_FIXTURE_GOAL_ID,
    _classify_tool_command,
    _execute_workspace_read,
    _SelectedTodoToolFixture,
)

CAPABILITY_MONITOR_REPAIR_TOOL_BEHAVIOR_RECEIPT_SCHEMA_VERSION = (
    "capability_monitor_repair_tool_behavior_receipt_v0"
)
CAPABILITY_MONITOR_REPAIR_TOOL_BEHAVIOR_MAX_CALLS = 6

CAPABILITY_REPAIR_BLOCKED_TODO_ID = "todo_portfolio_private_read"
CAPABILITY_REPAIR_MONITOR_TODO_ID = "todo_portfolio_monitor_schedule"
CAPABILITY_REPAIR_TARGET_CAPABILITY = "private_read"
CAPABILITY_REPAIR_TRIGGER_TIME = "2026-08-12T00:00:00+08:00"


def _heartbeat_trigger_message(task_body: str) -> str:
    return (
        "<heartbeat>\n"
        "  <automation_id>loopx</automation_id>\n"
        f"  <current_time_iso>{CAPABILITY_REPAIR_TRIGGER_TIME}</current_time_iso>\n"
        "  <instructions>\n"
        f"{task_body}\n"
        "  </instructions>\n"
        "</heartbeat>"
    )


def _build_capability_repair_fixture(root: Path) -> _SelectedTodoToolFixture:
    source_root = Path(__file__).resolve().parents[3]
    project_root = root / "project"
    runtime_root = root / "runtime"
    fixture_home = root / "home"
    state_relative = (
        Path(".codex")
        / "goals"
        / SELECTED_TODO_TOOL_FIXTURE_GOAL_ID
        / "ACTIVE_GOAL_STATE.md"
    )
    state_path = project_root / state_relative
    local_registry_path = project_root / ".loopx" / "registry.json"
    global_registry_path = (
        fixture_home / ".codex" / "loopx" / "registry.global.json"
    )
    unused_target = project_root / "fixture" / "unused.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    unused_target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    state_path.write_text(
        "---\n"
        "status: active\n"
        "owner_mode: goal\n"
        'objective: "Repair the missing capability bridge before delivery."\n'
        "updated_at: 2026-08-12T00:00:00+08:00\n"
        "---\n\n"
        "# Capability Repair Live Fixture\n\n"
        "## Objective\n\n"
        "Repair the missing capability bridge before delivery.\n\n"
        "## Next Action\n\n"
        "- Repair or materialize the missing capability bridge.\n\n"
        "## Agent Todo\n\n"
        "- [ ] [P0] Repair the release monitor schedule.\n"
        "  <!-- loopx:todo "
        f"todo_id={CAPABILITY_REPAIR_MONITOR_TODO_ID} status=open "
        "task_class=continuous_monitor action_kind=monitor "
        f"claimed_by={SELECTED_TODO_TOOL_FIXTURE_AGENT_ID} priority=P0 "
        "target_key=portfolio-release-monitor -->\n"
        "- [ ] [P1] Read a private source before implementation.\n"
        "  <!-- loopx:todo "
        f"todo_id={CAPABILITY_REPAIR_BLOCKED_TODO_ID} status=open "
        "task_class=advancement_task action_kind=read_private_source "
        f"claimed_by={SELECTED_TODO_TOOL_FIXTURE_AGENT_ID} priority=P1 "
        f"required_capabilities={CAPABILITY_REPAIR_TARGET_CAPABILITY} -->\n",
        encoding="utf-8",
    )
    registry = {
        "schema_version": "0.1",
        "updated_at": "2026-08-12T00:00:00+08:00",
        "common_runtime_root": str(runtime_root),
        "goals": [
            {
                "id": SELECTED_TODO_TOOL_FIXTURE_GOAL_ID,
                "domain": "capability-repair-live-fixture",
                "status": "active",
                "repo": str(project_root),
                "state_file": str(state_relative),
                "adapter": {
                    "kind": "fixture_connected_delivery_v0",
                    "status": "connected-delivery",
                },
                "coordination": {
                    "registered_agents": [SELECTED_TODO_TOOL_FIXTURE_AGENT_ID],
                    "agent_model": "peer_v1",
                },
                "authority_sources": [],
                "quota": {
                    "compute": 1.0,
                    "window_hours": 24,
                    "allowed_slots": 5,
                },
            }
        ],
    }
    registry_text = json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True)
    for registry_path in (local_registry_path, global_registry_path):
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(registry_text + "\n", encoding="utf-8")

    prompt = build_heartbeat_prompt(
        goal_id=SELECTED_TODO_TOOL_FIXTURE_GOAL_ID,
        thin=True,
        agent_id=SELECTED_TODO_TOOL_FIXTURE_AGENT_ID,
        registered_agents=[SELECTED_TODO_TOOL_FIXTURE_AGENT_ID],
        available_capabilities=[
            "shell",
            "filesystem_read",
            "filesystem_write",
            "network",
        ],
        runtime_profile="codex_app_heartbeat",
    )
    quota_guard_command = str(prompt["quota_guard_command"])
    if quota_guard_command not in str(prompt["task_body"]):
        raise ValueError("heartbeat fixture must contain its production quota guard")
    return _SelectedTodoToolFixture(
        task_body=str(prompt["task_body"]),
        quota_guard_command=quota_guard_command,
        project_root=project_root,
        runtime_root=runtime_root,
        global_registry_path=global_registry_path,
        source_root=source_root,
        selected_target=unused_target,
    )


def _is_capability_repair_command(command: str) -> bool:
    tokens = loopx_command_tokens(command)
    if not tokens:
        return False
    try:
        todo_index = tokens.index("todo")
    except ValueError:
        return False
    return bool(
        tokens[todo_index : todo_index + 2] == ["todo", "add"]
        and argument_value(tokens, "--goal-id")
        == SELECTED_TODO_TOOL_FIXTURE_GOAL_ID
        and argument_value(tokens, "--role") == "agent"
        and argument_value(tokens, "--task-class") == "advancement_task"
        and argument_value(tokens, "--action-kind") == "materialize_capability"
        and argument_value(tokens, "--target-capability")
        == CAPABILITY_REPAIR_TARGET_CAPABILITY
        and argument_value(tokens, "--claimed-by")
        == SELECTED_TODO_TOOL_FIXTURE_AGENT_ID
        and argument_value(tokens, "--unblocks-todo-id")
        == CAPABILITY_REPAIR_BLOCKED_TODO_ID
        and bool(argument_value(tokens, "--text"))
    )


def _is_monitor_fallback_command(command: str) -> bool:
    tokens = loopx_command_tokens(command)
    if not tokens:
        return False
    return any(
        tokens[index : index + 2]
        in (["quota", "monitor-poll"], ["todo", "update"])
        and CAPABILITY_REPAIR_MONITOR_TODO_ID in tokens
        for index in range(len(tokens) - 1)
    )


def _capability_repair_contract(packet: Mapping[str, Any]) -> dict[str, Any]:
    signature = quota_action_signature_document(packet)
    action = dict(signature.get("action") or {})
    user = dict(signature.get("user") or {})
    interaction = dict(packet.get("interaction_contract") or {})
    capability_gate = dict(packet.get("capability_gate") or {})
    cli_channel = dict(interaction.get("cli_channel") or {})
    next_cli_actions = [str(item) for item in cli_channel.get("next_cli_actions") or []]
    repair_actions = [item for item in next_cli_actions if _is_capability_repair_command(item)]
    contract = {
        "decision": "execute",
        "selected_todo_id": None,
        "user_action_required": bool(user.get("action_required")),
        "must_attempt_work": bool(action.get("must_attempt")),
        "delivery_allowed": bool(action.get("delivery_allowed")),
        "quiet_noop_allowed": bool(action.get("quiet_noop_allowed")),
        "external_write_requested": False,
        "repair_missing": list(capability_gate.get("repair_missing") or []),
    }
    if not (
        interaction.get("mode") == "capability_bridge_repair"
        and contract["user_action_required"] is False
        and contract["must_attempt_work"] is True
        and contract["delivery_allowed"] is False
        and contract["quiet_noop_allowed"] is False
        and "next_cli_actions[0]"
        in str((interaction.get("agent_channel") or {}).get("primary_action") or "")
        and capability_gate.get("action") == "repair_bridge"
        and capability_gate.get("decision_owner") == "agent"
        and CAPABILITY_REPAIR_TARGET_CAPABILITY in contract["repair_missing"]
        and len(repair_actions) == 1
    ):
        raise ValueError("real quota packet did not preserve capability bridge repair")
    return contract


def _execute_capability_repair(
    command: str,
    *,
    fixture: _SelectedTodoToolFixture,
) -> str:
    execute_loopx_cli(
        command,
        source_root=fixture.source_root,
        project_root=fixture.project_root,
    )
    readback = execute_loopx_cli(
        "loopx --format json todo list --goal-id "
        f"{SELECTED_TODO_TOOL_FIXTURE_GOAL_ID} --role agent --status open",
        source_root=fixture.source_root,
        project_root=fixture.project_root,
    )
    todos = json.loads(readback).get("todos") or []
    repair = next(
        (
            item
            for item in todos
            if item.get("action_kind") == "materialize_capability"
            and CAPABILITY_REPAIR_TARGET_CAPABILITY
            in (item.get("target_capabilities") or [])
            and item.get("unblocks_todo_id") == CAPABILITY_REPAIR_BLOCKED_TODO_ID
            and item.get("claimed_by") == SELECTED_TODO_TOOL_FIXTURE_AGENT_ID
        ),
        None,
    )
    monitor = next(
        (item for item in todos if item.get("todo_id") == CAPABILITY_REPAIR_MONITOR_TODO_ID),
        None,
    )
    if repair is None or monitor is None or monitor.get("status") != "open":
        raise ValueError("capability repair Todo readback failed")
    return json.dumps(
        {
            "repair_todo_id": repair.get("todo_id"),
            "target_capability": CAPABILITY_REPAIR_TARGET_CAPABILITY,
            "unblocks_todo_id": CAPABILITY_REPAIR_BLOCKED_TODO_ID,
            "monitor_fallback_executed": False,
        },
        sort_keys=True,
    )


def _receipt(
    *,
    qualification_id: str,
    actor_ref: str,
    steps: list[dict[str, Any]],
    contract: Mapping[str, Any] | None,
    repair_executed: bool,
    passed: bool,
    failure_code: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": CAPABILITY_MONITOR_REPAIR_TOOL_BEHAVIOR_RECEIPT_SCHEMA_VERSION,
        "qualification_id": qualification_id,
        "actor_ref": actor_ref,
        "qualification_passed": passed,
        "failure_code": failure_code,
        **dict(contract or {}),
        "observed_tool_sequence": [step["kind"] for step in steps],
        "tool_call_count": len(steps),
        "capability_repair_executed": repair_executed,
        "monitor_fallback_avoided": repair_executed,
        "tool_call_receipts": steps,
        "boundary": {
            "raw_prompt_persisted": False,
            "raw_provider_response_persisted": False,
            "raw_command_persisted": False,
            "writes_limited_to_temporary_fixture": True,
            "external_writes_executed": False,
            "shell_commands_executed": False,
            "control_plane_writes_executed": repair_executed,
        },
    }


class DoubaoCapabilityMonitorRepairToolBehaviorActor:
    """Prove capability repair outranks a monitor fallback in a real heartbeat."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DOUBAO_2_1_PRO_MODEL,
        timeout_seconds: float = 90.0,
        transport: DoubaoActorTransport = _direct_ark_transport,
    ) -> None:
        self._client = DoubaoExecToolClient(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        transport: DoubaoActorTransport = _direct_ark_transport,
        timeout_seconds: float = 90.0,
    ) -> DoubaoCapabilityMonitorRepairToolBehaviorActor:
        values = os.environ if environ is None else environ
        api_key = values.get(ARK_API_KEY_ENV, "")
        if not api_key.strip():
            raise RuntimeError(
                "ARK_API_KEY is not injected; live Doubao qualification is unavailable"
            )
        return cls(
            api_key=api_key,
            model=values.get(DOUBAO_MODEL_ENV, DOUBAO_2_1_PRO_MODEL),
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    def qualify(
        self,
        *,
        qualification_id: str,
        fixture_root: Path,
    ) -> dict[str, Any]:
        fixture = _build_capability_repair_fixture(fixture_root)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are Codex running one LoopX heartbeat. Follow the task and "
                    "choose each next action from the latest tool result. When real "
                    "quota projects an agent-owned capability bridge repair, execute "
                    "the concrete repair action from its CLI channel. Do not wait on, "
                    "poll, or rewrite a monitor fallback. Stop after the repair action "
                    "succeeds."
                ),
            },
            {
                "role": "user",
                "content": _heartbeat_trigger_message(fixture.task_body),
            },
        ]
        steps: list[dict[str, Any]] = []
        quota_observed = False
        repair_executed = False
        contract: dict[str, Any] | None = None
        seen_once: set[str] = set()
        actor_ref = self._client.actor_ref
        qualification_digest = sha256(qualification_id.encode()).hexdigest()[:16]
        turn_instance_id = f"qualification-{qualification_digest}"

        def receipt(*, passed: bool, failure_code: str | None) -> dict[str, Any]:
            return _receipt(
                qualification_id=qualification_id,
                actor_ref=actor_ref,
                steps=steps,
                contract=contract,
                repair_executed=repair_executed,
                passed=passed,
                failure_code=failure_code,
            )

        for _ in range(CAPABILITY_MONITOR_REPAIR_TOOL_BEHAVIOR_MAX_CALLS):
            tool_call = self._client.next_tool_call(messages)
            if tool_call is None:
                return receipt(
                    passed=False,
                    failure_code=(
                        "waited_on_capability_repair"
                        if quota_observed
                        else "model_returned_without_tool_call"
                    ),
                )

            if _is_capability_repair_command(tool_call.command):
                kind = (
                    "capability_repair"
                    if quota_observed
                    else "capability_repair_before_quota"
                )
                tool_output = None
            elif _is_monitor_fallback_command(tool_call.command):
                kind = "monitor_fallback"
                tool_output = None
            else:
                kind, tool_output = _classify_tool_command(
                    tool_call.command,
                    fixture=fixture,
                    quota_observed=quota_observed,
                )
                if kind == "workspace_read" and quota_observed:
                    kind = "post_quota_backtracking"
                elif kind not in {"clock", "quota_should_run", "workspace_read"}:
                    kind = "unexpected_command"
            steps.append(
                {
                    "ordinal": len(steps) + 1,
                    "kind": kind,
                    "command_digest": digest_text(tool_call.command),
                }
            )
            if kind == "capability_repair":
                try:
                    _execute_capability_repair(tool_call.command, fixture=fixture)
                except (RuntimeError, ValueError, json.JSONDecodeError):
                    return receipt(
                        passed=False,
                        failure_code="capability_repair_execution_failed",
                    )
                repair_executed = True
                return receipt(passed=True, failure_code=None)
            if kind in {
                "capability_repair_before_quota",
                "monitor_fallback",
                "post_quota_backtracking",
                "unexpected_command",
            }:
                return receipt(passed=False, failure_code=kind)
            if kind in {"clock", "quota_should_run"} and kind in seen_once:
                return receipt(passed=False, failure_code=f"repeated_{kind}")
            if kind in {"clock", "quota_should_run"}:
                seen_once.add(kind)
            if kind == "quota_should_run":
                try:
                    tool_output = execute_loopx_cli(
                        tool_call.command,
                        source_root=fixture.source_root,
                        project_root=fixture.project_root,
                        argument_overrides={
                            "--registry": str(fixture.global_registry_path),
                            "--turn-instance-id": turn_instance_id,
                        },
                    )
                    contract = _capability_repair_contract(json.loads(tool_output))
                    quota_observed = True
                except (RuntimeError, ValueError, json.JSONDecodeError):
                    return receipt(
                        passed=False,
                        failure_code="quota_execution_failed",
                    )
            elif kind == "workspace_read":
                try:
                    tool_output = _execute_workspace_read(
                        tool_call.command,
                        fixture=fixture,
                    )
                except RuntimeError:
                    return receipt(
                        passed=False,
                        failure_code="workspace_read_failed",
                    )
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": tool_call.assistant_content,
                        "tool_calls": [tool_call.provider_value],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.call_id,
                        "content": tool_output or "",
                    },
                ]
            )

        return receipt(passed=False, failure_code="tool_call_budget_exhausted")
