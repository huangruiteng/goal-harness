from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...control_plane.runtime.public_safety import public_safe_compact_text
from ...registry import registry_goals
from .private_json import write_private_json_atomic


GOAL_CHANNEL_BINDING_SCHEMA_VERSION = "loopx_goal_channel_lark_binding_v0"
GOAL_CHANNEL_OPERATION_SCHEMA_VERSION = "loopx_goal_channel_operation_v0"
# Compatibility export for older callers. Scheduler-projected reminder windows
# now own repeat-notification timing.
DEFAULT_GATE_COOLDOWN_SECONDS = 3600
HUMAN_GATE_AUTO_NOTIFY_SETTING = "human_gate_auto_notify_enabled"
HUMAN_GATE_AUTO_NOTIFY_MARKER_SCHEMA_VERSION = (
    "loopx_goal_channel_auto_notify_marker_v0"
)
PRIVATE_PACKET_KEYS = {
    "base_token",
    "chat_id",
    "config_path",
    "message_id",
    "path",
    "profile",
    "sender_profile",
    "table_id",
}
GATE_ACTION_PREFIX = re.compile(
    r"^(?:(?:[-*•]|\d+[.)])\s*)?(?:\[[ xX]\]\s*)?(?:\[P\d+\]\s*)?"
)


def default_goal_channel_binding_path(registry_path: Path) -> Path:
    expanded = registry_path.expanduser().resolve()
    if expanded.parent.name != ".loopx":
        raise ValueError(
            "Goal Channel default binding requires a project source registry"
        )
    return expanded.parent / "goal-channel.json"


