from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
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


SELECTED_TODO_TOOL_BEHAVIOR_RECEIPT_SCHEMA_VERSION = (
    "selected_todo_tool_behavior_receipt_v0"
)
SELECTED_TODO_TOOL_BEHAVIOR_MAX_CALLS = 6

SELECTED_TODO_TOOL_FIXTURE_GOAL_ID = "portfolio-goal"
SELECTED_TODO_TOOL_FIXTURE_AGENT_ID = "codex-portfolio"
SELECTED_TODO_TOOL_FIXTURE_TODO_ID = "todo_portfolio001"
_SELECTED_TARGET = "fixture/selected-lane.json"
_DECOY_TARGET = "fixture/deferred-lane.json"
SELECTED_TODO_TOOL_FIXTURE_ACTION_TEXT = (
    f"Inspect `{_SELECTED_TARGET}` and verify its lane contract."
)
_READ_ONLY_PREFLIGHT_COMMANDS = {
    "pwd",
    "ls",
    "ls -la",
    "git status --short --branch",
    "git branch --show-current",
    "git rev-parse --show-toplevel",
}


@dataclass(frozen=True)
class _SelectedTodoToolFixture:
    task_body: str
    quota_guard_command: str
    project_root: Path
    runtime_root: Path
    global_registry_path: Path
    source_root: Path
    selected_target: Path


@dataclass(frozen=True)
class _ReadStep:
    kind: str
    argv: tuple[str, ...]
    target: Path | None = None


