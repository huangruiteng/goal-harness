"""Provider-neutral governed execution for material external capabilities.

The provider owns its domain operation and asynchronous run. LoopX owns the
selected-Todo admission, durable invocation journal, typed effect receipt,
writeback-before-spend ordering, and settlement replay identity.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..control_plane.effect_program import settlement_result_payload
from ..control_plane.effect_runtime import effect_runtime_result
from ..control_plane.host_adapter_settlement import (
    HostGuardState,
    classify_host_guard_snapshot,
)
from ..control_plane.runtime.public_safety import validate_public_safe_value
from ..control_plane.turn_driver.settlement import execute_turn_driver_settlement
from ..control_plane.turn_driver.transaction import (
    TRANSACTION_PHASES,
    build_loopx_turn_transaction_plan,
)
from ..file_lock import exclusive_file_lock
from .capability_admission import prepare_external_capability_invocation
from .runtime import execute_extension_runtime_binding

GOVERNED_CAPABILITY_RUN_SCHEMA_VERSION = "loopx_governed_capability_run_v0"
GOVERNED_CAPABILITY_RECEIPT_SCHEMA_VERSION = (
    "loopx_governed_capability_execution_receipt_v0"
)
MaterialEffect = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def default_governed_capability_run_dir(
    runtime_root: str | Path | None = None,
) -> Path:
    root = (
        Path(runtime_root).expanduser()
        if runtime_root is not None
        else Path.home() / ".codex" / "loopx"
    )
    return root / "extensions" / "governed-capability-runs"


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    import hashlib

    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): deepcopy(item) for key, item in value.items()}


def _journal_path(run_dir: str | Path, invocation_id: str) -> Path:
    suffix = invocation_id.removeprefix("capability-")
    if (
        not invocation_id.startswith("capability-")
        or len(suffix) != 24
        or any(character not in "0123456789abcdef" for character in suffix)
    ):
        raise ValueError("governed capability invocation_id is invalid")
    return Path(run_dir).expanduser() / f"{invocation_id}.json"


def _read_journal(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("governed capability invocation does not exist") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "governed capability invocation journal is unreadable"
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != GOVERNED_CAPABILITY_RUN_SCHEMA_VERSION
    ):
        raise ValueError("governed capability invocation journal is invalid")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("governed capability invocation journal must use mode 0600")
    return value


def _write_journal(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(serialized)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _settlement_identity(transaction_plan: Mapping[str, Any]) -> dict[str, Any]:
    settlement = _mapping(transaction_plan.get("settlement_plan"), "settlement plan")
    return _mapping(settlement.get("identity"), "settlement identity")


def _require_admission(
    admission: Mapping[str, Any],
    *,
    expected_identity: Mapping[str, Any],
    require_should_run: bool,
    todo_contract: Mapping[str, Any] | None,
) -> None:
    if require_should_run and admission.get("should_run") is not True:
        raise ValueError("governed capability admission requires should_run=true")
    guard = classify_host_guard_snapshot(
        json.dumps(dict(admission), ensure_ascii=False, sort_keys=True)
    )
    if guard.state is not HostGuardState.SELECTED:
        raise ValueError(guard.reason or "quota guard did not select a Todo")
    if guard.settlement_identity is None:
        raise ValueError("quota guard did not return a typed settlement identity")
    observed = guard.settlement_identity.as_dict()
    expected = {
        key: str(expected_identity.get(key) or "")
        for key in ("goal_id", "agent_id", "todo_id", "turn_instance_id", "effect_id")
    }
    if any(observed.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "quota guard settlement identity does not match the invocation"
        )
    if todo_contract is not None:
        effect_runtime_result(
            "governed_capability.validate_admission",
            {
                "admission": dict(admission),
                "todo_id": expected["todo_id"],
                "todo_contract": dict(todo_contract),
            },
        )


def _validated_governed_capability_result(
    value: Mapping[str, Any],
    *,
    invocation_id: str,
    effect_id: str,
    operation: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    payload = effect_runtime_result(
        "governed_capability.validate_result",
        {
            "value": dict(value),
            "invocation_id": invocation_id,
            "effect_id": effect_id,
            "result_schema": operation.get("result_schema"),
            "effect_class": operation.get("effect_class"),
        },
    )
    if not isinstance(payload, Mapping):
        raise RuntimeError("TypeScript governed capability result shape mismatch")
    result = _mapping(payload.get("result"), "external capability result")
    journal_status = str(payload.get("journal_status") or "")
    if journal_status not in {"running", "ready_to_settle"}:
        raise RuntimeError("TypeScript governed capability status shape mismatch")
    validate_public_safe_value(result, path="provider_result")
    return result, journal_status


def validate_governed_capability_result(
    value: Mapping[str, Any],
    *,
    invocation_id: str,
    effect_id: str,
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    """Adapt the TS-owned material provider state validation."""

    result, _journal_status = _validated_governed_capability_result(
        value,
        invocation_id=invocation_id,
        effect_id=effect_id,
        operation=operation,
    )
    return result


def _validate_journal(
    journal: Mapping[str, Any],
    *,
    invocation_id: str,
) -> None:
    if journal.get("invocation_id") != invocation_id:
        raise ValueError("governed capability journal invocation identity is invalid")
    transaction_plan = _mapping(journal.get("transaction_plan"), "transaction plan")
    identity = _settlement_identity(transaction_plan)
    expected_top_level = {
        key: identity.get(key)
        for key in ("goal_id", "agent_id", "todo_id", "turn_instance_id", "effect_id")
    }
    if any(journal.get(key) != value for key, value in expected_top_level.items()):
        raise ValueError("governed capability journal settlement identity is invalid")

    request = _mapping(journal.get("request"), "provider request")
    if request.get("invocation_id") != invocation_id:
        raise ValueError("governed capability journal request identity is invalid")
    if request.get("authority") != identity:
        raise ValueError("governed capability journal request authority is invalid")
    lifecycle = _mapping(request.get("lifecycle"), "provider request lifecycle")
    if set(lifecycle) != {"phase", "idempotency_key"} or not (
        lifecycle.get("phase") == "start"
        and lifecycle.get("idempotency_key") == identity.get("effect_id")
    ):
        raise ValueError("governed capability journal start lifecycle is invalid")
    validate_public_safe_value(request, path="provider_request")
    if journal.get("request_digest") != _canonical_digest(request):
        raise ValueError("governed capability journal request digest is invalid")

    operation_profile = _mapping(journal.get("operation_profile"), "operation profile")
    if operation_profile.get("effect_class") != "external_write":
        raise ValueError("governed capability journal effect class is invalid")
    _mapping(journal.get("provider_binding"), "provider binding")
    status = str(journal.get("status") or "")
    provider_result = journal.get("provider_result")
    if provider_result is None:
        if status != "starting":
            raise ValueError("governed capability journal provider state is invalid")
        return
    result = _mapping(provider_result, "external capability result")
    validated, provider_status = _validated_governed_capability_result(
        result,
        invocation_id=invocation_id,
        effect_id=str(identity["effect_id"]),
        operation=operation_profile,
    )
    if validated != result:
        raise ValueError("governed capability journal provider result is invalid")
    allowed_statuses = (
        {"running"}
        if provider_status == "running"
        else {"ready_to_settle", "settlement_failed", "committed"}
    )
    if status not in allowed_statuses:
        raise ValueError("governed capability journal status is invalid")
    if provider_status == "running":
        if any(
            journal.get(field) is not None
            for field in ("writeback", "quota_spend", "settlement_result")
        ):
            raise ValueError("running governed capability has settlement receipts")
        return

    effect_receipt = _mapping(result.get("effect_receipt"), "external effect receipt")
    effect_receipt_digest = _canonical_digest(effect_receipt)
    for field, require_receipt_digest in (
        ("writeback", True),
        ("quota_spend", False),
    ):
        stored = journal.get(field)
        if stored is None:
            continue
        payload = _mapping(stored, f"governed capability {field}")
        checked = effect_runtime_result(
            "governed_capability.validate_settlement_callback",
            {
                "payload": payload,
                "effect_id": identity["effect_id"],
                "effect_receipt_digest": effect_receipt_digest,
                "require_receipt_digest": require_receipt_digest,
            },
        )
        if checked != payload:
            raise ValueError(f"governed capability journal {field} is invalid")
    if status == "committed":
        for field in ("writeback", "quota_spend"):
            receipt_payload = journal.get(field)
            if not (
                isinstance(receipt_payload, Mapping)
                and receipt_payload.get("ok") is True
                and receipt_payload.get("appended") is True
            ):
                raise ValueError(
                    f"committed governed capability has no {field} receipt"
                )
        settlement_result = journal.get("settlement_result")
        if not (
            isinstance(settlement_result, Mapping)
            and settlement_result.get("failure") is None
        ):
            raise ValueError(
                "committed governed capability has no successful settlement result"
            )
    elif status == "settlement_failed":
        settlement_result = journal.get("settlement_result")
        if not (
            isinstance(settlement_result, Mapping)
            and isinstance(settlement_result.get("failure"), Mapping)
        ):
            raise ValueError(
                "failed governed capability has no typed settlement failure"
            )


def _public_receipt(journal: Mapping[str, Any], *, dry_run: bool) -> dict[str, Any]:
    provider_result = journal.get("provider_result")
    result = provider_result if isinstance(provider_result, Mapping) else {}
    return {
        "ok": True,
        "schema_version": GOVERNED_CAPABILITY_RECEIPT_SCHEMA_VERSION,
        "status": journal.get("status"),
        "dry_run": dry_run,
        "executed": not dry_run,
        "invocation_id": journal.get("invocation_id"),
        "request_digest": journal.get("request_digest"),
        "goal_id": journal.get("goal_id"),
        "agent_id": journal.get("agent_id"),
        "todo_id": journal.get("todo_id"),
        "turn_instance_id": journal.get("turn_instance_id"),
        "effect_id": journal.get("effect_id"),
        "provider_status": result.get("status"),
        "provider_result_digest": (_canonical_digest(result) if result else None),
        "settlement_result": journal.get("settlement_result"),
        "effects": {
            "provider_invoked": bool(provider_result),
            "external_write_observed": bool(result.get("effect_receipt")),
            "loopx_state_written": isinstance(journal.get("writeback"), Mapping),
            "quota_spent": isinstance(journal.get("quota_spend"), Mapping),
        },
    }


def start_governed_external_capability(
    *,
    state_file: str | Path,
    run_dir: str | Path,
    registry_path: str | Path,
    goal_id: str,
    agent_id: str,
    todo_id: str,
    turn_instance_id: str,
    capability_id: str,
    operation: str,
    provider_input: Mapping[str, Any],
    admission: Mapping[str, Any],
    execute: bool = False,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Preview or idempotently start one selected-Todo material operation."""

    transaction_plan = build_loopx_turn_transaction_plan(
        planned=True,
        lineage={"goal_id": goal_id, "agent_id": agent_id, "todo_id": todo_id},
        host="external-capability-provider",
        execution_mode="governed-asynchronous",
        session_action="resume",
        turn_instance_id=turn_instance_id,
    )
    identity = _settlement_identity(transaction_plan)
    prepared = prepare_external_capability_invocation(
        state_file=state_file,
        capability_id=capability_id,
        operation=operation,
        registry_path=registry_path,
        goal_id=goal_id,
        provider_input=provider_input,
        authority=identity,
    )
    operation_profile = _mapping(prepared["operation_profile"], "operation profile")
    if operation_profile.get("effect_class") != "external_write":
        raise ValueError("governed capability execution requires external_write")
    _require_admission(
        admission,
        expected_identity=identity,
        require_should_run=not execute,
        todo_contract=(
            _mapping(
                operation_profile.get("todo_contract"),
                "operation todo_contract",
            )
            if not execute
            else None
        ),
    )
    request = _mapping(prepared["request"], "provider request")
    request["lifecycle"] = {
        "phase": "start",
        "idempotency_key": identity["effect_id"],
    }
    validate_public_safe_value(request, path="provider_request")
    request_digest = _canonical_digest(request)
    binding = _mapping(prepared["binding"], "provider binding")
    invocation_id = str(prepared["invocation_id"])
    journal: dict[str, Any] = {
        "schema_version": GOVERNED_CAPABILITY_RUN_SCHEMA_VERSION,
        "status": "ready" if not execute else "starting",
        "invocation_id": invocation_id,
        "request_digest": request_digest,
        "request": request,
        "provider_binding": binding,
        "operation_profile": operation_profile,
        "transaction_plan": transaction_plan,
        "goal_id": goal_id,
        "agent_id": agent_id,
        "todo_id": todo_id,
        "turn_instance_id": turn_instance_id,
        "effect_id": identity["effect_id"],
        "completed_phases": [],
        "provider_result": None,
        "writeback": None,
        "quota_spend": None,
        "settlement_result": None,
    }
    if not execute:
        return _public_receipt(journal, dry_run=True)

    path = _journal_path(run_dir, invocation_id)
    with exclusive_file_lock(path, operation="start_governed_external_capability"):
        if path.exists():
            current = _read_journal(path)
            _validate_journal(current, invocation_id=invocation_id)
            if (
                current.get("request_digest") != request_digest
                or current.get("effect_id") != identity["effect_id"]
            ):
                raise ValueError("governed capability invocation replay does not match")
            if isinstance(current.get("provider_result"), Mapping):
                return _public_receipt(current, dry_run=False)
            journal = current
        else:
            _require_admission(
                admission,
                expected_identity=identity,
                require_should_run=True,
                todo_contract=_mapping(
                    operation_profile.get("todo_contract"),
                    "operation todo_contract",
                ),
            )
            _write_journal(path, journal)
        provider_result = execute_extension_runtime_binding(
            binding,
            request=request,
            environment=environment,
        )
        validated, journal_status = _validated_governed_capability_result(
            provider_result,
            invocation_id=invocation_id,
            effect_id=str(identity["effect_id"]),
            operation=operation_profile,
        )
        journal["provider_result"] = validated
        journal["status"] = journal_status
        _write_journal(path, journal)
        return _public_receipt(journal, dry_run=False)


