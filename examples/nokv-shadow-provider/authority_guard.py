#!/usr/bin/env python3
"""TEST ONLY file-provider Turn authority guard.

This process adapter composes the production ``CoordinationAuthorityExecutor``
with ``FileCoordinationProvider``.  It is qualification wiring, not a shared
production-mode declaration: every invocation reads one Turn checkpoint on
stdin and emits one typed result on stdout.  Claim/reclaim and renew therefore
use the same authority core, aggregate, receipts, CAS, and store-lineage fence
as the NoKV provider contract; no parallel lock-based oracle exists here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from loopx.control_plane.coordination.executor import (
    CoordinationAuthorityExecutor,
    sample_claim_envelope,
    sample_work_envelope,
)
from loopx.control_plane.coordination.file_provider import (
    FileCoordinationProvider,
)
from loopx.control_plane.coordination.head import validated_head


def _clock(path: Path) -> float:
    return float(path.read_text(encoding="utf-8").strip())


def _preconditions(todo: Mapping[str, Any]) -> dict[str, Any]:
    eligibility = todo["eligibility"]
    return {
        field: eligibility[field]
        for field in (
            "authorization_projection_revision",
            "authorization_projection_digest",
            "dependency_revision",
            "gate_revision",
        )
    }


def _operation_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"turn-{prefix}-{digest}"


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    payload = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _rejection(reason_code: str, reason: str) -> dict[str, Any]:
    return {"ok": False, "reason_code": reason_code, "reason": reason}


def _stored_receipt(
    head: Mapping[str, Any], operation_id: str
) -> dict[str, Any] | None:
    index = head.get("receipt_index")
    entry = index.get(operation_id) if isinstance(index, Mapping) else None
    receipt = entry.get("original_receipt") if isinstance(entry, Mapping) else None
    return dict(receipt) if isinstance(receipt, Mapping) else None


def _binding_matches_admission_receipt(
    binding: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    agent_id: str,
    todo_id: str,
) -> bool:
    actor = receipt.get("actor")
    expected = {
        "operation_id": receipt.get("operation_id"),
        "receipt_digest": _receipt_digest(receipt),
        "authority_revision": receipt.get("accepted_authority_revision"),
        "todo_revision": receipt.get("accepted_todo_revision"),
        "lease_id": receipt.get("lease_id"),
        "lease_epoch": receipt.get("lease_epoch"),
        "expires_at": receipt.get("expires_at"),
    }
    return bool(
        all(binding.get(field) == value for field, value in expected.items())
        and receipt.get("todo_id") == todo_id
        and isinstance(actor, Mapping)
        and actor.get("agent_id") == agent_id
        and receipt.get("command") in {"claim_work", "reclaim_work"}
    )


def _completion_operation_id(
    request: Mapping[str, Any], binding: Mapping[str, Any]
) -> str:
    return _operation_id(
        "complete",
        str(binding.get("operation_id") or ""),
        str(request.get("turn_key") or ""),
        str(request.get("effect_id") or ""),
    )


def _completion_command(
    request: Mapping[str, Any], *, todo_id: str
) -> dict[str, Any] | None:
    completion = request.get("completion")
    if not isinstance(completion, Mapping):
        return None
    continuation = completion.get("continuation")
    expected_fields = {"todo_id", "continuation"}
    if continuation == "successor":
        expected_fields.add("successor_todo_ids")
    if set(completion) != expected_fields or completion.get("todo_id") != todo_id:
        return None
    successors = completion.get("successor_todo_ids", [])
    if (
        continuation not in {"active_goal", "no_followup", "successor"}
        or not isinstance(successors, list)
        or not all(isinstance(item, str) and item for item in successors)
        or len(set(successors)) != len(successors)
        or (continuation == "successor") != bool(successors)
    ):
        return None
    return {
        "no_followup": continuation == "no_followup",
        "successor_todo_ids": list(successors),
        "completion_continuation": continuation,
    }


def _completion_receipt_matches(
    head: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    *,
    operation_id: str,
    binding: Mapping[str, Any],
    agent_id: str,
    todo_id: str,
    continuation: str,
) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    actor = receipt.get("actor")
    todo = head["coordination"]["todos"].get(todo_id)
    lease = head["coordination"]["leases"].get(todo_id)
    return bool(
        receipt.get("operation_id") == operation_id
        and receipt.get("command") == "complete_work"
        and receipt.get("todo_id") == todo_id
        and receipt.get("lease_id") == binding.get("lease_id")
        and receipt.get("lease_epoch") == binding.get("lease_epoch")
        and receipt.get("completion_continuation") == continuation
        and isinstance(actor, Mapping)
        and actor.get("agent_id") == agent_id
        and isinstance(todo, Mapping)
        and todo.get("status") == "done"
        and todo.get("completion_continuation") == continuation
        and lease is None
    )


def _complete_authority(
    request: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    executor: CoordinationAuthorityExecutor,
    provider: FileCoordinationProvider,
    clock_path: Path,
    goal_id: str,
    agent_id: str,
    todo_id: str,
) -> dict[str, Any]:
    command = _completion_command(request, todo_id=todo_id)
    if command is None:
        return _rejection(
            "authority_completion_invalid",
            "authority completion context is invalid",
        )
    head_value, _generation = provider.load()
    if head_value is None:
        return _rejection(
            "authority_head_missing", "coordination authority head is missing"
        )
    head = validated_head(head_value, goal_id=goal_id)
    if binding.get("store_identity") != provider.store_identity():
        return _rejection("store_lineage_mismatch", "authority store lineage changed")
    admission_receipt = _stored_receipt(head, str(binding.get("operation_id") or ""))
    if admission_receipt is None or not _binding_matches_admission_receipt(
        binding,
        admission_receipt,
        agent_id=agent_id,
        todo_id=todo_id,
    ):
        return _rejection(
            "authority_receipt_mismatch",
            "authority admission receipt no longer matches",
        )
    operation_id = _completion_operation_id(request, binding)
    prior = _stored_receipt(head, operation_id)
    if prior is None:
        todo = head["coordination"]["todos"].get(todo_id)
        lease = head["coordination"]["leases"].get(todo_id)
        if not isinstance(todo, Mapping) or not isinstance(lease, Mapping):
            return _rejection(
                "stale_lease_fence", "authority lease is no longer current"
            )
        if (
            lease.get("owner") != agent_id
            or lease.get("lease_id") != binding.get("lease_id")
            or lease.get("lease_epoch") != binding.get("lease_epoch")
        ):
            return _rejection(
                "stale_lease_fence", "authority lease generation changed"
            )
        expiry = datetime.fromisoformat(str(lease["expires_at"]))
        if _clock(clock_path) >= expiry.timestamp():
            return _rejection(
                "lease_expired", "authority lease expired before completion"
            )
        expected_revision = int(todo["todo_revision"])
    else:
        expected_revision = int(prior["accepted_todo_revision"]) - 1
    outcome = executor.apply(
        sample_work_envelope(
            goal_id=goal_id,
            operation_id=operation_id,
            agent_id=agent_id,
            device_id=f"turn-canary-{agent_id}",
            command={
                "type": "complete_work",
                "todo_id": todo_id,
                "expected_todo_revision": expected_revision,
                "lease_id": str(binding["lease_id"]),
                "expected_lease_epoch": int(binding["lease_epoch"]),
                "no_followup": command["no_followup"],
                "successor_todo_ids": command["successor_todo_ids"],
                "evidence": None,
            },
        )
    )
    if outcome.get("result") not in {"applied", "already_applied"}:
        return _rejection(
            "authority_completion_rejected",
            "coordination authority refused completion",
        )
    completed_value, _completed_generation = provider.load()
    if completed_value is None:
        return _rejection(
            "authority_head_missing", "coordination authority head is missing"
        )
    completed = validated_head(completed_value, goal_id=goal_id)
    receipt = _stored_receipt(completed, operation_id)
    if not _completion_receipt_matches(
        completed,
        receipt,
        operation_id=operation_id,
        binding=binding,
        agent_id=agent_id,
        todo_id=todo_id,
        continuation=command["completion_continuation"],
    ):
        return _rejection(
            "authority_completion_mismatch",
            "authority completion receipt does not match",
        )
    return {"ok": True, "binding": dict(binding)}


def _admit(
    request: Mapping[str, Any],
    *,
    executor: CoordinationAuthorityExecutor,
    provider: FileCoordinationProvider,
    goal_id: str,
    agent_id: str,
    todo_id: str,
    lease_ttl_seconds: int,
) -> dict[str, Any]:
    head_value, _generation = provider.load()
    if head_value is None:
        return _rejection(
            "authority_head_missing", "coordination authority head is not initialized"
        )
    head = validated_head(head_value, goal_id=goal_id)
    todo = head["coordination"]["todos"].get(todo_id)
    if not isinstance(todo, Mapping):
        return _rejection("authority_todo_missing", "coordination Todo is missing")
    operation_id = _operation_id(
        "admit", str(request.get("turn_key") or ""), agent_id, todo_id
    )
    prior = _stored_receipt(head, operation_id)
    if prior is not None:
        command_kind = str(prior.get("command") or "")
        expected_revision = int(prior["accepted_todo_revision"]) - 1
    else:
        command_kind = (
            "claim_work" if todo.get("claimed_by") is None else "reclaim_work"
        )
        expected_revision = int(todo["todo_revision"])
    if command_kind == "claim_work":
        envelope = sample_claim_envelope(
            goal_id=goal_id,
            operation_id=operation_id,
            agent_id=agent_id,
            device_id=f"turn-canary-{agent_id}",
            todo_id=todo_id,
            expected_todo_revision=expected_revision,
            expected_preconditions=_preconditions(todo),
            lease_ttl_seconds=lease_ttl_seconds,
        )
    elif command_kind == "reclaim_work":
        envelope = sample_work_envelope(
            goal_id=goal_id,
            operation_id=operation_id,
            agent_id=agent_id,
            device_id=f"turn-canary-{agent_id}",
            command={
                "type": "reclaim_work",
                "todo_id": todo_id,
                "expected_todo_revision": expected_revision,
                "expected_preconditions": _preconditions(todo),
                "lease_ttl_seconds": lease_ttl_seconds,
            },
        )
    else:
        return _rejection(
            "authority_receipt_invalid", "authority admission receipt is invalid"
        )
    outcome = executor.apply(envelope)
    if outcome.get("result") not in {"applied", "already_applied"}:
        return _rejection(
            "authority_admission_rejected", "coordination authority refused admission"
        )
    if outcome.get("authorization_status") != "active":
        return _rejection(
            "authority_admission_inactive", "coordination authority is not active"
        )
    receipt = outcome.get("original_receipt")
    if not isinstance(receipt, Mapping):
        return _rejection(
            "authority_receipt_invalid", "authority admission receipt is invalid"
        )
    return {
        "ok": True,
        "binding": {
            "schema_version": "loopx_turn_authority_binding_v0",
            "store_identity": provider.store_identity(),
            "operation_id": str(receipt["operation_id"]),
            "receipt_digest": _receipt_digest(receipt),
            "authority_revision": int(receipt["accepted_authority_revision"]),
            "todo_revision": int(receipt["accepted_todo_revision"]),
            "lease_id": str(receipt["lease_id"]),
            "lease_epoch": int(receipt["lease_epoch"]),
            "expires_at": str(receipt["expires_at"]),
        },
    }


def _revalidate_and_renew(
    request: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    executor: CoordinationAuthorityExecutor,
    provider: FileCoordinationProvider,
    clock_path: Path,
    goal_id: str,
    agent_id: str,
    todo_id: str,
    lease_ttl_seconds: int,
) -> dict[str, Any]:
    head_value, _generation = provider.load()
    if head_value is None:
        return _rejection(
            "authority_head_missing", "coordination authority head is missing"
        )
    head = validated_head(head_value, goal_id=goal_id)
    if binding.get("store_identity") != provider.store_identity():
        return _rejection("store_lineage_mismatch", "authority store lineage changed")
    admission_receipt = _stored_receipt(head, str(binding.get("operation_id") or ""))
    if admission_receipt is None or not _binding_matches_admission_receipt(
        binding,
        admission_receipt,
        agent_id=agent_id,
        todo_id=todo_id,
    ):
        return _rejection(
            "authority_receipt_mismatch",
            "authority admission receipt no longer matches",
        )
    completion_operation_id = _completion_operation_id(request, binding)
    completion_receipt = _stored_receipt(head, completion_operation_id)
    if _completion_receipt_matches(
        head,
        completion_receipt,
        operation_id=completion_operation_id,
        binding=binding,
        agent_id=agent_id,
        todo_id=todo_id,
        continuation=str(
            completion_receipt.get("completion_continuation")
            if isinstance(completion_receipt, Mapping)
            else ""
        ),
    ):
        if request.get("checkpoint") in {"quota_spend", "scheduler"}:
            return {"ok": True, "binding": dict(binding)}
        return _rejection(
            "stale_lease_fence", "authority work is already complete"
        )
    todo = head["coordination"]["todos"].get(todo_id)
    lease = head["coordination"]["leases"].get(todo_id)
    if not isinstance(todo, Mapping) or not isinstance(lease, Mapping):
        return _rejection("stale_lease_fence", "authority lease is no longer current")
    if (
        lease.get("owner") != agent_id
        or lease.get("lease_id") != binding.get("lease_id")
        or lease.get("lease_epoch") != binding.get("lease_epoch")
    ):
        return _rejection("stale_lease_fence", "authority lease generation changed")
    expiry = datetime.fromisoformat(str(lease["expires_at"]))
    if _clock(clock_path) >= expiry.timestamp():
        return _rejection("lease_expired", "authority lease expired before checkpoint")
    checkpoint = str(request.get("checkpoint") or "")
    effect_ref = str(request.get("effect_ref") or "")
    operation_id = _operation_id(
        "renew", str(binding["operation_id"]), checkpoint, effect_ref
    )
    prior = _stored_receipt(head, operation_id)
    expected_revision = (
        int(prior["accepted_todo_revision"]) - 1
        if prior is not None
        else int(todo["todo_revision"])
    )
    outcome = executor.apply(
        sample_work_envelope(
            goal_id=goal_id,
            operation_id=operation_id,
            agent_id=agent_id,
            device_id=f"turn-canary-{agent_id}",
            command={
                "type": "renew_work",
                "todo_id": todo_id,
                "expected_todo_revision": expected_revision,
                "lease_id": str(binding["lease_id"]),
                "expected_lease_epoch": int(binding["lease_epoch"]),
                "lease_ttl_seconds": lease_ttl_seconds,
            },
        )
    )
    if outcome.get("result") not in {"applied", "already_applied"}:
        return _rejection("stale_lease_fence", "authority renewal was refused")
    if outcome.get("authorization_status") != "active":
        return _rejection("lease_expired", "authority lease is not active")
    return {"ok": True, "binding": dict(binding)}


def evaluate(args: argparse.Namespace, request: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "goal_id": args.goal_id,
        "agent_id": args.agent_id,
        "todo_id": args.todo_id,
    }
    if any(request.get(field) != value for field, value in expected.items()):
        return _rejection(
            "authority_identity_mismatch",
            "checkpoint identity does not match guard scope",
        )
    provider = FileCoordinationProvider(args.store_directory, args.goal_id)
    clock_path = Path(args.clock_file)
    executor = CoordinationAuthorityExecutor(
        provider,
        goal_id=args.goal_id,
        now=lambda: _clock(clock_path),
        reclaim_grace_seconds=args.reclaim_grace_seconds,
    )
    binding = request.get("authority_binding")
    if binding is None:
        if request.get("checkpoint") != "host_admission":
            return _rejection(
                "authority_admission_missing", "checkpoint has no admission binding"
            )
        return _admit(
            request,
            executor=executor,
            provider=provider,
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            todo_id=args.todo_id,
            lease_ttl_seconds=args.lease_ttl_seconds,
        )
    if not isinstance(binding, Mapping):
        return _rejection("authority_binding_invalid", "authority binding is invalid")
    if request.get("checkpoint") == "authority_complete":
        return _complete_authority(
            request,
            binding,
            executor=executor,
            provider=provider,
            clock_path=clock_path,
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            todo_id=args.todo_id,
        )
    return _revalidate_and_renew(
        request,
        binding,
        executor=executor,
        provider=provider,
        clock_path=clock_path,
        goal_id=args.goal_id,
        agent_id=args.agent_id,
        todo_id=args.todo_id,
        lease_ttl_seconds=args.lease_ttl_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-directory", required=True)
    parser.add_argument("--clock-file", required=True)
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--todo-id", required=True)
    parser.add_argument("--lease-ttl-seconds", type=int, default=2)
    parser.add_argument("--reclaim-grace-seconds", type=float, default=30.0)
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, Mapping):
            raise TypeError("checkpoint request must be an object")
        result = evaluate(args, request)
    except Exception:  # noqa: BLE001 - TEST ONLY process boundary fails closed
        result = _rejection(
            "authority_guard_unavailable",
            "authority guard could not verify current state",
        )
    json.dump(result, sys.stdout, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
