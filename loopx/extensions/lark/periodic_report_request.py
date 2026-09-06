"""Bind an Agent-selected Lark inbox item to the periodic-report action.

This adapter validates provider identity, addressing, and Goal/Agent routing.
It deliberately does not inspect message text or decide report intent; the
Agent has already made that semantic decision before invoking the typed action.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...agent_registry import registered_agent_ids_for_goal
from ...capabilities.periodic_report.request_action import (
    REQUEST_ADAPTER_PHASE,
    REQUEST_BIND_PORT,
    REQUEST_HOOK_ID,
    REQUEST_SETTLE_PORT,
    SOURCE_BINDING_RECEIPT_SCHEMA,
    SOURCE_SETTLEMENT_RECEIPT_SCHEMA,
)
from ...control_plane.runtime.goal_project_route import resolve_goal_project_route
from ..hook_adapters import HOOK_ADAPTER_FACTORY_CONTEXT_SCHEMA_VERSION
from .event_collector import load_lark_event_collector_config
from .event_inbox import (
    MESSAGE_ID_PATTERN,
    _event_from_file,
    _load_processed,
    acknowledge_lark_event_inbox,
    load_lark_event_inbox_config,
)
from .goal_channel_contracts import (
    binding_for_goal,
    bindings_for_goal,
    default_goal_channel_binding_path,
    read_goal_channel_binding,
)
from .goal_channel_targets import (
    default_goal_channel_target_path,
    goal_channel_target_for_name,
    read_goal_channel_targets,
)
from .routed_inbox import lark_inbox_config_kind


LARK_REQUEST_ADAPTER_ID = "lark-periodic-report-source"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _observed_at(value: object) -> str:
    raw = str(value or "").strip()
    try:
        if raw.isdigit():
            number = int(raw)
            seconds = number / 1000 if number >= 10_000_000_000 else number
            parsed = datetime.fromtimestamp(seconds, tz=UTC)
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
            parsed = parsed.astimezone(UTC)
    except (OSError, OverflowError, ValueError) as exc:
        raise ValueError("Lark periodic-report source timestamp is invalid") from exc
    return parsed.isoformat().replace("+00:00", "Z")


def _goal_agent_inbox_config(goal: Mapping[str, Any], agent_id: str) -> str:
    control_plane = goal.get("control_plane")
    control_plane = control_plane if isinstance(control_plane, Mapping) else {}
    inboxes = control_plane.get("lark_event_inboxes")
    inboxes = inboxes if isinstance(inboxes, Mapping) else {}
    inbox = inboxes.get(agent_id)
    if not isinstance(inbox, Mapping) or inbox.get("enabled") is not True:
        raise ValueError("Agent-scoped Lark inbox is not enabled")
    config_ref = str(inbox.get("config_path") or "").strip()
    if not config_ref:
        raise ValueError("Agent-scoped Lark inbox config is missing")
    return config_ref


def _resolved_request_context(
    *, registry_path: Path, runtime_root: Path, goal_id: str, agent_id: str
) -> dict[str, Any]:
    goal, project, route = resolve_goal_project_route(
        registry_path=registry_path,
        goal_id=goal_id,
    )
    if agent_id not in registered_agent_ids_for_goal(goal):
        raise ValueError("periodic-report request Agent is not registered")
    config_ref = _goal_agent_inbox_config(goal, agent_id)
    source_registry = Path(str(route["source_registry"])).expanduser().resolve()
    binding_payload = read_goal_channel_binding(
        default_goal_channel_binding_path(source_registry)
    )
    matches = [
        binding
        for binding in bindings_for_goal(binding_payload, goal_id)
        if binding.get("enabled") is True
        and str(binding.get("agent_id") or "") == agent_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "periodic-report request requires one Agent Goal Channel binding"
        )
    raw_binding = matches[0]
    routing = raw_binding.get("routing")
    routing = routing if isinstance(routing, Mapping) else {}
    if (
        raw_binding.get("provider") != "lark"
        or routing.get("ingress_mode") != "async_inbox"
        or str(routing.get("inbox_config_ref") or "") != config_ref
    ):
        raise ValueError("Agent Goal Channel inbox binding is inconsistent")

    target_ref = str(raw_binding.get("target_ref") or "").strip()
    target = goal_channel_target_for_name(
        read_goal_channel_targets(default_goal_channel_target_path(runtime_root)),
        target_ref,
    )
    if (
        target is None
        or target.get("enabled") is not True
        or target.get("provider") != "lark"
    ):
        raise ValueError("Agent Goal Channel Lark target is unavailable")
    binding = binding_for_goal(
        binding_payload,
        goal_id,
        provider_target=target,
        connection_id=str(raw_binding.get("connection_id") or ""),
    )
    if binding is None:
        raise ValueError("Agent Goal Channel binding is incomplete")

    channel = binding.get("channel")
    channel = channel if isinstance(channel, Mapping) else {}
    identity = binding.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    config_kind = lark_inbox_config_kind(project=project, config_path=config_ref)
    selected_route_key = "default"
    selected_config_ref = config_ref
    if config_kind == "collector":
        collector = load_lark_event_collector_config(
            project=project,
            config_path=config_ref,
        )
        routes = [
            route
            for route in collector["routes"]
            if str(route.get("chat_id") or "") == str(channel.get("chat_id") or "")
        ]
        if (
            collector.get("enabled") is not True
            or collector.get("identity") != "bot"
            or str(collector.get("profile") or "")
            != str(identity.get("sender_profile") or "")
            or len(routes) != 1
        ):
            raise ValueError("Agent inbox collector does not match its Goal Channel")
        route = routes[0]
        selected_route_key = str(route.get("route_key") or "")
        selected_config_ref = str(route.get("event_inbox_config_ref") or "")
        config = dict(route["inbox"])
    else:
        config = load_lark_event_inbox_config(
            project=project,
            config_path=config_ref,
        )
    reply = config.get("reply")
    reply = reply if isinstance(reply, Mapping) else {}
    if (
        config.get("enabled") is not True
        or identity.get("mode") != "project_bot"
        or identity.get("sender_identity") != "bot"
        or (
            config_kind == "inbox"
            and (
                reply.get("enabled") is not True
                or reply.get("sender_identity") != "bot"
                or str(reply.get("sender_profile") or "")
                != str(identity.get("sender_profile") or "")
                or str(reply.get("bot_display_name") or "")
                != str(identity.get("bot_display_name") or "")
                or str(reply.get("chat_id") or "")
                != str(channel.get("chat_id") or "")
            )
        )
    ):
        raise ValueError("Agent inbox identity does not match its Goal Channel")

    binding_revision = _digest(
        {
            "goal_id": goal_id,
            "agent_id": agent_id,
            "connection_id": binding.get("connection_id"),
            "target_ref": target_ref,
            "config_ref": config_ref,
            "selected_route_key": selected_route_key,
            "selected_config_ref": selected_config_ref,
            "capture_scope": routing.get("capture_scope"),
            "chat_id": channel.get("chat_id"),
            "sender_profile": identity.get("sender_profile"),
            "bot_display_name": identity.get("bot_display_name"),
        }
    )
    return {
        "project": project,
        "selected_config_ref": selected_config_ref,
        "config": config,
        "binding_revision": binding_revision,
    }


def _addressing_source(event: Mapping[str, Any]) -> str:
    source = str(event.get("addressing_source") or "")
    mention_count = event.get("provider_mention_count")
    target_count = event.get("target_mention_count")
    if (
        event.get("sender_type") != "user"
        or event.get("addressed_to_bot") is not True
        or type(mention_count) is not int
        or type(target_count) is not int
    ):
        raise ValueError("Lark periodic-report source is not an addressed user item")
    if source == "provider_mention" and mention_count == 1 and target_count == 1:
        return source
    if (
        source == "verified_reply"
        and event.get("reply_to_bot") is True
        and (mention_count == 0 or (mention_count == 1 and target_count == 1))
    ):
        return source
    raise ValueError("Lark periodic-report source addressing is ambiguous")


def _source_receipt(
    event: Mapping[str, Any], *, goal_id: str, agent_id: str, binding_revision: str
) -> dict[str, Any]:
    source_ref = str(event.get("message_id") or "")
    if not MESSAGE_ID_PATTERN.fullmatch(source_ref):
        raise ValueError("Lark periodic-report source reference is invalid")
    observed_at = _observed_at(event.get("create_time"))
    addressing_source = _addressing_source(event)
    identity = {
        "provider": "lark",
        "goal_id": goal_id,
        "agent_id": agent_id,
        "source_ref": source_ref,
        "observed_at": observed_at,
        "requester_kind": "user",
        "addressing_source": addressing_source,
        "binding_revision": binding_revision,
    }
    return {
        "schema_version": SOURCE_BINDING_RECEIPT_SCHEMA,
        **identity,
        "source_digest": _digest(identity),
        "raw_content_returned": False,
        "external_writes_performed": False,
    }


def bind_lark_periodic_report_source(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    agent_id: str,
    source_ref: str,
) -> dict[str, Any]:
    """Bind one exact pending source item without reading its semantic content."""

    if not MESSAGE_ID_PATTERN.fullmatch(str(source_ref or "")):
        raise ValueError("Lark periodic-report source reference is invalid")
    context = _resolved_request_context(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
    )
    inbox = context["config"]["inbox_path"]
    if source_ref in _load_processed(inbox / "processed.json"):
        raise ValueError("Lark periodic-report source is already settled")
    event = _event_from_file(inbox / f"{source_ref}.json")
    if not isinstance(event, Mapping) or event.get("message_id") != source_ref:
        raise ValueError("Lark periodic-report source is unavailable")
    return _source_receipt(
        event,
        goal_id=goal_id,
        agent_id=agent_id,
        binding_revision=str(context["binding_revision"]),
    )


def settle_lark_periodic_report_source(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    agent_id: str,
    source_receipt: Mapping[str, Any],
    execute: bool,
) -> dict[str, Any]:
    """ACK the exact source only after capability durability is established."""

    context = _resolved_request_context(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
    )
    source_ref = str(source_receipt.get("source_ref") or "")
    if (
        source_receipt.get("schema_version") != SOURCE_BINDING_RECEIPT_SCHEMA
        or source_receipt.get("goal_id") != goal_id
        or source_receipt.get("agent_id") != agent_id
        or source_receipt.get("binding_revision") != context["binding_revision"]
        or not MESSAGE_ID_PATTERN.fullmatch(source_ref)
    ):
        raise ValueError("Lark periodic-report source binding drifted")
    inbox = context["config"]["inbox_path"]
    event = _event_from_file(inbox / f"{source_ref}.json")
    if not isinstance(event, Mapping):
        raise ValueError("Lark periodic-report source is unavailable")
    current = _source_receipt(
        event,
        goal_id=goal_id,
        agent_id=agent_id,
        binding_revision=str(context["binding_revision"]),
    )
    if current != dict(source_receipt):
        raise ValueError("Lark periodic-report source receipt drifted")
    receipt = acknowledge_lark_event_inbox(
        project=context["project"],
        config_path=context["selected_config_ref"],
        message_ids=[source_ref],
        execute=execute,
    )
    settled = execute and (
        int(receipt.get("new_count") or 0) == 1
        or int(receipt.get("already_acknowledged_count") or 0) == 1
    )
    return {
        "ok": receipt.get("ok") is True,
        "schema_version": SOURCE_SETTLEMENT_RECEIPT_SCHEMA,
        "status": "settled" if settled else "preview" if not execute else "failed",
        "write_performed": receipt.get("write_performed") is True,
        "raw_content_returned": False,
        "external_writes_performed": False,
    }


def build_lark_periodic_report_hook_adapter(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Build typed source ports from one manifest-discovered activation."""

    required = {
        "schema_version",
        "extension_id",
        "adapter_id",
        "capability_id",
        "target_hook_id",
        "phase",
        "activation",
        "registry_path",
        "runtime_root",
        "goal_id",
        "agent_id",
    }
    activation = context.get("activation")
    if (
        set(context) != required
        or context.get("schema_version")
        != HOOK_ADAPTER_FACTORY_CONTEXT_SCHEMA_VERSION
        or context.get("extension_id") != "loopx-lark"
        or context.get("adapter_id") != LARK_REQUEST_ADAPTER_ID
        or context.get("capability_id") != "periodic-report"
        or context.get("target_hook_id") != REQUEST_HOOK_ID
        or context.get("phase") != REQUEST_ADAPTER_PHASE
        or not isinstance(activation, Mapping)
        or activation.get("extension_id") != "loopx-lark"
        or activation.get("enabled") is not True
        or activation.get("doctor_verified") is not True
        or set(activation.get("required_permissions") or [])
        != {"lark.inbox.read", "lark.inbox.write"}
    ):
        raise ValueError("Lark periodic-report hook adapter context is invalid")
    return {
        REQUEST_BIND_PORT: bind_lark_periodic_report_source,
        REQUEST_SETTLE_PORT: settle_lark_periodic_report_source,
    }


__all__ = [
    "LARK_REQUEST_ADAPTER_ID",
    "bind_lark_periodic_report_source",
    "build_lark_periodic_report_hook_adapter",
    "settle_lark_periodic_report_source",
]
