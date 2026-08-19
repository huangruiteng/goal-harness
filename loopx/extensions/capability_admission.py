from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..authority import validate_public_safe_text
from ..control_plane.quota.turn_envelope import turn_envelope_action_signature_document
from ..control_plane.turn_driver import build_loopx_turn_transaction_plan
from ..control_plane.turn_driver.driver import selected_turn_todo
from .manifest import EXTERNAL_CAPABILITY_PROFILE_SCHEMA_VERSION
from .runtime import (
    execute_extension_runtime_binding,
    extension_catalog_entries,
    resolve_extension_runtime_binding,
)

EXTERNAL_CAPABILITY_REQUEST_SCHEMA_VERSION = (
    "loopx_external_domain_capability_request_v0"
)
EXTERNAL_CAPABILITY_RESULT_SCHEMA_VERSION = (
    "loopx_external_domain_capability_result_v0"
)
EXTERNAL_CAPABILITY_INVOCATION_SCHEMA_VERSION = (
    "loopx_external_domain_capability_invocation_v0"
)
_TURN_PLAN_SCHEMA_VERSION = "loopx_turn_plan_v0"
_TURN_KEY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "credential",
        "credentials",
        "cookie",
        "password",
        "private_key",
        "raw_document",
        "raw_log",
        "raw_message",
        "request_body",
        "response_body",
        "secret",
        "token",
    }
)
_RESULT_FIELDS = {
    "schema_version",
    "invocation_id",
    "status",
    "observations",
    "domain_state_mutations",
    "domain_transition_receipts",
    "transition_proposals",
    "effect_receipt",
    "follow_up",
}


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): deepcopy(item) for key, item in value.items()}


def _token(value: object, label: str) -> str:
    token = str(value or "").strip()
    if not token:
        raise ValueError(f"{label} is required")
    return token


def _canonical_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("external capability payload must be JSON serializable") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _operation_from_profile(
    profile: Mapping[str, Any], operation_id: str
) -> dict[str, Any]:
    if profile.get("schema_version") != EXTERNAL_CAPABILITY_PROFILE_SCHEMA_VERSION:
        raise ValueError("external capability integration profile is invalid")
    operations = profile.get("operations")
    if not isinstance(operations, list):
        raise ValueError("external capability integration profile operations are invalid")
    matching = [
        dict(item)
        for item in operations
        if isinstance(item, Mapping) and item.get("id") == operation_id
    ]
    if len(matching) != 1:
        raise ValueError(
            f"external capability profile does not declare operation `{operation_id}`"
        )
    return matching[0]


def resolve_external_capability_binding(
    *,
    state_file: str | Path,
    capability_id: str,
    operation: str,
) -> dict[str, Any]:
    """Resolve one ready extension-owned capability and its snapshotted profile."""

    matches: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    for entry in extension_catalog_entries(state_file=state_file):
        provider = entry.get("provider")
        if not isinstance(provider, Mapping) or provider.get("ready") is not True:
            continue
        capabilities = entry.get("capabilities")
        if not isinstance(capabilities, list):
            continue
        for capability in capabilities:
            if not isinstance(capability, Mapping):
                continue
            if capability.get("id") != capability_id:
                continue
            profile = capability.get("integration_profile")
            if not isinstance(profile, Mapping):
                continue
            matches.append((str(provider.get("id") or ""), capability, profile))
    if not matches:
        raise ValueError(
            f"no enabled, doctor-ready external provider exposes `{capability_id}`"
        )
    if len(matches) != 1:
        providers = [extension_id for extension_id, _, _ in matches]
        raise ValueError(
            f"multiple enabled, doctor-ready external providers expose "
            f"`{capability_id}`: {providers}"
        )
    extension_id, capability, profile = matches[0]
    operation_profile = _operation_from_profile(profile, operation)
    permission = _token(
        operation_profile.get("required_permission"),
        "external capability required_permission",
    )
    protocol = _token(profile.get("protocol"), "external capability protocol")
    runtime_binding = resolve_extension_runtime_binding(
        extension_id,
        state_file=state_file,
        protocol=protocol,
        permission=permission,
    )
    return {
        **runtime_binding,
        "capability_id": capability_id,
        "operation": deepcopy(operation_profile),
        "integration_profile_digest": _token(
            capability.get("integration_profile_digest"),
            "external capability integration_profile_digest",
        ),
    }


