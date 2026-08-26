"""Python provider bridge for the TypeScript-owned task-lease transaction.

TypeScript owns request normalization, settlement identity and plan projection,
provider failure classification, ordered receipts, and the canonical result.
Python retains the atomic task-lease provider and the legacy CLI projection
until task-lease persistence and the CLI move to the native TS runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loopx.control_plane.effect_program import SettlementResult
from loopx.control_plane.effect_runtime import effect_runtime_result
from loopx.control_plane.settlement_driver import decode_settlement_result
from loopx.control_plane.work_items.task_lease import (
    TaskLeaseError,
    acquire_task_lease,
    task_lease_path,
)

__all__ = ["execute_task_lease_settlement"]


TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION = (
    "loopx_task_lease_acquire_transaction_v0"
)
TASK_LEASE_ACQUIRE_REDUCTION_SCHEMA_VERSION = "loopx_task_lease_acquire_reduction_v0"


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"TypeScript task-lease {label} shape mismatch")
    return value


def _reduce_task_lease_acquire(params: Mapping[str, Any]) -> dict[str, Any]:
    result = effect_runtime_result("task_lease.acquire.reduce", params)
    reduction = _require_mapping(result, "reduction")
    if reduction.get(
        "schema_version"
    ) != TASK_LEASE_ACQUIRE_REDUCTION_SCHEMA_VERSION or reduction.get(
        "decision"
    ) not in {"execute", "complete", "failed"}:
        raise RuntimeError("TypeScript task-lease reduction shape mismatch")
    return dict(reduction)


def _decode_task_lease_result(
    reduction: Mapping[str, Any],
) -> SettlementResult[dict[str, Any]]:
    result = reduction.get("result")
    projection = reduction.get("settlement_result")
    if not isinstance(result, Mapping) or not isinstance(projection, Mapping):
        raise RuntimeError("TypeScript task-lease result shape mismatch")

    def decode_lease(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise RuntimeError("TypeScript task-lease value shape mismatch")
        return dict(value)

    return decode_settlement_result(
        result,
        value_decoder=decode_lease,
        projection_payload=projection,
    )


def _optional_provider_integer(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"TypeScript task-lease {label} shape mismatch")
    return value


def _decode_provider_effect(
    provider_effect: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any], list[str], int | None, int | None]:
    if (
        provider_effect.get("step_kind") != "durable_writeback"
        or provider_effect.get("action") != "acquire"
        or not isinstance(provider_effect.get("effect_id"), str)
    ):
        raise RuntimeError("TypeScript task-lease provider effect shape mismatch")
    parameters = _require_mapping(
        provider_effect.get("parameters"),
        "provider parameters",
    )
    write_scopes = parameters.get("write_scopes")
    if not isinstance(write_scopes, list) or any(
        not isinstance(scope, str) for scope in write_scopes
    ):
        raise RuntimeError("TypeScript task-lease write scopes shape mismatch")
    return (
        str(provider_effect["effect_id"]),
        parameters,
        list(write_scopes),
        _optional_provider_integer(parameters.get("ttl_seconds"), "ttl"),
        _optional_provider_integer(
            parameters.get("expected_version"),
            "expected version",
        ),
    )


def _provider_result(
    provider_effect: Mapping[str, Any],
    *,
    registry_path: Path,
    runtime_root: Path,
    acquire: bool,
) -> dict[str, Any]:
    (
        effect_id,
        parameters,
        write_scopes,
        ttl_seconds,
        expected_version,
    ) = _decode_provider_effect(provider_effect)
    lease_path = task_lease_path(
        runtime_root=runtime_root,
        goal_id=str(parameters.get("goal_id") or ""),
        todo_id=str(parameters.get("todo_id") or ""),
    )
    if not acquire:
        return {
            "effect_id": effect_id,
            "ok": False,
            "error": "task lease acquire rejected by settlement oracle",
            "error_code": "settlement_oracle_rejected",
            "lease_path": str(lease_path),
        }
    try:
        result = acquire_task_lease(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=str(parameters.get("goal_id") or ""),
            todo_id=str(parameters.get("todo_id") or ""),
            owner=str(parameters.get("owner") or ""),
            idempotency_key=str(parameters.get("idempotency_key") or ""),
            ttl_seconds=ttl_seconds,
            write_scopes=list(write_scopes),
            expected_version=expected_version,
        )
    except TaskLeaseError as exc:
        return {
            "effect_id": effect_id,
            "ok": False,
            "error": str(exc),
            "error_code": exc.code,
            "task_lease_payload": dict(exc.payload),
            "lease_path": str(lease_path),
        }
    lease = result.get("lease")
    return {
        "effect_id": effect_id,
        "ok": True,
        "acquired": result.get("acquired") is True,
        "idempotent": result.get("idempotent") is True,
        "lease": dict(lease) if isinstance(lease, Mapping) else None,
        "lease_path": str(result.get("lease_path") or ""),
    }


def execute_task_lease_settlement(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    owner: str,
    todo_id: str,
    idempotency_key: str,
    write_scopes: list[str] | None = None,
    ttl_seconds: int | None = None,
    expected_version: int | None = None,
    acquire: bool = True,
) -> SettlementResult[dict[str, Any]]:
    """Run one coarse preflight/provider/final task-lease transaction."""

    preflight = _reduce_task_lease_acquire(
        {
            "schema_version": TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION,
            "phase": "preflight",
            "goal_id": goal_id,
            "owner": owner,
            "todo_id": todo_id,
            "idempotency_key": idempotency_key,
            "write_scopes": list(write_scopes or []),
            "ttl_seconds": ttl_seconds,
            "expected_version": expected_version,
        }
    )
    if preflight["decision"] != "execute":
        return _decode_task_lease_result(preflight)
    transaction = _require_mapping(preflight.get("transaction"), "transaction")
    provider_effect = _require_mapping(
        preflight.get("provider_effect"),
        "provider effect",
    )
    provider_result = _provider_result(
        provider_effect,
        registry_path=registry_path,
        runtime_root=runtime_root,
        acquire=acquire,
    )
    final = _reduce_task_lease_acquire(
        {
            "schema_version": TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION,
            "phase": "finalize",
            "transaction": dict(transaction),
            "provider_result": provider_result,
        }
    )
    if final["decision"] == "execute":
        raise RuntimeError(
            "TypeScript task-lease final reduction requested another effect"
        )
    return _decode_task_lease_result(final)
