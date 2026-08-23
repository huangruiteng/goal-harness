from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result


TODO_COMPLETION_FENCE_REQUEST_SCHEMA = "loopx_todo_completion_fence_request_v0"
TODO_COMPLETION_FENCE_RESULT_SCHEMA = "loopx_todo_completion_fence_result_v0"


def _json_successor_value(value: Any) -> Any:
    if isinstance(value, (tuple, set)):
        return list(value)
    return value


def evaluate_todo_completion_fence(
    *,
    todo: Mapping[str, Any],
    projection_source: str,
    completion_turn_key: str | None,
    no_followup: bool,
    goal_id: str | None = None,
    todo_id: str | None = None,
    completion_identity_source: str | None = None,
) -> dict[str, Any]:
    """Ask the TypeScript Todo owner for the canonical replay-fence decision."""

    raw_no_followup = todo.get("no_followup")
    if raw_no_followup is not None and not isinstance(raw_no_followup, (bool, str)):
        raw_no_followup = str(raw_no_followup)
    raw_continuation = todo.get("completion_continuation")
    if raw_continuation is not None and not isinstance(raw_continuation, str):
        raw_continuation = str(raw_continuation)
    raw_turn_key = todo.get("completion_turn_key")
    if raw_turn_key is not None and not isinstance(raw_turn_key, str):
        raw_turn_key = str(raw_turn_key)
    try:
        result = effect_runtime_result(
            "todo.completion_fence.evaluate",
            {
                "schema_version": TODO_COMPLETION_FENCE_REQUEST_SCHEMA,
                "projection_source": projection_source,
                "todo": {
                    "status": str(todo.get("status") or "open"),
                    "no_followup": raw_no_followup,
                    "completion_continuation": raw_continuation,
                    "completion_turn_key": raw_turn_key,
                    "successor_todo_ids": _json_successor_value(
                        todo.get("successor_todo_ids")
                    ),
                },
                "requested_no_followup": no_followup,
                "requested_completion_turn_key": completion_turn_key,
                "requested_completion_identity_source": completion_identity_source,
                "goal_id": goal_id,
                "todo_id": todo_id,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping):
        raise RuntimeError("TypeScript Todo completion fence result must be an object")
    if (
        result.get("schema_version") != TODO_COMPLETION_FENCE_RESULT_SCHEMA
        or result.get("outcome") not in {"continue", "replay"}
        or not isinstance(result.get("reason"), str)
        or not isinstance(result.get("status"), str)
        or not isinstance(result.get("terminal_before_request"), bool)
        or not (
            result.get("completion_continuation") is None
            or isinstance(result.get("completion_continuation"), str)
        )
    ):
        raise RuntimeError("TypeScript Todo completion fence result shape mismatch")
    return dict(result)