def _turn_binding(turn_plan: Mapping[str, Any]) -> dict[str, Any]:
    if turn_plan.get("schema_version") != _TURN_PLAN_SCHEMA_VERSION:
        raise ValueError(f"turn plan must use {_TURN_PLAN_SCHEMA_VERSION}")
    if turn_plan.get("ok") is not True:
        raise ValueError("turn plan is not executable")
    route = _mapping(turn_plan.get("route"), "turn plan route")
    if route.get("would_invoke_host") is not True:
        raise ValueError("turn plan route is not host executable")
    transaction = _mapping(turn_plan.get("transaction"), "turn plan transaction")
    if transaction.get("status") != "planned":
        raise ValueError("turn plan transaction is not planned")
    turn_key = _token(transaction.get("turn_key"), "turn plan turn_key")
    if not _TURN_KEY_RE.fullmatch(turn_key):
        raise ValueError("turn plan turn_key is invalid")
    turn_instance_id = _token(
        transaction.get("turn_instance_id"), "turn plan turn_instance_id"
    )
    settlement = _mapping(
        transaction.get("settlement_plan"), "turn plan settlement_plan"
    )
    identity = _mapping(settlement.get("identity"), "turn plan settlement identity")
    envelope = _mapping(turn_plan.get("turn_envelope"), "turn plan envelope")
    signature = _mapping(envelope.get("action_signature"), "turn action signature")
    action_signature = _token(
        signature.get("source_hash"), "turn action signature source_hash"
    )
    expected_signature = _canonical_digest(
        turn_envelope_action_signature_document(envelope)
    )
    if (
        signature.get("matches") is not True
        or signature.get("envelope_hash") != action_signature
        or action_signature != expected_signature
    ):
        raise ValueError("turn action signature is stale")
    todo = selected_turn_todo(envelope)
    required_todo_fields = (
        "todo_id",
        "action_kind",
        "target_key",
        "capability_binding_ref",
    )
    for field in required_todo_fields:
        _token(todo.get(field), f"selected Todo {field}")
    goal_id = _token(envelope.get("goal_id"), "turn goal_id")
    agent_id = _token(envelope.get("agent_id"), "turn agent_id")
    expected_identity = {
        "goal_id": goal_id,
        "agent_id": agent_id,
        "todo_id": str(todo["todo_id"]),
        "turn_instance_id": turn_instance_id,
    }
    actual_identity = {
        key: str(identity.get(key) or "") for key in expected_identity
    }
    if actual_identity != expected_identity:
        raise ValueError("turn settlement identity does not match the selected Todo")
    host = _mapping(turn_plan.get("host"), "turn plan host")
    session = _mapping(turn_plan.get("session"), "turn plan session")
    signature_document = turn_envelope_action_signature_document(envelope)
    signed_action = _mapping(signature_document.get("action"), "turn signed action")
    signature_document["action"] = {
        **signed_action,
        "selected_todo": dict(todo),
    }
    lineage = {
        "goal_id": goal_id,
        "agent_id": agent_id,
        "todo_id": str(todo["todo_id"]),
        "action_hash": _canonical_digest(signature_document),
    }
    expected_transaction = build_loopx_turn_transaction_plan(
        planned=True,
        lineage=lineage,
        host=_token(host.get("kind"), "turn plan host kind"),
        execution_mode=_token(
            host.get("execution_mode"), "turn plan host execution_mode"
        ),
        scheduler_owner=_token(
            host.get("scheduler_owner"), "turn plan host scheduler_owner"
        ),
        session_action=_token(session.get("action"), "turn plan session action"),
        turn_instance_id=turn_instance_id,
    )
    if expected_transaction.get("turn_key") != turn_key:
        raise ValueError("turn plan turn_key does not match its signed lineage")
    return {
        "turn_key": turn_key,
        "turn_instance_id": turn_instance_id,
        "action_signature": action_signature,
        "goal_id": goal_id,
        "agent_id": agent_id,
        "todo": todo,
    }


def _validate_todo_contract(
    operation: Mapping[str, Any], todo: Mapping[str, Any]
) -> None:
    contract = operation.get("todo_contract")
    if not isinstance(contract, Mapping):
        return
    action_kind = str(todo.get("action_kind") or "")
    action_kinds = contract.get("action_kinds")
    if not isinstance(action_kinds, list) or action_kind not in action_kinds:
        raise ValueError("selected Todo action_kind is outside the capability profile")
    target_key = str(todo.get("target_key") or "")
    prefixes = contract.get("target_key_prefixes")
    if not isinstance(prefixes, list) or not any(
        target_key.startswith(str(prefix)) for prefix in prefixes
    ):
        raise ValueError("selected Todo target_key is outside the capability profile")
    binding_ref = str(todo.get("capability_binding_ref") or "")
    binding_refs = contract.get("capability_binding_refs")
    if not isinstance(binding_refs, list) or binding_ref not in binding_refs:
        raise ValueError(
            "selected Todo capability_binding_ref is outside the capability profile"
        )


def _provider_input(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "provider input")
    if set(payload) != {"context_refs", "input"}:
        raise ValueError("provider input must contain only context_refs and input")
    context_refs = payload.get("context_refs")
    if not isinstance(context_refs, list) or not 1 <= len(context_refs) <= 32:
        raise ValueError("provider input context_refs must contain 1 to 32 objects")
    for index, item in enumerate(context_refs):
        ref = _mapping(item, f"provider input context_refs[{index}]")
        for field in ("kind", "ref", "digest"):
            _token(ref.get(field), f"provider input context_refs[{index}].{field}")
    _mapping(payload.get("input"), "provider input input")
    return payload


