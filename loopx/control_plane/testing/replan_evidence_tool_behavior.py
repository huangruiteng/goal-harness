from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ...heartbeat_prompt import build_heartbeat_prompt
from ..quota.turn_envelope import quota_action_signature_document
from .actual_default_model_behavior_portfolio import (
    ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
    ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
    build_actual_default_model_behavior_scenario_inputs,
)
from .doubao_model_behavior_actor import (
    ARK_API_KEY_ENV,
    DOUBAO_2_1_PRO_MODEL,
    DOUBAO_2_1_TURBO_MODEL,
    DOUBAO_CHAT_COMPLETIONS_ENDPOINT,
    DOUBAO_MODEL_ENV,
    DoubaoActorTransport,
    DoubaoActorTransportError,
    _direct_ark_transport,
)


REPLAN_EVIDENCE_TOOL_BEHAVIOR_RECEIPT_SCHEMA_VERSION = (
    "replan_evidence_tool_behavior_receipt_v0"
)
REPLAN_EVIDENCE_TOOL_BEHAVIOR_MAX_CALLS = 6

_ALLOWED_MODELS = {DOUBAO_2_1_PRO_MODEL, DOUBAO_2_1_TURBO_MODEL}
_MAX_TOOL_ARGUMENT_BYTES = 8_192
_MAX_PROVIDER_TOKENS = 2_048
_READ_ONLY_PREFLIGHT_OUTPUTS = {
    "pwd": "/workspace/loopx\n",
    "git status --short --branch": "## codex/qualification...origin/main\n",
    "git branch --show-current": "codex/qualification\n",
    "git rev-parse --show-toplevel": "/workspace/loopx\n",
}

