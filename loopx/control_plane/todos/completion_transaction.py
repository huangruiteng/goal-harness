"""Thin Python adapter for the TypeScript-owned Todo completion transaction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result


TODO_COMPLETION_TRANSACTION_REQUEST_SCHEMA = "loopx_todo_completion_transaction_v0"
TODO_COMPLETION_TRANSACTION_RESULT_SCHEMA = (
    "loopx_todo_completion_transaction_result_v0"
)

_DECISIONS = {"execute_validation", "commit", "replay", "reject"}
_IDENTITY_SOURCES = {
    "turn_settlement",
    "unscoped_completion",
    "lifecycle_reentry",
}
_CONTINUATIONS = {"active_goal", "successor", "no_followup"}
_RECOVERIES = {
    "same_turn_terminal_closeout",
    "lifecycle_reentry_terminal_closeout",
}
_SOURCE_FIELDS = (
    "status",
    "no_followup",
    "completion_continuation",
    "completion_turn_key",
    "successor_todo_ids",
    "validation_command",
    "validation_command_argv",
    "validation_label",
    "validation_timeout_seconds",
)


def _json_sequence(value: Any) -> Any:
    if isinstance(value, (tuple, set)):
        return list(value)
    return value


def todo_completion_source_snapshot(todo: Mapping[str, Any]) -> dict[str, Any]:
    """Project exactly the Todo fields owned by completion admission.

    The snapshot is a transport/CAS boundary, not a second semantic decoder.
    Python compares it after taking the mutation lock so a validation planned
    against one declaration cannot authorize a different persisted Todo.
    """

    return {
        field: (
            _json_sequence(todo.get(field))
            if field in {"successor_todo_ids", "validation_command_argv"}
            else todo.get(field)
        )
        for field in _SOURCE_FIELDS
    }


def todo_completion_source_matches(
    expected: Mapping[str, Any],
    todo: Mapping[str, Any],
) -> bool:
    return dict(expected) == todo_completion_source_snapshot(todo)


def todo_completion_source_drift_failure(
    *,
    goal_id: str,
    todo_id: str,
    dry_run: bool,
    reason: str,
) -> dict[str, Any]:
    """Project a retryable compare-and-swap miss without claiming a write."""

    return {
        "ok": False,
        "dry_run": dry_run,
        "completed": False,
        "changed": False,
        "goal_id": goal_id,
        "todo_id": todo_id,
        "completion_source_drift": True,
        "reason": reason,
    }


def _valid_fence(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return (
        value.get("schema_version") == "loopx_todo_completion_fence_result_v0"
        and value.get("outcome") in {"continue", "replay"}
        and isinstance(value.get("reason"), str)
        and isinstance(value.get("status"), str)
        and isinstance(value.get("terminal_before_request"), bool)
        and (
            value.get("completion_continuation") is None
            or value.get("completion_continuation") in _CONTINUATIONS
        )
    )


def _valid_receipt(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return (
        value.get("schema_version") == "issue_fix_validation_command_v0"
        and isinstance(value.get("command_label"), str)
        and bool(str(value.get("command_label") or "").strip())
        and (
            value.get("exit_code") is None
            or (
                isinstance(value.get("exit_code"), int)
                and not isinstance(value.get("exit_code"), bool)
            )
        )
        and isinstance(value.get("passed"), bool)
        and (
            (value.get("passed") is True and value.get("exit_code") == 0)
            or (
                value.get("passed") is False
                and value.get("exit_code") != 0
            )
        )
        and (
            value.get("status") is None
            or isinstance(value.get("status"), str)
        )
        and (
            value.get("summary") is None
            or isinstance(value.get("summary"), str)
        )
        and value.get("stdout_captured") is False
        and value.get("stderr_captured") is False
        and value.get("local_path_captured") is False
    )


def _valid_common(result: Mapping[str, Any]) -> bool:
    return (
        result.get("schema_version") == TODO_COMPLETION_TRANSACTION_RESULT_SCHEMA
        and result.get("decision") in _DECISIONS
        and (
            result.get("completion_identity_key") is None
            or isinstance(result.get("completion_identity_key"), str)
        )
        and (
            result.get("completion_identity_source") is None
            or result.get("completion_identity_source") in _IDENTITY_SOURCES
        )
        and _valid_fence(result.get("fence"))
    )


def _valid_result(result: Mapping[str, Any]) -> bool:
    if not _valid_common(result):
        return False
    decision = result.get("decision")
    if decision == "execute_validation":
        effect = result.get("validation_effect")
        return (
            isinstance(effect, Mapping)
            and effect.get("kind") == "caller_validation"
            and (
                effect.get("validation_command") is None
                or isinstance(effect.get("validation_command"), str)
            )
            and (
                effect.get("validation_argv") is None
                or (
                    isinstance(effect.get("validation_argv"), list)
                    and bool(effect.get("validation_argv"))
                    and all(
                        isinstance(item, str) and item
                        for item in effect.get("validation_argv") or []
                    )
                )
            )
            and (
                (effect.get("validation_command") is None)
                != (effect.get("validation_argv") is None)
            )
            and (
                effect.get("validation_label") is None
                or isinstance(effect.get("validation_label"), str)
            )
            and (
                effect.get("validation_timeout_seconds") is None
                or (
                    isinstance(effect.get("validation_timeout_seconds"), int)
                    and not isinstance(
                        effect.get("validation_timeout_seconds"), bool
                    )
                    and 1
                    <= int(effect["validation_timeout_seconds"])
                    <= 29
                )
            )
        )
    if decision == "commit":
        state = result.get("completion_state")
        updates = result.get("metadata_updates")
        receipt = result.get("validation_receipt")
        return (
            isinstance(state, Mapping)
            and state.get("continuation") in _CONTINUATIONS
            and (
                state.get("recovery") is None
                or state.get("recovery") in _RECOVERIES
            )
            and isinstance(updates, Mapping)
            and all(
                key in {"completion_continuation", "completion_recovery"}
                and isinstance(value, str)
                for key, value in updates.items()
            )
            and updates.get("completion_continuation")
            == state.get("continuation")
            and updates.get("completion_recovery") == state.get("recovery")
            and (receipt is None or _valid_receipt(receipt))
        )
    if decision == "replay":
        return result["fence"].get("outcome") == "replay"
    failure = result.get("failure")
    return (
        isinstance(failure, Mapping)
        and failure.get("kind")
        in {"validation_declaration_invalid", "validation_failed"}
        and isinstance(failure.get("summary"), str)
        and _valid_receipt(failure.get("validation_receipt"))
        and failure["validation_receipt"].get("passed") is False
    )


def reduce_todo_completion_transaction(
    *,
    todo: Mapping[str, Any],
    projection_source: str,
    goal_id: str,
    todo_id: str,
    completion_turn_key: str | None,
    completion_identity_source: str | None,
    no_followup: bool,
    requested_has_successor: bool,
    dry_run: bool,
    validation_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reduce one coarse completion request through the TS authority."""

    try:
        result = effect_runtime_result(
            "todo.completion.reduce",
            {
                "schema_version": TODO_COMPLETION_TRANSACTION_REQUEST_SCHEMA,
                "goal_id": goal_id,
                "todo_id": todo_id,
                "projection_source": projection_source,
                "todo": todo_completion_source_snapshot(todo),
                "requested_no_followup": no_followup,
                "requested_completion_turn_key": completion_turn_key,
                "requested_completion_identity_source": completion_identity_source,
                "requested_has_successor": requested_has_successor,
                "dry_run": dry_run,
                "validation_receipt": (
                    dict(validation_receipt)
                    if isinstance(validation_receipt, Mapping)
                    else None
                ),
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping):
        raise RuntimeError("TypeScript Todo completion transaction result must be an object")
    if not _valid_result(result):
        raise RuntimeError("TypeScript Todo completion transaction result shape mismatch")
    return dict(result)