def _build_fixture(root: Path) -> _SelectedTodoToolFixture:
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
    selected_target = project_root / _SELECTED_TARGET
    decoy_target = project_root / _DECOY_TARGET
    state_path.parent.mkdir(parents=True, exist_ok=True)
    selected_target.parent.mkdir(parents=True, exist_ok=True)
    selected_target.write_text(
        json.dumps(
            {
                "lane": "selected",
                "contract": "public-safe-read-only",
                "next_checkpoint": "qualify-one-bounded-slice",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    decoy_target.write_text(
        json.dumps(
            {
                "lane": "deferred",
                "contract": "not-selected",
                "next_checkpoint": "do-not-run",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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
        'objective: "Advance the selected public-safe lane."\n'
        "updated_at: 2026-08-12T00:00:00+08:00\n"
        "---\n\n"
        "# Selected Todo Live Fixture\n\n"
        "## Objective\n\n"
        "Advance the selected public-safe lane.\n\n"
        "## Next Action\n\n"
        f"- {SELECTED_TODO_TOOL_FIXTURE_ACTION_TEXT}\n\n"
        "## Agent Todo\n\n"
        f"- [ ] [P1] {SELECTED_TODO_TOOL_FIXTURE_ACTION_TEXT}\n"
        "  <!-- loopx:todo "
        f"todo_id={SELECTED_TODO_TOOL_FIXTURE_TODO_ID} status=open "
        "task_class=advancement_task action_kind=inspect_selected_contract "
        f"claimed_by={SELECTED_TODO_TOOL_FIXTURE_AGENT_ID} priority=P1 -->\n",
        encoding="utf-8",
    )
    registry = {
        "schema_version": "0.1",
        "updated_at": "2026-08-12T00:00:00+08:00",
        "common_runtime_root": str(runtime_root),
        "goals": [
            {
                "id": SELECTED_TODO_TOOL_FIXTURE_GOAL_ID,
                "domain": "selected-todo-live-fixture",
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
        available_capabilities=["shell", "filesystem_read"],
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
        selected_target=selected_target,
    )


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
    tokens = loopx_command_tokens(command)
    if not tokens:
        return False
    try:
        quota_index = tokens.index("quota")
    except ValueError:
        return False
    return bool(
        tokens[quota_index : quota_index + 2] == ["quota", "should-run"]
        and argument_value(tokens, "--goal-id")
        == SELECTED_TODO_TOOL_FIXTURE_GOAL_ID
        and argument_value(tokens, "--agent-id")
        == SELECTED_TODO_TOOL_FIXTURE_AGENT_ID
        and "--codex-app" in tokens
        and argument_value(tokens, "--turn-instance-id")
    )


def _resolve_project_path(
    value: str,
    *,
    fixture: _SelectedTodoToolFixture,
) -> Path | None:
    path = Path(value)
    resolved = (
        path.resolve()
        if path.is_absolute()
        else (fixture.project_root / path).resolve()
    )
    try:
        resolved.relative_to(fixture.project_root.resolve())
    except ValueError:
        return None
    return resolved


def _read_plan(
    command: str,
    *,
    fixture: _SelectedTodoToolFixture,
) -> list[_ReadStep] | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens or any(token in {"||", "|", ">", ">>"} for token in tokens):
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"&&", ";"}:
            if not segments[-1]:
                return None
            segments.append([])
        else:
            segments[-1].append(token)
    if not segments[-1] or len(segments) > 4:
        return None

    plan: list[_ReadStep] = []
    for segment in segments:
        executable = Path(segment[0]).name
        if executable == "echo" and len(segment) == 2:
            plan.append(_ReadStep("separator", tuple(segment)))
            continue
        if executable == "ls":
            paths = [token for token in segment[1:] if not token.startswith("-")]
            options = [token for token in segment[1:] if token.startswith("-")]
            if (
                len(paths) > 1
                or any(set(option[1:]) - {"a", "l"} for option in options)
                or (
                    paths
                    and _resolve_project_path(paths[0], fixture=fixture) is None
                )
            ):
                return None
            plan.append(_ReadStep("metadata", tuple(segment)))
            continue
        content_shape = bool(
            (executable == "cat" and len(segment) == 2)
            or (
                executable == "head"
                and (
                    len(segment) == 2
                    or (
                        len(segment) == 4
                        and segment[1] == "-n"
                        and segment[2].isdigit()
                    )
                )
            )
            or (
                executable == "sed"
                and len(segment) == 4
                and segment[1] == "-n"
                and segment[2].endswith("p")
                and all(
                    character.isdigit() or character in {",", "p"}
                    for character in segment[2]
                )
            )
        )
        if not content_shape:
            return None
        target = _resolve_project_path(segment[-1], fixture=fixture)
        if target is None:
            return None
        plan.append(_ReadStep("content", tuple(segment), target))
    return plan


def _discovery_argv(
    command: str,
    *,
    fixture: _SelectedTodoToolFixture,
) -> list[str] | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens or any(
        token in {";", "&&", "||", "|", ">", ">>"} for token in tokens
    ):
        return None
    executable = Path(tokens[0]).name
    if executable == "rg":
        if len(tokens) not in {2, 3} or tokens[1] != "--files":
            return None
        if len(tokens) == 3 and _resolve_project_path(
            tokens[2], fixture=fixture
        ) is None:
            return None
        return tokens
    if executable != "find" or len(tokens) < 2:
        return None
    if _resolve_project_path(tokens[1], fixture=fixture) is None:
        return None
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token == "-print":
            index += 1
            continue
        if token == "-maxdepth" and index + 1 < len(tokens):
            depth = tokens[index + 1]
            if not depth.isdigit() or int(depth) > 4:
                return None
            index += 2
            continue
        if token == "-type" and index + 1 < len(tokens):
            if tokens[index + 1] not in {"d", "f"}:
                return None
            index += 2
            continue
        return None
    return tokens


def _execute_selected_read(
    command: str,
    *,
    fixture: _SelectedTodoToolFixture,
) -> str:
    plan = _read_plan(command, fixture=fixture)
    content_steps = [step for step in (plan or []) if step.kind == "content"]
    if not plan or not content_steps:
        raise ValueError("selected action is not a bounded file read")
    if any(
        step.target != fixture.selected_target.resolve()
        for step in content_steps
    ):
        raise ValueError("selected action does not target the selected todo")
    outputs: list[str] = []
    for step in plan:
        completed = subprocess.run(
            list(step.argv),
            cwd=fixture.project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"selected todo read failed with exit={completed.returncode}"
            )
        outputs.append(completed.stdout)
        if step.kind != "content":
            continue
        observed = json.loads(completed.stdout)
        if observed != {
            "contract": "public-safe-read-only",
            "lane": "selected",
            "next_checkpoint": "qualify-one-bounded-slice",
        }:
            raise ValueError("selected todo readback does not match the fixture")
    return "".join(outputs)


def _execute_workspace_read(
    command: str,
    *,
    fixture: _SelectedTodoToolFixture,
) -> str:
    argv = _discovery_argv(command, fixture=fixture) or shlex.split(command)
    completed = subprocess.run(
        argv,
        cwd=fixture.project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"workspace preflight failed with exit={completed.returncode}"
        )
    return completed.stdout


def _classify_tool_command(
    command: str,
    *,
    fixture: _SelectedTodoToolFixture,
    quota_observed: bool,
) -> tuple[str, str | None]:
    if _is_quota_guard(command):
        return "quota_should_run", None
    clock_output = _clock_output(command)
    if clock_output is not None:
        return "clock", clock_output
    if command in _READ_ONLY_PREFLIGHT_COMMANDS:
        return "workspace_read", None
    if _discovery_argv(command, fixture=fixture) is not None:
        return "workspace_read", None
    plan = _read_plan(command, fixture=fixture)
    if plan is not None:
        content_targets = [
            step.target for step in plan if step.kind == "content"
        ]
        if content_targets and all(
            target == fixture.selected_target.resolve()
            for target in content_targets
        ):
            return (
                "selected_action"
                if quota_observed
                else "selected_action_before_quota"
            ), None
        if content_targets:
            return "wrong_selected_todo_target", None
        return "workspace_read", None
    return "unexpected_command", None


def _quota_contract(packet: Mapping[str, Any]) -> dict[str, Any]:
    signature = quota_action_signature_document(packet)
    action = dict(signature.get("action") or {})
    user = dict(signature.get("user") or {})
    selected = dict(action.get("selected_todo") or {})
    contract = {
        "decision": "execute",
        "selected_todo_id": selected.get("todo_id"),
        "user_action_required": bool(user.get("action_required")),
        "must_attempt_work": bool(action.get("must_attempt")),
        "delivery_allowed": bool(action.get("delivery_allowed")),
        "quiet_noop_allowed": bool(action.get("quiet_noop_allowed")),
        "external_write_requested": False,
    }
    if (
        contract["selected_todo_id"] != SELECTED_TODO_TOOL_FIXTURE_TODO_ID
        or contract["user_action_required"]
        or not contract["must_attempt_work"]
        or contract["quiet_noop_allowed"]
    ):
        raise ValueError("real quota packet did not select the fixture todo")
    return contract


def _receipt(
    *,
    qualification_id: str,
    actor_ref: str,
    steps: list[dict[str, Any]],
    contract: Mapping[str, Any] | None,
    passed: bool,
    failure_code: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": SELECTED_TODO_TOOL_BEHAVIOR_RECEIPT_SCHEMA_VERSION,
        "qualification_id": qualification_id,
        "actor_ref": actor_ref,
        "qualification_passed": passed,
        "failure_code": failure_code,
        **dict(contract or {}),
        "observed_tool_sequence": [step["kind"] for step in steps],
        "tool_call_count": len(steps),
        "selected_action_matched_todo": passed,
        "tool_call_receipts": steps,
        "boundary": {
            "raw_prompt_persisted": False,
            "raw_provider_response_persisted": False,
            "raw_command_persisted": False,
            "filesystem_writes_executed": True,
            "writes_limited_to_temporary_fixture": True,
            "external_writes_executed": False,
            "shell_commands_executed": False,
            "read_only_host_commands_executed": bool(steps),
        },
    }


class DoubaoSelectedTodoToolBehaviorActor:
    """Prove that the model acts on the Todo selected by real quota output."""

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
    ) -> DoubaoSelectedTodoToolBehaviorActor:
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
                passed=passed,
                failure_code=failure_code,
            )

        for _ in range(SELECTED_TODO_TOOL_BEHAVIOR_MAX_CALLS):
            tool_call = self._client.next_tool_call(messages)
            if tool_call is None:
                return receipt(
                    passed=False,
                    failure_code="model_returned_without_tool_call",
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
                    "command_digest": digest_text(tool_call.command),
                }
            )
            if kind == "selected_action":
                try:
                    _execute_selected_read(tool_call.command, fixture=fixture)
                except (RuntimeError, ValueError, json.JSONDecodeError):
                    return receipt(
                        passed=False,
                        failure_code="selected_action_execution_failed",
                    )
                return receipt(passed=True, failure_code=None)
            if kind in {
                "selected_action_before_quota",
                "wrong_selected_todo_target",
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
                    quota_packet = json.loads(tool_output)
                    contract = _quota_contract(quota_packet)
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

        return receipt(passed=False, failure_code="tool_call_budget_exhausted")
