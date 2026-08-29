"""Run one external-agent phase without taking benchmark ownership.

The surrounding benchmark harness owns task provisioning, container lifecycle,
verification, and score calculation. This module only consumes a small
versioned request, invokes a runner-selected solver command in the supplied
workspace, and writes a public-safe result receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

EXTERNAL_AGENT_REQUEST_SCHEMA_VERSION = "external_agent_request_v1"
EXTERNAL_AGENT_RESULT_SCHEMA_VERSION = "external_agent_result_v1"
EXTERNAL_AGENT_CONTAINMENT_SCHEMA_VERSION = "external_agent_containment_v1"
EXTERNAL_AGENT_CONTAINMENT_VERIFICATION_SCHEMA_VERSION = (
    "external_agent_containment_verification_v1"
)
LOOPX_EXTERNAL_AGENT_PHASE_RECEIPT_SCHEMA_VERSION = (
    "loopx_external_agent_phase_receipt_v1"
)
_MAX_TIMEOUT_SECONDS = 86_400.0
_RESULT_STATUSES = {"succeeded", "failed"}
_CONTAINMENT_KINDS = {
    "container",
    "cgroup_v2",
    "pid_namespace",
    "virtual_machine",
    "windows_job_object",
}
_CONTAINMENT_POSTCONDITION = "drained_before_result_consumption"
_OPAQUE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:@/-]{1,160}$")
_SOLVER_ENVIRONMENT_ALLOWLIST = (
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "WINDIR",
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("external_agent_request_unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("external_agent_request_not_object")
    return value


def _validate_request(
    value: Mapping[str, Any],
) -> tuple[str, Path, float, str, str]:
    if value.get("schema_version") != EXTERNAL_AGENT_REQUEST_SCHEMA_VERSION:
        raise ValueError("external_agent_request_schema_unsupported")

    instruction = value.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("external_agent_request_instruction_missing")

    workspace_value = value.get("workspace")
    if not isinstance(workspace_value, str) or not workspace_value.strip():
        raise ValueError("external_agent_request_workspace_missing")
    try:
        workspace = Path.cwd()
    except OSError as exc:
        raise ValueError("external_agent_runner_workspace_invalid") from exc
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("external_agent_runner_workspace_invalid")
    if workspace_value != str(workspace):
        raise ValueError("external_agent_request_workspace_mismatch")

    timeout_value = value.get("timeout_seconds")
    if isinstance(timeout_value, bool) or not isinstance(timeout_value, (int, float)):
        raise ValueError("external_agent_request_timeout_invalid")
    timeout_seconds = float(timeout_value)
    if not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        raise ValueError("external_agent_request_timeout_invalid")

    containment = value.get("containment")
    if not isinstance(containment, Mapping) or set(containment) != {
        "schema_version",
        "kind",
        "timeout_owner",
        "termination_postcondition",
        "verification",
    }:
        raise ValueError("external_agent_containment_contract_invalid")
    if (
        containment.get("schema_version")
        != EXTERNAL_AGENT_CONTAINMENT_SCHEMA_VERSION
        or containment.get("kind") not in _CONTAINMENT_KINDS
        or containment.get("timeout_owner") != "runner"
        or containment.get("termination_postcondition")
        != _CONTAINMENT_POSTCONDITION
    ):
        raise ValueError("external_agent_containment_contract_invalid")

    verification = containment.get("verification")
    if not isinstance(verification, Mapping) or set(verification) != {
        "schema_version",
        "status",
        "authority",
        "receipt_ref",
    }:
        raise ValueError("external_agent_containment_verification_invalid")
    receipt_ref = str(verification.get("receipt_ref") or "")
    if (
        verification.get("schema_version")
        != EXTERNAL_AGENT_CONTAINMENT_VERIFICATION_SCHEMA_VERSION
        or verification.get("status") != "verified"
        or verification.get("authority") != "runner"
        or not _OPAQUE_REF_PATTERN.fullmatch(receipt_ref)
    ):
        raise ValueError("external_agent_containment_verification_invalid")

    return (
        instruction,
        workspace,
        timeout_seconds,
        str(containment["kind"]),
        receipt_ref,
    )


def _validate_solver_command(value: Sequence[str]) -> list[str]:
    if isinstance(value, (str, bytes)):
        raise ValueError("external_agent_solver_command_invalid")
    command = [item for item in value if isinstance(item, str) and item]
    if len(command) != len(value) or not command:
        raise ValueError("external_agent_solver_command_invalid")
    return command


def _solver_environment(environment: Mapping[str, str]) -> dict[str, str]:
    safe_environment = {
        key: os.environ[key]
        for key in _SOLVER_ENVIRONMENT_ALLOWLIST
        if key in os.environ
    }
    safe_environment.update(environment)
    return safe_environment


def _result(
    *,
    status: str,
    exit_code: int | None,
    duration_ms: int,
    instruction: str | None,
    command: Sequence[str],
    classification: str,
    containment_kind: str | None = None,
    containment_verification_ref: str | None = None,
) -> dict[str, Any]:
    if status not in _RESULT_STATUSES:
        raise ValueError("external_agent_result_status_invalid")
    receipt: dict[str, Any] = {
        "schema_version": LOOPX_EXTERNAL_AGENT_PHASE_RECEIPT_SCHEMA_VERSION,
        "classification": classification,
        "command_recorded": False,
        "command_argument_count": len(command),
        "duration_ms": max(0, duration_ms),
        "instruction_recorded": False,
        "workspace_recorded": False,
    }
    if instruction is not None:
        receipt["instruction_sha256"] = _sha256(instruction)
        receipt["instruction_chars"] = len(instruction)
    if containment_kind is not None:
        receipt["containment_contract_validated"] = True
        receipt["containment_kind"] = containment_kind
        receipt["containment_verification_authority"] = "runner"
        receipt["containment_verification_status"] = "verified"
        receipt["containment_termination_postcondition"] = (
            _CONTAINMENT_POSTCONDITION
        )
        receipt["timeout_enforced_locally"] = False
        receipt["timeout_owner"] = "runner"
    if containment_verification_ref is not None:
        receipt["containment_verification_ref_sha256"] = _sha256(
            containment_verification_ref
        )
    return {
        "schema_version": EXTERNAL_AGENT_RESULT_SCHEMA_VERSION,
        "status": status,
        "exit_code": exit_code,
        "receipt": receipt,
    }


def run_external_agent_phase(
    request: Mapping[str, Any],
    *,
    solver_command: Sequence[str],
    request_path: Path | None = None,
) -> dict[str, Any]:
    """Execute one runner-owned solver command from an external-agent request."""

    (
        instruction,
        workspace,
        timeout_seconds,
        containment_kind,
        containment_verification_ref,
    ) = _validate_request(request)
    command = _validate_solver_command(solver_command)
    environment = {
        "LOOPX_EXTERNAL_AGENT_REQUEST_SCHEMA_VERSION": (
            EXTERNAL_AGENT_REQUEST_SCHEMA_VERSION
        ),
        "LOOPX_EXTERNAL_AGENT_INSTRUCTION_SHA256": _sha256(instruction),
        "LOOPX_EXTERNAL_AGENT_INSTRUCTION_CHARS": str(len(instruction)),
        "LOOPX_EXTERNAL_AGENT_WORKSPACE": str(workspace),
        "LOOPX_EXTERNAL_AGENT_TIMEOUT_SECONDS": str(timeout_seconds),
    }
    if request_path is not None:
        environment["LOOPX_EXTERNAL_AGENT_REQUEST"] = str(request_path)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=_solver_environment(environment),
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
            text=True,
        )
        process.communicate(instruction)
        exit_code = process.returncode
    except OSError:
        return _result(
            status="failed",
            exit_code=None,
            duration_ms=int((time.monotonic() - started) * 1000),
            instruction=instruction,
            command=command,
            classification="solver_startup_failed",
            containment_kind=containment_kind,
            containment_verification_ref=containment_verification_ref,
        )

    return _result(
        status="succeeded" if exit_code == 0 else "failed",
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        instruction=instruction,
        command=command,
        classification=(
            "solver_completed"
            if exit_code == 0
            else "solver_exited_nonzero"
        ),
        containment_kind=containment_kind,
        containment_verification_ref=containment_verification_ref,
    )


def write_external_agent_result(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(dict(result), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def execute_external_agent_request(
    *,
    request_path: Path,
    result_path: Path,
    solver_command: Sequence[str],
    execute: bool,
) -> dict[str, Any]:
    """Validate one request and optionally run its solver command."""

    if execute:
        result_path.unlink(missing_ok=True)
    try:
        command = _validate_solver_command(solver_command)
        request = _load_json_object(request_path)
        (
            instruction,
            _workspace,
            _timeout_seconds,
            containment_kind,
            containment_verification_ref,
        ) = _validate_request(request)
        result = (
            run_external_agent_phase(
                request,
                solver_command=command,
                request_path=request_path,
            )
            if execute
            else _result(
                status="succeeded",
                exit_code=0,
                duration_ms=0,
                instruction=instruction,
                command=command,
                classification="request_validated_not_executed",
                containment_kind=containment_kind,
                containment_verification_ref=containment_verification_ref,
            )
        )
    except (TypeError, ValueError):
        result = _result(
            status="failed",
            exit_code=None,
            duration_ms=0,
            instruction=None,
            command=(),
            classification="agent_phase_input_invalid",
        )
    write_external_agent_result(result_path, result)
    return result
