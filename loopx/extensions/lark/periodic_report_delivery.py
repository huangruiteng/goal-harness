from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ...capabilities.periodic_report.adapters import PeriodicReportAdapterRegistry
from ...capabilities.periodic_report.bindings import (
    GENERATION_BUNDLE_SCHEMA,
    build_periodic_report_generation_bundle,
)
from ...capabilities.periodic_report.core import _reject_raw_keys
from . import LARK_EXTENSION_ID, LARK_GOAL_CHANNEL_PERMISSION
from .goal_channel_contracts import (
    binding_for_goal,
    default_goal_channel_binding_path,
    read_goal_channel_binding,
)
from .goal_channel_targets import (
    default_goal_channel_target_path,
    goal_channel_target_for_name,
    read_goal_channel_targets,
)
from .goal_channel_transport import (
    auth_verified,
    bot_membership_verified,
    call,
    chat_verified,
    contains_exact_field,
    find_first_string,
    json_payload,
    lark_args,
    MESSAGE_ID_PATTERN,
    verified_app_id,
)
from .presentation.kanban import CommandRunner, default_subprocess_runner
from .presentation.periodic_report import periodic_report_lark_sink_adapter


GOAL_CHANNEL_DELIVERY_REQUEST_SCHEMA = (
    "periodic_report_goal_channel_delivery_request_v0"
)
GOAL_CHANNEL_DELIVERY_RESULT_SCHEMA = "periodic_report_goal_channel_delivery_result_v0"
DELIVERY_INTENT_SCHEMA = "periodic_report_delivery_intent_v0"
_ANNOUNCEMENT_KINDS = ("hosted_report", "lark_document")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _text(value: object, label: str, *, maximum: int = 500) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return text