def _assert_public_safe_result(value: object, *, path: str = "provider_result") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).casefold()
            if normalized_key in _FORBIDDEN_RESULT_KEYS or normalized_key.startswith(
                "raw_"
            ):
                raise ValueError(f"{path} contains forbidden field `{key}`")
            _assert_public_safe_result(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_public_safe_result(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        validate_public_safe_text(path, value)


def validate_external_capability_result(
    value: Mapping[str, Any],
    *,
    invocation_id: str,
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    result = _mapping(value, "external capability result")
    unknown = sorted(set(result) - _RESULT_FIELDS)
    if unknown:
        raise ValueError(f"external capability result has unsupported fields {unknown}")
    expected_schema = str(operation.get("result_schema") or "")
    if result.get("schema_version") != expected_schema:
        raise ValueError("external capability result schema_version does not match profile")
    if result.get("invocation_id") != invocation_id:
        raise ValueError("external capability result invocation_id does not match request")
    if result.get("status") not in {"succeeded", "no_change"}:
        raise ValueError("external capability read-only result did not succeed")
    observations = result.get("observations")
    if not isinstance(observations, list) or len(observations) > 64:
        raise ValueError("external capability result observations are invalid")
    if operation.get("effect_class") != "read_only":
        raise ValueError("external-write capability admission is not implemented")
    for field in (
        "domain_state_mutations",
        "domain_transition_receipts",
        "transition_proposals",
    ):
        if result.get(field) != []:
            raise ValueError(f"read-only external capability result must leave {field} empty")
    if result.get("effect_receipt") is not None:
        raise ValueError("read-only external capability result cannot contain an effect receipt")
    _assert_public_safe_result(result)
    return result


def invoke_external_capability(
    *,
    state_file: str | Path,
    capability_id: str,
    operation: str,
    turn_plan: Mapping[str, Any],
    provider_input: Mapping[str, Any],
    execute: bool = False,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Preview or run one read-only provider as a child of an admitted Turn."""

    binding = resolve_external_capability_binding(
        state_file=state_file,
        capability_id=capability_id,
        operation=operation,
    )
    operation_profile = _mapping(binding.get("operation"), "operation profile")
    if operation_profile.get("effect_class") != "read_only":
        raise ValueError("external-write capability admission is not implemented")
    turn = _turn_binding(turn_plan)
    todo = _mapping(turn.get("todo"), "selected Todo")
    _validate_todo_contract(operation_profile, todo)
    provided = _provider_input(provider_input)
    invocation_seed = {
        "turn_key": turn["turn_key"],
        "capability_id": capability_id,
        "operation": operation,
        "provider_input_digest": _canonical_digest(provided),
    }
    invocation_id = "capability-" + _canonical_digest(invocation_seed).split(":", 1)[1][
        :24
    ]
    request = {
        "schema_version": str(operation_profile.get("request_schema") or ""),
        "invocation_id": invocation_id,
        "turn": {
            "turn_key": turn["turn_key"],
            "turn_instance_id": turn["turn_instance_id"],
            "action_signature": turn["action_signature"],
        },
        "capability_id": capability_id,
        "operation": operation,
        "goal": {"goal_id": turn["goal_id"]},
        "todo": {
            "todo_id": todo["todo_id"],
            "action_kind": todo["action_kind"],
            "target_key": todo["target_key"],
            "capability_binding_ref": todo["capability_binding_ref"],
        },
        "provider": {
            "extension_id": binding["extension_id"],
            "revision": binding["revision"],
            "profile_digest": binding["integration_profile_digest"],
        },
        "context_refs": provided["context_refs"],
        "input": provided["input"],
    }
    receipt: dict[str, Any] = {
        "ok": True,
        "schema_version": EXTERNAL_CAPABILITY_INVOCATION_SCHEMA_VERSION,
        "status": "ready" if not execute else "running",
        "dry_run": not execute,
        "executed": False,
        "capability_id": capability_id,
        "operation": operation,
        "effect_class": operation_profile["effect_class"],
        "provider": {
            "extension_id": binding["extension_id"],
            "revision": binding["revision"],
            "profile_digest": binding["integration_profile_digest"],
        },
        "turn": {
            "goal_id": turn["goal_id"],
            "agent_id": turn["agent_id"],
            "todo_id": todo["todo_id"],
            "turn_key": turn["turn_key"],
            "turn_instance_id": turn["turn_instance_id"],
        },
        "invocation_id": invocation_id,
        "request_digest": _canonical_digest(request),
        "context_ref_count": len(provided["context_refs"]),
        "effects": {
            "provider_invoked": False,
            "external_write_performed": False,
            "loopx_state_written": False,
            "quota_spent": False,
        },
    }
    if not execute:
        return receipt
    provider_result = execute_extension_runtime_binding(
        binding,
        request=request,
        environment=environment,
    )
    result = validate_external_capability_result(
        provider_result,
        invocation_id=invocation_id,
        operation=operation_profile,
    )
    return {
        **receipt,
        "status": str(result["status"]),
        "executed": True,
        "provider_result_digest": _canonical_digest(result),
        "provider_result": result,
        "effects": {
            **receipt["effects"],
            "provider_invoked": True,
        },
    }