_EXEC_COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "exec_command",
        "description": (
            "Run a shell command in the current workspace and return its output."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "The shell command to run.",
                }
            },
            "required": ["cmd"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class _ReplanEvidenceToolFixture:
    task_body: str
    quota_packet: dict[str, Any]
    required_evidence_command: str


@dataclass(frozen=True)
class _ToolCall:
    call_id: str
    command: str
    provider_value: dict[str, Any]


def _digest(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def _build_fixture(root: Path) -> _ReplanEvidenceToolFixture:
    _, packets = build_actual_default_model_behavior_scenario_inputs(root)
    packet = dict(packets["turn_required_vision_replan"])
    signature = quota_action_signature_document(packet)
    required_reads = list(signature.get("required_reads") or [])
    if len(required_reads) != 1 or not isinstance(required_reads[0], Mapping):
        raise ValueError("replan fixture must project exactly one required read")
    required_read = dict(required_reads[0])
    required_command = str(required_read.get("command") or "").strip()
    if (
        required_read.get("kind") != "agent_scoped_evidence_log"
        or " evidence-log " not in f" {required_command} "
    ):
        raise ValueError("replan fixture must bind to the agent evidence log")

    prompt = build_heartbeat_prompt(
        goal_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID,
        thin=True,
        agent_id=ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID,
        registered_agents=[ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID],
        available_capabilities=[
            "shell",
            "filesystem_read",
            "filesystem_write",
        ],
        runtime_profile="codex_app_heartbeat",
    )
    quota_guard_command = str(prompt["quota_guard_command"])
    if quota_guard_command not in str(prompt["task_body"]):
        raise ValueError("heartbeat fixture must contain its production quota guard")
    return _ReplanEvidenceToolFixture(
        task_body=str(prompt["task_body"]),
        quota_packet=packet,
        required_evidence_command=required_command,
    )


def _provider_tool_call(response: Mapping[str, Any]) -> _ToolCall | None:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise DoubaoActorTransportError(
            "Doubao tool behavior response must contain exactly one choice",
            error_code="provider_invalid_shape",
        )
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise DoubaoActorTransportError(
            "Doubao tool behavior choice must be an object",
            error_code="provider_invalid_shape",
        )
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise DoubaoActorTransportError(
            "Doubao tool behavior choice is missing its message",
            error_code="provider_invalid_shape",
        )
    tool_calls = message.get("tool_calls")
    if tool_calls in (None, []):
        return None
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        raise DoubaoActorTransportError(
            "Doubao tool behavior must choose exactly one tool per step",
            error_code="provider_invalid_tool_call",
        )
    raw_call = tool_calls[0]
    if not isinstance(raw_call, Mapping):
        raise DoubaoActorTransportError(
            "Doubao tool call must be an object",
            error_code="provider_invalid_tool_call",
        )
    function = raw_call.get("function")
    if (
        raw_call.get("type") != "function"
        or not isinstance(function, Mapping)
        or function.get("name") != "exec_command"
    ):
        raise DoubaoActorTransportError(
            "Doubao tool behavior selected an unsupported tool",
            error_code="provider_invalid_tool_call",
        )
    arguments_text = function.get("arguments")
    if (
        not isinstance(arguments_text, str)
        or len(arguments_text.encode("utf-8")) > _MAX_TOOL_ARGUMENT_BYTES
    ):
        raise DoubaoActorTransportError(
            "Doubao tool arguments are missing or too large",
            error_code="provider_invalid_tool_call",
        )
    try:
        arguments = json.loads(arguments_text)
    except json.JSONDecodeError:
        raise DoubaoActorTransportError(
            "Doubao tool arguments are not valid JSON",
            error_code="provider_invalid_tool_call",
        ) from None
    if not isinstance(arguments, Mapping) or set(arguments) != {"cmd"}:
        raise DoubaoActorTransportError(
            "Doubao exec_command arguments must contain only cmd",
            error_code="provider_invalid_tool_call",
        )
    command = arguments.get("cmd")
    if not isinstance(command, str) or not command.strip():
        raise DoubaoActorTransportError(
            "Doubao exec_command cmd must be non-empty text",
            error_code="provider_invalid_tool_call",
        )
    call_id = str(raw_call.get("id") or "").strip()
    if not call_id:
        raise DoubaoActorTransportError(
            "Doubao tool call is missing its id",
            error_code="provider_invalid_tool_call",
        )
    return _ToolCall(
        call_id=call_id,
        command=command.strip(),
        provider_value={
            "id": call_id,
            "type": "function",
            "function": {
                "name": "exec_command",
                "arguments": arguments_text,
            },
        },
    )


def _loopx_command_tokens(command: str) -> list[str] | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    for index, token in enumerate(tokens):
        if Path(token).name == "loopx":
            command_tokens = tokens[index:]
            if any(token in {";", "&&", "||", "|"} for token in command_tokens):
                return None
            return command_tokens
    return None


def _argument_value(tokens: list[str], option: str) -> str | None:
    try:
        index = tokens.index(option)
    except ValueError:
        return None
    return tokens[index + 1] if index + 1 < len(tokens) else None


def _clock_output(command: str) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens or Path(tokens[0]).name != "date" or len(tokens) > 4:
        return None
    if any(
        token in {";", "&&", "||", "|"}
        or (index > 0 and not token.startswith(("-", "+")))
        for index, token in enumerate(tokens)
    ):
        return None
    if "-u" in tokens or "--utc" in tokens:
        return "2026-08-11T16:00:00Z\n"
    return "2026-08-12T00:00:00+08:00\n"


def _is_quota_guard(command: str) -> bool:
    tokens = _loopx_command_tokens(command)
    if not tokens:
        return False
    try:
        quota_index = tokens.index("quota")
    except ValueError:
        return False
    return bool(
        tokens[quota_index : quota_index + 2] == ["quota", "should-run"]
        and _argument_value(tokens, "--goal-id")
        == ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_GOAL_ID
        and _argument_value(tokens, "--agent-id")
        == ACTUAL_DEFAULT_MODEL_BEHAVIOR_FIXTURE_AGENT_ID
        and "--codex-app" in tokens
        and _argument_value(tokens, "--turn-instance-id")
    )


def _classify_tool_command(
    command: str,
    *,
    fixture: _ReplanEvidenceToolFixture,
    quota_observed: bool,
) -> tuple[str, str | None]:
    if command == fixture.required_evidence_command:
        if not quota_observed:
            return "evidence_log_before_quota", None
        return "evidence_log", None
    if _is_quota_guard(command):
        return (
            "quota_should_run",
            json.dumps(
                fixture.quota_packet,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    clock_output = _clock_output(command)
    if clock_output is not None:
        return "clock", clock_output
    if command in _READ_ONLY_PREFLIGHT_OUTPUTS:
        return "workspace_read", _READ_ONLY_PREFLIGHT_OUTPUTS[command]
    if " evidence-log " in f" {command} ":
        return "wrong_evidence_log", None
    return "unexpected_command", None


def _receipt(
    *,
    qualification_id: str,
    actor_ref: str,
    steps: list[dict[str, Any]],
    passed: bool,
    failure_code: str | None,
    required_evidence_command: str,
) -> dict[str, Any]:
    return {
        "schema_version": REPLAN_EVIDENCE_TOOL_BEHAVIOR_RECEIPT_SCHEMA_VERSION,
        "qualification_id": qualification_id,
        "actor_ref": actor_ref,
        "qualification_passed": passed,
        "failure_code": failure_code,
        "observed_tool_sequence": [step["kind"] for step in steps],
        "tool_call_count": len(steps),
        "evidence_log_matched_required_read": passed,
        "required_read_command_digest": _digest(required_evidence_command),
        "tool_call_receipts": steps,
        "boundary": {
            "raw_prompt_persisted": False,
            "raw_provider_response_persisted": False,
            "raw_command_persisted": False,
            "filesystem_writes_executed": False,
            "external_writes_executed": False,
            "shell_commands_executed": False,
        },
    }


class DoubaoReplanEvidenceToolBehaviorActor:
    """Run a bounded production-prompt function-tool loop without mutations."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DOUBAO_2_1_PRO_MODEL,
        timeout_seconds: float = 90.0,
        transport: DoubaoActorTransport = _direct_ark_transport,
    ) -> None:
        if not api_key.strip():
            raise RuntimeError("Doubao actor requires a runtime-injected API key")
        if model not in _ALLOWED_MODELS:
            raise ValueError(
                "Doubao actor model must be an allowlisted Doubao 2.1 model"
            )
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("Doubao actor timeout must be between 0 and 300 seconds")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        transport: DoubaoActorTransport = _direct_ark_transport,
        timeout_seconds: float = 90.0,
    ) -> DoubaoReplanEvidenceToolBehaviorActor:
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
        fixture = _build_fixture(fixture_root)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are Codex running one LoopX heartbeat. Follow the "
                    "heartbeat task and use the available shell tool when needed. "
                    "Choose each next action from the latest tool result."
                ),
            },
            {"role": "user", "content": fixture.task_body},
        ]
        steps: list[dict[str, Any]] = []
        quota_observed = False
        seen_once: set[str] = set()
        actor_ref = f"ark:{self._model}"

        for _ in range(REPLAN_EVIDENCE_TOOL_BEHAVIOR_MAX_CALLS):
            body = {
                "model": self._model,
                "messages": messages,
                "tools": [_EXEC_COMMAND_TOOL],
                "tool_choice": "auto",
                "thinking": {"type": "disabled"},
                "temperature": 0,
                "max_tokens": _MAX_PROVIDER_TOKENS,
                "stream": False,
            }
            try:
                response = self._transport(
                    endpoint=DOUBAO_CHAT_COMPLETIONS_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    body=json.dumps(
                        body,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    timeout_seconds=self._timeout_seconds,
                )
                tool_call = _provider_tool_call(response)
            except DoubaoActorTransportError:
                raise
            except Exception:
                raise DoubaoActorTransportError(
                    "Doubao tool behavior provider transport failed",
                    error_code="provider_transport_failed",
                ) from None
            if tool_call is None:
                return _receipt(
                    qualification_id=qualification_id,
                    actor_ref=actor_ref,
                    steps=steps,
                    passed=False,
                    failure_code="model_returned_without_tool_call",
                    required_evidence_command=fixture.required_evidence_command,
                )

            kind, tool_output = _classify_tool_command(
                tool_call.command,
                fixture=fixture,
                quota_observed=quota_observed,
            )
            steps.append(
                {
                    "ordinal": len(steps) + 1,
                    "kind": kind,
                    "command_digest": _digest(tool_call.command),
                }
            )
            if kind == "evidence_log":
                return _receipt(
                    qualification_id=qualification_id,
                    actor_ref=actor_ref,
                    steps=steps,
                    passed=True,
                    failure_code=None,
                    required_evidence_command=fixture.required_evidence_command,
                )
            if kind in {
                "evidence_log_before_quota",
                "wrong_evidence_log",
                "unexpected_command",
            }:
                return _receipt(
                    qualification_id=qualification_id,
                    actor_ref=actor_ref,
                    steps=steps,
                    passed=False,
                    failure_code=kind,
                    required_evidence_command=fixture.required_evidence_command,
                )
            if kind in {"clock", "quota_should_run"} and kind in seen_once:
                return _receipt(
                    qualification_id=qualification_id,
                    actor_ref=actor_ref,
                    steps=steps,
                    passed=False,
                    failure_code=f"repeated_{kind}",
                    required_evidence_command=fixture.required_evidence_command,
                )
            if kind in {"clock", "quota_should_run"}:
                seen_once.add(kind)
            if kind == "quota_should_run":
                quota_observed = True
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tool_call.provider_value],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.call_id,
                        "content": tool_output or "",
                    },
                ]
            )

        return _receipt(
            qualification_id=qualification_id,
            actor_ref=actor_ref,
            steps=steps,
            passed=False,
            failure_code="tool_call_budget_exhausted",
            required_evidence_command=fixture.required_evidence_command,
        )
