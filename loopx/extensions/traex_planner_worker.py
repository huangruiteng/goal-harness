from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ..planner_worker import AdapterTurn, ValidationResult
from ..planner_worker_runtime import run_planner_worker_once


TRAEX_PLANNER_WORKER_PROBE_SCHEMA_VERSION = "traex_planner_worker_probe_v1"
DEFAULT_TRAEX_PLANNER_MODEL = "GPT-5.5"
DEFAULT_TRAEX_WORKER_MODEL = "DeepSeek-V4-Flash"
DEFAULT_VALIDATION_EXECUTABLES = frozenset(
    {"python", "python3", "pytest", "go", "npm", "npx", "cargo"}
)


class TraexPlannerWorkerError(RuntimeError):
    """Raised when the experimental TraeX adapter cannot complete safely."""


def _assistant_text_and_usage(jsonl: str) -> tuple[str, dict[str, int], bool]:
    parts: list[str] = []
    usage: dict[str, int] = {}
    completed = False
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraexPlannerWorkerError("traex returned invalid JSONL") from exc
        if item.get("type") == "turn.completed":
            completed = True
            if isinstance(item.get("usage"), dict):
                usage = {
                    key: int(value)
                    for key, value in item["usage"].items()
                    if isinstance(value, int) and not isinstance(value, bool)
                }
        payload = item.get("item")
        if isinstance(payload, dict) and payload.get("type") == "agent_message":
            parts.append(str(payload.get("text") or ""))
    usage_complete = (
        completed
        and "input_tokens" in usage
        and "output_tokens" in usage
    )
    return "\n".join(parts).strip(), usage, usage_complete


def _run_traex_exec(
    *,
    traex_bin: str,
    model: str,
    prompt: str,
    cwd: Path,
    sandbox: str,
    timeout_seconds: float,
    minimal_context: bool,
) -> tuple[AdapterTurn, bool]:
    command = [
        traex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        sandbox,
        "--skip-git-repo-check",
        "--model",
        model,
    ]
    if minimal_context:
        command.extend(["--ignore-rules", "--ignore-user-config"])
    command.append(prompt)
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise TraexPlannerWorkerError(
            f"traex exec failed for model={model}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    assistant_text, usage, usage_complete = _assistant_text_and_usage(result.stdout)
    return (
        AdapterTurn(
            output_text=assistant_text,
            usage=usage,
            usage_complete=usage_complete,
        ),
        bool(result.stderr.strip()),
    )


class TraexPlannerAdapter:
    def __init__(
        self,
        *,
        traex_bin: str,
        timeout_seconds: float,
    ) -> None:
        self.traex_bin = traex_bin
        self.timeout_seconds = timeout_seconds
        self.stderr_present = False

    def plan(
        self,
        *,
        prompt: str,
        model_route: dict[str, str],
        cwd: Path,
    ) -> AdapterTurn:
        turn, self.stderr_present = _run_traex_exec(
            traex_bin=self.traex_bin,
            model=model_route["model"],
            prompt=prompt,
            cwd=cwd,
            sandbox="read-only",
            timeout_seconds=self.timeout_seconds,
            minimal_context=False,
        )
        return turn


class TraexWorkerAdapter:
    def __init__(
        self,
        *,
        traex_bin: str,
        timeout_seconds: float,
        minimal_context: bool,
    ) -> None:
        self.traex_bin = traex_bin
        self.timeout_seconds = timeout_seconds
        self.minimal_context = minimal_context
        self.stderr_present = False

    def execute(
        self,
        *,
        prompt: str,
        model_route: dict[str, str],
        cwd: Path,
    ) -> AdapterTurn:
        turn, self.stderr_present = _run_traex_exec(
            traex_bin=self.traex_bin,
            model=model_route["model"],
            prompt=prompt,
            cwd=cwd,
            sandbox="workspace-write",
            timeout_seconds=self.timeout_seconds,
            minimal_context=self.minimal_context,
        )
        return turn


class SubprocessValidationRunner:
    """Run bounded validation commands without shell expansion."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        allowed_executables: frozenset[str] = DEFAULT_VALIDATION_EXECUTABLES,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.allowed_executables = allowed_executables

    def __call__(self, command: str, cwd: Path) -> ValidationResult:
        try:
            argv = shlex.split(command)
        except ValueError:
            return ValidationResult(command=command, passed=False, exit_code=None)
        if not argv or Path(argv[0]).name not in self.allowed_executables:
            return ValidationResult(command=command, passed=False, exit_code=None)
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ValidationResult(command=command, passed=False, exit_code=None)
        return ValidationResult(
            command=command,
            passed=result.returncode == 0,
            exit_code=result.returncode,
        )


def run_traex_planner_worker_probe(
    *,
    objective: str,
    task_instruction: str,
    traex_bin: str = "traex",
    planner_model: str = DEFAULT_TRAEX_PLANNER_MODEL,
    worker_model: str = DEFAULT_TRAEX_WORKER_MODEL,
    strong_worker_model: str | None = None,
    cwd: Path | str = ".",
    worker_minimal_context: bool = True,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Run the experimental TraeX adapter through the core vertical slice."""

    workdir = Path(cwd).resolve()
    planner = TraexPlannerAdapter(
        traex_bin=traex_bin,
        timeout_seconds=timeout_seconds,
    )
    worker = TraexWorkerAdapter(
        traex_bin=traex_bin,
        timeout_seconds=timeout_seconds,
        minimal_context=worker_minimal_context,
    )
    try:
        receipt = run_planner_worker_once(
            objective=objective,
            task_instruction=task_instruction,
            cwd=workdir,
            planner=planner,
            worker=worker,
            validation_runner=SubprocessValidationRunner(
                timeout_seconds=timeout_seconds,
            ),
            model_routes={
                "planner": {"model": planner_model, "effort": "high"},
                "cheap_worker": {"model": worker_model, "effort": "medium"},
                "strong_worker": {
                    "model": strong_worker_model or planner_model,
                    "effort": "high",
                },
            },
        )
    except ValueError as exc:
        raise TraexPlannerWorkerError(
            f"invalid planner-worker contract: {exc}"
        ) from exc
    return {
        "schema_version": TRAEX_PLANNER_WORKER_PROBE_SCHEMA_VERSION,
        "runtime": "traex",
        "mode": "experimental_planner_worker",
        "receipt": receipt,
        "boundary": {
            "planner_sandbox": "read-only",
            "worker_sandbox": "workspace-write",
            "worker_minimal_context": bool(worker_minimal_context),
            "validation_shell": False,
            "raw_prompts_recorded": False,
            "raw_assistant_messages_recorded": False,
            "raw_stderr_recorded": False,
            "planner_stderr_present": planner.stderr_present,
            "worker_stderr_present": worker.stderr_present,
        },
    }


__all__ = [
    "DEFAULT_TRAEX_PLANNER_MODEL",
    "DEFAULT_TRAEX_WORKER_MODEL",
    "TRAEX_PLANNER_WORKER_PROBE_SCHEMA_VERSION",
    "SubprocessValidationRunner",
    "TraexPlannerAdapter",
    "TraexPlannerWorkerError",
    "TraexWorkerAdapter",
    "run_traex_planner_worker_probe",
]