def _settlement_callback(
    effect: MaterialEffect,
    *,
    context: Mapping[str, Any],
    effect_receipt_digest: str,
    effect_id: str,
    require_receipt_digest: bool,
) -> dict[str, Any]:
    payload = effect_runtime_result(
        "governed_capability.validate_settlement_callback",
        {
            "payload": dict(effect(context)),
            "effect_id": effect_id,
            "effect_receipt_digest": effect_receipt_digest,
            "require_receipt_digest": require_receipt_digest,
        },
    )
    return _mapping(payload, "governed capability settlement callback")


def reconcile_governed_external_capability(
    *,
    run_dir: str | Path,
    invocation_id: str,
    writeback: MaterialEffect,
    spend: MaterialEffect,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Poll and idempotently settle one asynchronous material invocation."""

    path = _journal_path(run_dir, invocation_id)
    with exclusive_file_lock(path, operation="reconcile_governed_external_capability"):
        journal = _read_journal(path)
        _validate_journal(journal, invocation_id=invocation_id)
        if journal.get("status") == "committed":
            return _public_receipt(journal, dry_run=False)
        identity = _settlement_identity(
            _mapping(journal.get("transaction_plan"), "transaction plan")
        )
        operation_profile = _mapping(
            journal.get("operation_profile"), "operation profile"
        )
        provider_result = journal.get("provider_result")
        if not isinstance(provider_result, Mapping):
            raise ValueError("governed capability provider start has no receipt")
        if provider_result.get("status") == "running":
            request = _mapping(journal.get("request"), "provider request")
            request["lifecycle"] = {
                "phase": "reconcile",
                "idempotency_key": identity["effect_id"],
                "follow_up": deepcopy(provider_result.get("follow_up")),
            }
            observed = execute_extension_runtime_binding(
                _mapping(journal.get("provider_binding"), "provider binding"),
                request=request,
                environment=environment,
            )
            provider_result, journal_status = _validated_governed_capability_result(
                observed,
                invocation_id=invocation_id,
                effect_id=str(identity["effect_id"]),
                operation=operation_profile,
            )
            journal["provider_result"] = provider_result
            journal["status"] = journal_status
            _write_journal(path, journal)
            if provider_result["status"] == "running":
                return _public_receipt(journal, dry_run=False)

        effect_receipt = _mapping(
            provider_result.get("effect_receipt"), "external effect receipt"
        )
        effect_receipt_digest = _canonical_digest(effect_receipt)
        context = {
            "settlement_identity": identity,
            "invocation_id": invocation_id,
            "provider_result_digest": _canonical_digest(provider_result),
            "effect_receipt": effect_receipt,
            "effect_receipt_digest": effect_receipt_digest,
        }

        def checkpoint(
            step_kind: object,
            payload: Mapping[str, Any],
            phases: tuple[str, ...],
        ) -> None:
            step_name = str(getattr(step_kind, "value", step_kind))
            journal["writeback" if step_name == "durable_writeback" else step_name] = (
                dict(payload)
            )
            journal["completed_phases"] = list(phases)
            _write_journal(path, journal)

        settlement = execute_turn_driver_settlement(
            _mapping(journal.get("transaction_plan"), "transaction plan"),
            transaction_phases=TRANSACTION_PHASES,
            completed_phases=(
                tuple(str(item) for item in journal["completed_phases"])
                if isinstance(journal.get("completed_phases"), list)
                and journal["completed_phases"]
                else ("host_execute", "typed_result", "validation")
            ),
            writeback_payload=(
                journal.get("writeback")
                if isinstance(journal.get("writeback"), Mapping)
                else None
            ),
            quota_spend_payload=(
                journal.get("quota_spend")
                if isinstance(journal.get("quota_spend"), Mapping)
                else None
            ),
            writeback=lambda: _settlement_callback(
                writeback,
                context=context,
                effect_receipt_digest=effect_receipt_digest,
                effect_id=str(identity["effect_id"]),
                require_receipt_digest=True,
            ),
            spend=lambda: _settlement_callback(
                spend,
                context=context,
                effect_receipt_digest=effect_receipt_digest,
                effect_id=str(identity["effect_id"]),
                require_receipt_digest=False,
            ),
            checkpoint=checkpoint,
            committed_effect_id=str(identity["effect_id"]),
        )
        journal["settlement_result"] = settlement_result_payload(settlement)
        settlement_status = effect_runtime_result(
            "governed_capability.settlement_status",
            {
                "failure": (
                    settlement.failure.as_dict()
                    if settlement.failure is not None
                    else None
                )
            },
        )
        if settlement_status == "settlement_failed":
            journal["status"] = settlement_status
            _write_journal(path, journal)
            return {**_public_receipt(journal, dry_run=False), "ok": False}
        if settlement_status != "committed":
            raise RuntimeError("TypeScript governed capability status shape mismatch")
        journal["status"] = settlement_status
        _write_journal(path, journal)
        return _public_receipt(journal, dry_run=False)