def read_goal_channel_binding(path: Path) -> dict[str, Any]:
    binding_path = path.expanduser()
    if not binding_path.exists():
        return {
            "schema_version": GOAL_CHANNEL_BINDING_SCHEMA_VERSION,
            "bindings": {},
        }
    payload = json.loads(binding_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Goal Channel binding root must be a JSON object")
    if payload.get("schema_version") != GOAL_CHANNEL_BINDING_SCHEMA_VERSION:
        raise ValueError(
            f"Goal Channel binding must use {GOAL_CHANNEL_BINDING_SCHEMA_VERSION}"
        )
    bindings = payload.get("bindings")
    if not isinstance(bindings, dict):
        raise ValueError("Goal Channel binding requires an object `bindings`")
    return payload


def write_goal_channel_binding(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    binding_path = path.expanduser()
    write_private_json_atomic(binding_path, payload)


def goal_from_registry(
    registry: Mapping[str, Any],
    goal_id: str,
) -> dict[str, Any]:
    safe_goal_id = str(goal_id or "").strip()
    match = next(
        (
            dict(goal)
            for goal in registry_goals(dict(registry))
            if str(goal.get("id") or "") == safe_goal_id
        ),
        None,
    )
    if match is None:
        raise ValueError(f"Goal Channel goal `{safe_goal_id}` is not registered")
    return match


def binding_for_goal(
    payload: Mapping[str, Any],
    goal_id: str,
    *,
    provider_target: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    bindings = payload.get("bindings")
    binding = bindings.get(goal_id) if isinstance(bindings, Mapping) else None
    if not isinstance(binding, Mapping):
        return None
    resolved = dict(binding)
    target_ref = str(resolved.get("target_ref") or "")
    if not target_ref or provider_target is None:
        return resolved
    if str(provider_target.get("name") or "") != target_ref:
        raise ValueError("Goal Channel provider target does not match target_ref")
    if str(provider_target.get("provider") or "") != str(
        resolved.get("provider") or ""
    ):
        raise ValueError("Goal Channel provider target does not match provider")
    target_channel = provider_target.get("channel")
    target_identity = provider_target.get("identity")
    if not isinstance(target_channel, Mapping) or not isinstance(
        target_identity, Mapping
    ):
        raise ValueError("Goal Channel provider target is incomplete")
    binding_channel = resolved.get("channel")
    binding_channel = (
        dict(binding_channel) if isinstance(binding_channel, Mapping) else {}
    )
    resolved["channel"] = {
        **dict(target_channel),
        **(
            {"pinned_message_id": binding_channel["pinned_message_id"]}
            if binding_channel.get("pinned_message_id")
            else {}
        ),
    }
    resolved["identity"] = dict(target_identity)
    return resolved


def human_gate_auto_notify_enabled(binding: Mapping[str, Any] | None) -> bool:
    automation = (
        binding.get("automation")
        if isinstance(binding, Mapping)
        and isinstance(binding.get("automation"), Mapping)
        else {}
    )
    return automation.get(HUMAN_GATE_AUTO_NOTIFY_SETTING) is True


def human_gate_auto_notify_marker_path(
    binding_path: Path,
    goal_id: str,
) -> Path:
    safe_goal_id = str(goal_id or "").strip()
    if (
        not safe_goal_id
        or safe_goal_id in {".", ".."}
        or "/" in safe_goal_id
        or "\\" in safe_goal_id
    ):
        raise ValueError("Goal Channel goal id must be a single path segment")
    return binding_path.with_name(
        f"{binding_path.stem}.{safe_goal_id}.human-gate-auto-notify.json"
    )


def human_gate_auto_notify_marker_enabled(path: Path) -> bool:
    marker_path = path.expanduser()
    if not marker_path.exists():
        return False
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return bool(
        isinstance(payload, Mapping)
        and payload.get("schema_version")
        == HUMAN_GATE_AUTO_NOTIFY_MARKER_SCHEMA_VERSION
        and payload.get("enabled") is True
    )


def write_human_gate_auto_notify_marker(path: Path) -> None:
    write_private_json_atomic(
        path,
        {
            "schema_version": HUMAN_GATE_AUTO_NOTIFY_MARKER_SCHEMA_VERSION,
            "enabled": True,
        },
    )


def clear_human_gate_auto_notify_marker(path: Path) -> None:
    path.expanduser().unlink(missing_ok=True)


def quota_human_gate_identity(quota_packet: Mapping[str, Any]) -> str:
    summary = quota_packet.get("user_todo_summary")
    summary = summary if isinstance(summary, Mapping) else {}
    for key in ("gate_open_items", "first_open_items"):
        items = summary.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            identity = str(item.get("todo_id") or item.get("gate_id") or "").strip()
            if identity:
                return identity
    return str(
        quota_packet.get("gate_id")
        or quota_packet.get("operator_gate_id")
        or "unidentified_gate"
    ).strip()


def _quota_human_gate_items(
    quota_packet: Mapping[str, Any],
) -> list[dict[str, Any]]:
    summary = quota_packet.get("user_todo_summary")
    summary = summary if isinstance(summary, Mapping) else {}
    for key in ("gate_open_items", "first_open_items"):
        raw_items = summary.get(key)
        if not isinstance(raw_items, list):
            continue
        items = [dict(item) for item in raw_items if isinstance(item, Mapping)]
        if items:
            return items[:3]
    return []


def quota_human_gate_state_generation(
    quota_packet: Mapping[str, Any],
) -> str:
    """Fingerprint the material state of the currently projected human gate."""

    material_items = []
    for item in _quota_human_gate_items(quota_packet):
        material_items.append(
            {
                key: item.get(key)
                for key in (
                    "todo_id",
                    "gate_id",
                    "status",
                    "task_class",
                    "updated_at",
                    "material_change_generation",
                    "decision_scope",
                    "decision_outcome",
                    "blocks_agent",
                    "global_gate",
                    "unblocks_todo_id",
                )
                if item.get(key) is not None
            }
        )
        text = public_safe_compact_text(
            item.get("text") or item.get("title"),
            limit=300,
        )
        if text:
            material_items[-1]["text"] = text
    material: dict[str, Any] = {
        "gate_identity": quota_human_gate_identity(quota_packet),
        "items": material_items,
    }
    if not material_items:
        material["state"] = str(quota_packet.get("state") or "")
        material["question"] = public_safe_compact_text(
            quota_packet.get("gate_prompt")
            or quota_packet.get("operator_question")
            or quota_packet.get("reason"),
            limit=900,
        )
    return semantic_key(
        "human_gate_state_v0",
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def quota_human_gate_reminder_generation(
    quota_packet: Mapping[str, Any],
) -> str | None:
    cooldown = quota_packet.get("user_gate_notification_cooldown")
    if (
        not isinstance(cooldown, Mapping)
        or cooldown.get("notification_due") is not True
    ):
        return None
    reminder_identity = {
        key: cooldown.get(key)
        for key in (
            "policy",
            "failed_at",
            "next_reminder_at",
            "cooldown_minutes",
            "reminder_window_minutes",
        )
        if cooldown.get(key) is not None
    }
    return semantic_key(
        "human_gate_reminder_v0",
        json.dumps(
            reminder_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def quota_human_gate_notification_suppressed(
    quota_packet: Mapping[str, Any],
) -> bool:
    cooldown = quota_packet.get("user_gate_notification_cooldown")
    return bool(
        isinstance(cooldown, Mapping)
        and cooldown.get("notification_suppressed") is True
    )


def quota_selects_human_gate(quota_packet: Mapping[str, Any]) -> bool:
    if quota_human_gate_notification_suppressed(quota_packet):
        return False
    interaction = quota_packet.get("interaction_contract")
    if isinstance(interaction, Mapping):
        user_channel = interaction.get("user_channel")
        if isinstance(user_channel, Mapping):
            if user_channel.get("notify") != "NOTIFY":
                return False
            if user_channel.get("action_required") is True or bool(
                user_channel.get("actions")
            ):
                return True
    return bool(
        quota_packet.get("state") == "operator_gate"
        or quota_packet.get("notify_user_on_gate") is True
        or quota_packet.get("notify_user_on_open_todo") is True
    )


def save_goal_binding(
    *,
    binding_path: Path,
    payload: Mapping[str, Any],
    goal_id: str,
    binding: Mapping[str, Any],
) -> None:
    bindings = payload.get("bindings")
    mutable_bindings = dict(bindings) if isinstance(bindings, Mapping) else {}
    mutable_bindings[goal_id] = dict(binding)
    write_goal_channel_binding(
        binding_path,
        {
            "schema_version": GOAL_CHANNEL_BINDING_SCHEMA_VERSION,
            "bindings": mutable_bindings,
        },
    )


def semantic_key(*parts: str) -> str:
    digest = hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def provider_idempotency_key(receipt: str) -> str:
    return f"loopx-{receipt.removeprefix('sha256:')[:32]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def operation_packet(
    *,
    ok: bool,
    goal_id: str | None,
    operation: str,
    execute: bool,
    status: str,
    public_summary: str,
    external_write_performed: bool = False,
    readback_verified: bool = False,
    idempotency_key: str | None = None,
    receipt_id: str | None = None,
    blocker: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": GOAL_CHANNEL_OPERATION_SCHEMA_VERSION,
        "ok": ok,
        "goal_id": goal_id,
        "provider": "lark",
        "operation": operation,
        "execute": execute,
        "status": status,
        "external_write_performed": external_write_performed,
        "readback_verified": readback_verified,
        "idempotency_key": idempotency_key,
        "receipt_id": receipt_id,
        "public_summary": public_summary,
        "private_provider_payload_captured": False,
    }
    if blocker:
        packet["blocker"] = blocker
    if details:
        packet["details"] = dict(details)
    assert_public_packet(packet)
    return packet


def assert_public_packet(packet: Mapping[str, Any]) -> None:
    from .goal_channel_transport import CHAT_ID_PATTERN, MESSAGE_ID_PATTERN

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in PRIVATE_PACKET_KEYS:
                    raise ValueError(
                        f"public Goal Channel packet contains private key `{key}`"
                    )
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            if CHAT_ID_PATTERN.search(value) or MESSAGE_ID_PATTERN.search(value):
                raise ValueError(
                    "public Goal Channel packet contains a private provider id"
                )

    visit(packet)


def goal_objective(goal: Mapping[str, Any]) -> str:
    return public_safe_compact_text(
        goal.get("objective") or goal.get("description") or goal.get("id"),
        limit=300,
    )


def control_message(
    *,
    goal_id: str,
    objective: str,
    kanban_url: str,
) -> str:
    lines = [
        f"LoopX Goal: {goal_id}",
        f"Objective: {objective}",
        "LoopX remains the source of truth for todos, gates, quota, and evidence.",
    ]
    if kanban_url:
        lines.append(f"Kanban: {kanban_url}")
    return "\n".join(lines)


def gate_message(
    *,
    goal_id: str,
    objective: str,
    quota_packet: Mapping[str, Any],
    kanban_url: str,
) -> tuple[str, str]:
    question = public_safe_compact_text(
        quota_packet.get("gate_prompt")
        or quota_packet.get("operator_question")
        or quota_packet.get("reason")
        or "A human decision is required.",
        limit=900,
    )
    interaction = quota_packet.get("interaction_contract")
    interaction = interaction if isinstance(interaction, Mapping) else {}
    user_channel = interaction.get("user_channel")
    user_channel = user_channel if isinstance(user_channel, Mapping) else {}
    raw_actions = user_channel.get("actions")
    action_lines = (
        [public_safe_compact_text(action, limit=300) for action in raw_actions[:3]]
        if isinstance(raw_actions, list)
        else []
    )
    if not any(action_lines):
        action_lines = [
            public_safe_compact_text(
                item.get("text") or item.get("title"),
                limit=300,
            )
            for item in _quota_human_gate_items(quota_packet)
        ]
    unique_actions: list[str] = []
    for action in action_lines or [question]:
        cleaned = GATE_ACTION_PREFIX.sub("", action.strip()).strip()
        if cleaned and cleaned not in unique_actions:
            unique_actions.append(cleaned)
    lines = [
        "LoopX · Action required",
        "",
        f"Goal: {goal_id}",
    ]
    if objective and objective != goal_id:
        lines.append(f"Objective: {objective}")
    lines.extend(["", "Please confirm:"])
    lines.extend(
        f"{index}. {action}" for index, action in enumerate(unique_actions, start=1)
    )
    lines.extend(
        [
            "",
            "Reply: approve / reject / done / still pending, plus a one-sentence reason.",
            "Unchanged gate state will stay quiet until an explicit reminder window.",
        ]
    )
    if kanban_url:
        lines.extend(["", f"Kanban: {kanban_url}"])
    return "\n".join(lines), question
