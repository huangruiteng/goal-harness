"""Bridge a material LoopX Chat action into the canonical governed Turn CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .control_plane.turn_driver.workspace_progress_validator import (
    workspace_progress_digest,
)


class ChatTurnAdmissionError(RuntimeError):
    """A material Chat turn failed before a committed governed receipt."""

    def __init__(self, message: str, *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = dict(payload or {})


def governed_session_lineage(
    action_store: Any,
    *,
    session_id: str,
    goal_id: str,
) -> dict[str, str] | None:
    """Resolve the latest applied material Todo lineage for one Goal Session."""

    for proposal in action_store.list(goal_id=goal_id, status="applied"):
        receipt = proposal.get("receipt")
        receipt = receipt if isinstance(receipt, Mapping) else {}
        resources = receipt.get("resource_ids")
        resources = resources if isinstance(resources, Mapping) else {}
        if str(resources.get("session_id") or "") != session_id:
            continue
        todo_id = str(resources.get("todo_id") or "")
        if not todo_id:
            todo_ids = resources.get("todo_ids")
            if isinstance(todo_ids, list) and todo_ids:
                todo_id = str(todo_ids[0] or "")
        agent_id = str(resources.get("agent_id") or "")
        if todo_id and agent_id:
            return {"todo_id": todo_id, "agent_id": agent_id}
    return None


def governed_execution_gate(kind: str) -> dict[str, str]:
    gates = {
        "todo_required": {
            "kind": "todo_required",
            "summary": "A governed first Agent Turn requires one explicit initial Todo.",
            "next_action": "Create and assign one bounded Todo, then start execution from the Goal Chat.",
        },
        "governed_turn_required": {
            "kind": "governed_turn_required",
            "summary": "Run correction requires a prior governed Todo on this Goal Session.",
            "next_action": "Start one explicitly assigned Todo, then retry the correction on the same Session.",
        },
    }
    try:
        return dict(gates[kind])
    except KeyError as exc:
        raise ValueError("unsupported governed execution gate") from exc


def submit_governed_goal_turn(
    runtime_controller: Any,
    *,
    goal_id: str,
    endpoint_id: str,
    governed_agent_id: str,
    todo_id: str,
    work_dir: Path,
    objective: str,
    client_turn_id: str,
    message: str,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Open the canonical Goal Session and queue one governed material Turn."""

    session, _resumed = runtime_controller.open_session(
        goal_id=goal_id,
        agent_id=endpoint_id,
        work_dir=work_dir,
        objective=objective,
        mode="resume_latest",
        channel_id=f"goal.{goal_id}",
        agent_goal_id=goal_id,
    )
    turn, created = runtime_controller.submit_governed_turn(
        session_id=str(session["session_id"]),
        client_turn_id=client_turn_id,
        message=message,
        todo_id=todo_id,
        governed_agent_id=governed_agent_id,
        work_dir=work_dir,
    )
    return session, turn, created


class LoopXChatTurnAdmission:
    """Run one Chat-requested Todo through fresh admission and settlement."""

    def __init__(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | Path | None = None,
        loopx_bin: str | None = None,
        codex_bin: str = "codex",
        timeout_seconds: float = 900.0,
        available_capabilities: Sequence[str] = (),
    ) -> None:
        self.registry_path = registry_path.expanduser().resolve()
        self.runtime_root_override = (
            str(Path(runtime_root_override).expanduser().resolve())
            if runtime_root_override is not None
            else None
        )
        self.loopx_bin = loopx_bin
        self.codex_bin = codex_bin
        self.timeout_seconds = max(30.0, timeout_seconds)
        self.available_capabilities = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in available_capabilities
                    if str(item).strip()
                }
            )
        )

    def _command_prefix(self) -> list[str]:
        if self.loopx_bin is None:
            return [sys.executable, "-m", "loopx"]
        resolved = (
            self.loopx_bin
            if "/" in self.loopx_bin and Path(self.loopx_bin).is_file()
            else shutil.which(self.loopx_bin)
        )
        if not resolved:
            raise ChatTurnAdmissionError(
                "LoopX CLI is unavailable for governed Chat execution"
            )
        return [str(resolved)]

    def __call__(
        self,
        *,
        goal_id: str,
        agent_id: str,
        todo_id: str,
        upstream_thread_id: str,
        work_dir: Path,
        turn_instance_id: str,
    ) -> dict[str, Any]:
        project = work_dir.expanduser().resolve()
        baseline_hash = workspace_progress_digest(project)
        validator_argv = [
            sys.executable,
            "-m",
            "loopx.control_plane.turn_driver.workspace_progress_validator",
            "--baseline-hash",
            baseline_hash,
        ]
        command = [
            *self._command_prefix(),
            "--format",
            "json",
            "--registry",
            str(self.registry_path),
        ]
        if self.runtime_root_override:
            command.extend(["--runtime-root", self.runtime_root_override])
        command.extend(
            [
                "turn",
                "run-once",
                "--goal-id",
                goal_id,
                "--agent-id",
                agent_id,
                "--host",
                "codex-cli",
                "--execution-mode",
                "isolated-headless",
                "--scheduler-owner",
                "agent_cli_loop",
                "--expected-todo-id",
                todo_id,
                "--turn-instance-id",
                turn_instance_id,
                "--project",
                str(project),
                "--codex-bin",
                self.codex_bin,
                "--codex-sandbox",
                "workspace-write",
                "--codex-resume-session-id",
                upstream_thread_id,
                "--validation-command-json",
                json.dumps(validator_argv, separators=(",", ":")),
                "--validation-failure-kind",
                "repair_required",
                "--scan-root",
                str(project),
                "--timeout-seconds",
                str(self.timeout_seconds),
                "--execute",
            ]
        )
        for capability in self.available_capabilities:
            command.extend(["--available-capability", capability])
        try:
            completed = subprocess.run(
                command,
                cwd=project,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds + 30.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ChatTurnAdmissionError(
                "governed LoopX Chat execution could not complete"
            ) from exc
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ChatTurnAdmissionError(
                "governed LoopX Chat execution returned no typed receipt"
            ) from exc
        if not isinstance(payload, dict):
            raise ChatTurnAdmissionError(
                "governed LoopX Chat execution returned an invalid receipt"
            )
        if completed.returncode != 0 or payload.get("ok") is not True:
            raise ChatTurnAdmissionError(
                str(
                    payload.get("reason")
                    or payload.get("error")
                    or "governed LoopX Chat execution failed"
                ),
                payload=payload,
            )
        return payload