def _reject_unknown_fields(
    value: Mapping[str, Any], *, allowed: set[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _announcements(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(
            "Goal Channel periodic report delivery requires exactly two announcements"
        )
    normalized: list[dict[str, str]] = []
    for index, expected_kind in enumerate(_ANNOUNCEMENT_KINDS):
        label = f"delivery_intent.announcements[{index}]"
        raw = _mapping(value[index], label)
        _reject_unknown_fields(
            raw,
            allowed={"kind", "title", "url"},
            label=label,
        )
        if set(raw) != {"kind", "title", "url"}:
            raise ValueError(f"{label} requires kind, title, and url")
        kind = str(raw.get("kind") or "").strip()
        if kind != expected_kind:
            raise ValueError(
                "Goal Channel announcements must be ordered as hosted_report, "
                "lark_document"
            )
        url = _text(raw.get("url"), f"{label}.url")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"{label}.url must be an https URL")
        normalized.append(
            {
                "kind": kind,
                "title": _text(raw.get("title"), f"{label}.title", maximum=72),
                "url": url,
            }
        )
    return normalized


def _announcement_markdown(announcement: Mapping[str, str]) -> str:
    if announcement["kind"] == "hosted_report":
        return f"本期阶段周报已发布。\n\n[查看周报]({announcement['url']})"
    return f"配套 Lark 文档已同步。\n\n[查看 Lark 文档]({announcement['url']})"


def _normalized_generation_bundle(raw: object) -> dict[str, Any]:
    supplied = _mapping(raw, "generation_bundle")
    if supplied.get("schema_version") != GENERATION_BUNDLE_SCHEMA:
        raise ValueError(f"generation_bundle must use {GENERATION_BUNDLE_SCHEMA}")
    normalized = build_periodic_report_generation_bundle(
        document=_mapping(supplied.get("document"), "generation_bundle.document"),
        artifacts=[
            _mapping(item, "generation_bundle.artifacts[]")
            for item in supplied.get("artifacts") or []
        ],
    )
    if supplied != normalized:
        raise ValueError("generation_bundle does not match its normalized receipts")
    return normalized


def _resolved_goal_channel_binding(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
) -> dict[str, Any]:
    payload = read_goal_channel_binding(
        default_goal_channel_binding_path(registry_path)
    )
    raw = binding_for_goal(payload, goal_id)
    if raw is None:
        raise ValueError("periodic report delivery requires a Goal Channel binding")
    target_ref = str(raw.get("target_ref") or "").strip()
    target = None
    if target_ref:
        target = goal_channel_target_for_name(
            read_goal_channel_targets(default_goal_channel_target_path(runtime_root)),
            target_ref,
        )
        if target is None:
            raise ValueError("periodic report Goal Channel target is missing")
    resolved = binding_for_goal(
        payload,
        goal_id,
        provider_target=target,
    )
    if resolved is None:
        raise ValueError("periodic report Goal Channel binding is incomplete")
    return resolved


def _find_message(value: Any, message_id: str) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        if str(value.get("message_id") or "") == message_id:
            return value
        for child in value.values():
            found = _find_message(child, message_id)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_message(child, message_id)
            if found is not None:
                return found
    return None


def _message_card(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
    body = value.get("body")
    content = body.get("content") if isinstance(body, Mapping) else None
    if isinstance(content, Mapping):
        return content
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _normalized_card_text(card: Mapping[str, Any]) -> str | None:
    """Match the lossless interactive-card projection returned by new CLIs."""

    header = card.get("header")
    elements = card.get("elements")
    if not isinstance(header, Mapping) or not isinstance(elements, list):
        return None
    title = header.get("title")
    title = title.get("content") if isinstance(title, Mapping) else None
    if not isinstance(title, str) or not elements:
        return None
    first = elements[0]
    first = first if isinstance(first, Mapping) else {}
    text = first.get("text")
    markdown = text.get("content") if isinstance(text, Mapping) else None
    if not isinstance(markdown, str):
        return None
    footer = None
    if len(elements) == 3 and elements[1] == {"tag": "hr"}:
        note = elements[2]
        note_elements = note.get("elements") if isinstance(note, Mapping) else None
        if isinstance(note_elements, list) and len(note_elements) == 1:
            note_text = note_elements[0]
            footer = (
                note_text.get("content") if isinstance(note_text, Mapping) else None
            )
    lines = [f'<card title="{title}">', markdown]
    if isinstance(footer, str) and footer:
        lines.extend(["---", f"📝 {footer}"])
    lines.append("</card>")
    return "\n".join(lines)


def _message_card_matches(
    value: Mapping[str, Any], expected: Mapping[str, Any] | None
) -> bool:
    if expected is None:
        return False
    if _message_card(value) == expected:
        return True
    content = value.get("content")
    return isinstance(content, str) and content == _normalized_card_text(expected)


def _message_sender(value: Mapping[str, Any]) -> tuple[str, str]:
    sender = value.get("sender")
    sender = sender if isinstance(sender, Mapping) else {}
    sender_type = str(
        sender.get("sender_type") or value.get("sender_type") or ""
    ).strip()
    sender_id = str(
        sender.get("id") or sender.get("sender_id") or value.get("sender_id") or ""
    ).strip()
    return sender_type, sender_id


def _validate_extension_activation(value: Mapping[str, Any]) -> None:
    permissions = value.get("required_permissions")
    if (
        value.get("schema_version") != "loopx_extension_activation_v0"
        or value.get("extension_id") != LARK_EXTENSION_ID
        or value.get("enabled") is not True
        or value.get("doctor_verified") is not True
        or not isinstance(permissions, list)
        or LARK_GOAL_CHANNEL_PERMISSION not in permissions
    ):
        raise ValueError(
            "active Lark extension does not authorize Goal Channel delivery"
        )


def _normalized_delivery_request(
    request: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str, list[dict[str, str]], dict[str, Any]]:
    payload = _mapping(request, "request")
    _reject_unknown_fields(
        payload,
        allowed={"schema_version", "generation_bundle", "delivery_intent"},
        label="request",
    )
    if payload.get("schema_version") != GOAL_CHANNEL_DELIVERY_REQUEST_SCHEMA:
        raise ValueError(f"request must use {GOAL_CHANNEL_DELIVERY_REQUEST_SCHEMA}")
    generation = _normalized_generation_bundle(payload.get("generation_bundle"))
    intent = _mapping(payload.get("delivery_intent"), "request.delivery_intent")
    identity_override_keys = sorted(
        {
            "bot_app_id",
            "bot_display_name",
            "chat_id",
            "identity_mode",
            "lark_profile",
            "profile",
            "sender_identity",
            "sender_profile",
        }.intersection(intent)
    )
    if identity_override_keys:
        raise ValueError(
            "periodic report sender identity is owned by Goal Channel; "
            "caller overrides are forbidden: " + ", ".join(identity_override_keys)
        )
    _reject_unknown_fields(
        intent,
        allowed={
            "schema_version",
            "kind",
            "sink_id",
            "sink_kind",
            "idempotency_key",
            "artifact_id",
            "announcements",
        },
        label="delivery_intent",
    )
    if intent.get("schema_version") != DELIVERY_INTENT_SCHEMA:
        raise ValueError(f"delivery_intent must use {DELIVERY_INTENT_SCHEMA}")
    if (
        intent.get("kind") != "goal_channel"
        or intent.get("sink_kind") != "lark_message"
    ):
        raise ValueError("delivery_intent must select Goal Channel Lark delivery")
    sink_id = _text(intent.get("sink_id"), "delivery_intent.sink_id", maximum=128)
    idempotency_key = _text(
        intent.get("idempotency_key"),
        "delivery_intent.idempotency_key",
        maximum=256,
    )
    announcements = _announcements(intent.get("announcements"))
    _reject_raw_keys(payload, "request")
    artifacts = [
        artifact
        for artifact in generation["artifacts"]
        if artifact.get("renderer_kind") == "markdown"
        and (
            not intent.get("artifact_id")
            or artifact.get("artifact_id") == str(intent["artifact_id"]).strip()
        )
    ]
    if len(artifacts) != 1:
        raise ValueError("delivery intent must resolve exactly one Markdown artifact")
    return generation, sink_id, idempotency_key, announcements, artifacts[0]


class _GoalChannelDeliverySession:
    def __init__(
        self,
        *,
        goal_id: str,
        binding: Mapping[str, Any],
        runner: CommandRunner,
    ) -> None:
        self.goal_id = goal_id
        self.binding = dict(binding)
        self.runner = runner
        self.route: dict[str, Any] = {}
        self.expected_cards: dict[str, list[dict[str, Any]]] = {}

    def resolve(self, requested_goal_id: str) -> Mapping[str, Any]:
        if requested_goal_id != self.goal_id:
            raise ValueError("Goal Channel delivery goal identity changed")
        return self.binding

    def verify(self, route: Mapping[str, Any]) -> bool:
        cli_bin = str(route["cli_bin"])
        profile = str(route["sender_profile"])
        app_id = str(route["bot_app_id"])
        chat_id = str(route["chat_id"])
        checks = (
            auth_verified(
                runner=self.runner,
                cli_bin=cli_bin,
                profile=profile,
                identity="bot",
                expected_bot_name=str(route["bot_display_name"]),
            ),
            verified_app_id(
                runner=self.runner,
                cli_bin=cli_bin,
                profile=profile,
            )
            == app_id,
            chat_verified(
                runner=self.runner,
                cli_bin=cli_bin,
                profile=profile,
                identity="bot",
                chat_id=chat_id,
            ),
            bot_membership_verified(
                runner=self.runner,
                cli_bin=cli_bin,
                profile=profile,
                chat_id=chat_id,
                app_id=app_id,
            ),
        )
        verified = all(checks)
        if verified:
            self.route = dict(route)
        return verified

    def send(
        self,
        card: Mapping[str, Any],
        key: str,
        route: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        result = call(
            self.runner,
            lark_args(
                cli_bin=str(route["cli_bin"]),
                profile=str(route["sender_profile"]),
                tail=[
                    "im",
                    "+messages-send",
                    "--chat-id",
                    str(route["chat_id"]),
                    "--content",
                    json.dumps(card, ensure_ascii=False, separators=(",", ":")),
                    "--msg-type",
                    "interactive",
                    "--idempotency-key",
                    f"loopx-{hashlib.sha256(key.encode()).hexdigest()[:32]}",
                    "--as",
                    "bot",
                    "--format",
                    "json",
                ],
            ),
        )
        message_id = find_first_string(
            json_payload(result), {"message_id"}, MESSAGE_ID_PATTERN
        )
        if result.get("returncode") != 0 or not message_id:
            raise ValueError("Goal Channel periodic report send failed")
        self.expected_cards.setdefault(message_id, []).append(dict(card))
        return {"message_id": message_id}

    def readback(self, message_id: str) -> Mapping[str, Any]:
        result = call(
            self.runner,
            lark_args(
                cli_bin=str(self.route["cli_bin"]),
                profile=str(self.route["sender_profile"]),
                tail=[
                    "im",
                    "+messages-mget",
                    "--message-ids",
                    message_id,
                    "--as",
                    "bot",
                    "--no-reactions",
                    "--format",
                    "json",
                ],
            ),
        )
        message = _find_message(json_payload(result), message_id)
        sender_type, sender_app_id = (
            _message_sender(message) if message is not None else ("", "")
        )
        expected_card = (self.expected_cards.get(message_id) or [None]).pop(0)
        exact = bool(
            result.get("returncode") == 0
            and message is not None
            and contains_exact_field(message, "chat_id", str(self.route["chat_id"]))
            and _message_card_matches(message, expected_card)
            and sender_type == "app"
            and sender_app_id == self.route["bot_app_id"]
            and auth_verified(
                runner=self.runner,
                cli_bin=str(self.route["cli_bin"]),
                profile=str(self.route["sender_profile"]),
                identity="bot",
                expected_bot_name=str(self.route["bot_display_name"]),
            )
            and verified_app_id(
                runner=self.runner,
                cli_bin=str(self.route["cli_bin"]),
                profile=str(self.route["sender_profile"]),
            )
            == self.route["bot_app_id"]
        )
        return {
            "verified": exact,
            "message_id": message_id,
            "chat_id": self.route["chat_id"] if exact else None,
            "sender_app_id": sender_app_id if exact else None,
            "sender_identity": "bot" if exact else None,
            "sender_evidence_source": "message_readback" if exact else None,
        }


def _delivery_status(*, satisfied: bool, execute: bool) -> str:
    if satisfied:
        return "satisfied"
    if execute:
        return "readback_unverified"
    return "pending_execution"


def deliver_periodic_report_to_goal_channel(
    request: Mapping[str, Any],
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    extension_activation: Mapping[str, Any],
    execute: bool = False,
    runner: CommandRunner = default_subprocess_runner,
) -> dict[str, Any]:
    """Deliver one generated report through the Goal-bound project Bot only."""

    _validate_extension_activation(extension_activation)
    generation, sink_id, idempotency_key, announcements, artifact = (
        _normalized_delivery_request(request)
    )

    binding = _resolved_goal_channel_binding(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=goal_id,
    )
    session = _GoalChannelDeliverySession(
        goal_id=goal_id,
        binding=binding,
        runner=runner,
    )
    registry = PeriodicReportAdapterRegistry()
    registry.register_sink(
        periodic_report_lark_sink_adapter(
            send=session.send,
            readback=session.readback,
            resolve_goal_channel=session.resolve,
            verify_goal_channel=session.verify,
            sink_id=sink_id,
        )
    )
    message_results: list[dict[str, Any]] = []
    for announcement in announcements:
        content = _announcement_markdown(announcement)
        result = registry.deliver(
            sink_id,
            {
                **artifact,
                "content": content,
                "content_digest": "sha256:"
                + hashlib.sha256(content.encode("utf-8")).hexdigest(),
            },
            {
                "execute": bool(execute),
                "goal_id": goal_id,
                "idempotency_key": f"{idempotency_key}:{announcement['kind']}",
                "title": announcement["title"],
                "footer": "LoopX periodic report · Goal Channel",
            },
        )
        message_results.append({"kind": announcement["kind"], **result})
    satisfied = bool(
        execute
        and len(message_results) == 2
        and len({str(result.get("receipt_ref") or "") for result in message_results})
        == 2
        and all(
            result.get("status") == "sent"
            and result.get("readback_verified") is True
            and result.get("goal_channel_verified") is True
            and result.get("sender_identity_verified") is True
            for result in message_results
        )
    )
    sink_status = "sent" if satisfied else "unknown" if execute else "pending"
    sink_result = {
        "status": sink_status,
        "readback_verified": satisfied,
        "goal_channel_verified": satisfied,
        "sender_identity_verified": satisfied,
        "external_writes_performed": any(
            result.get("external_writes_performed") is True
            for result in message_results
        ),
        "message_results": message_results,
    }
    return {
        "ok": bool(satisfied or not execute),
        "schema_version": GOAL_CHANNEL_DELIVERY_RESULT_SCHEMA,
        "status": _delivery_status(satisfied=satisfied, execute=execute),
        "intent_satisfied": satisfied,
        "generation_id": generation["generation_receipt"]["generation_id"],
        "sink_result": sink_result,
        "boundary": {
            "goal_channel_binding_required": True,
            "project_bot_identity_required": True,
            "caller_identity_override_allowed": False,
            "exact_sender_and_chat_readback_required": True,
            "sender_evidence_source": "message_readback",
            "external_writes_performed": sink_result.get("external_writes_performed")
            is True,
        },
    }


__all__ = [
    "DELIVERY_INTENT_SCHEMA",
    "GOAL_CHANNEL_DELIVERY_REQUEST_SCHEMA",
    "GOAL_CHANNEL_DELIVERY_RESULT_SCHEMA",
    "deliver_periodic_report_to_goal_channel",
]
