from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .event_collector import (
    SUPPORTED_CONFIG_SCHEMA_VERSIONS as COLLECTOR_SCHEMA_VERSIONS,
)
from .event_collector import load_lark_event_collector_config
from .event_inbox import (
    CONFIG_SCHEMA_VERSION as INBOX_SCHEMA_VERSION,
)
from .event_inbox import (
    MESSAGE_ID_PATTERN,
    acknowledge_lark_event_inbox,
    ingest_lark_event_inbox,
    inspect_lark_event_inbox,
    load_lark_event_inbox_config,
    project_lark_event_inbox_urgency,
    settle_lark_event_inbox_material_review,
)


def lark_inbox_config_kind(*, project: str | Path, config_path: str | Path) -> str:
    """Classify one local-private inbox or routed collector config."""

    root = Path(project).expanduser().resolve()
    path = Path(config_path).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    try:
        path.relative_to(root)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Lark inbox config must be readable inside the project"
        ) from exc
    schema_version = (
        str(payload.get("schema_version") or "") if isinstance(payload, Mapping) else ""
    )
    if schema_version == INBOX_SCHEMA_VERSION:
        load_lark_event_inbox_config(project=root, config_path=path)
        return "inbox"
    if schema_version in COLLECTOR_SCHEMA_VERSIONS:
        load_lark_event_collector_config(project=root, config_path=path)
        return "collector"
    raise ValueError("Lark inbox config schema is unsupported")


def _collector_routes(
    *, project: str | Path, config_path: str | Path
) -> tuple[Path, list[dict[str, Any]]]:
    config = load_lark_event_collector_config(
        project=project,
        config_path=config_path,
    )
    return Path(config["project"]), list(config["routes"])


def inspect_routed_lark_event_inbox(
    *, project: str | Path, config_path: str | Path, limit: int = 20
) -> dict[str, Any]:
    """Drain one inbox or a collector's isolated route inboxes as one lane."""

    kind = lark_inbox_config_kind(project=project, config_path=config_path)
    if kind == "inbox":
        return inspect_lark_event_inbox(
            project=project,
            config_path=config_path,
            limit=limit,
        )
    root, routes = _collector_routes(project=project, config_path=config_path)
    items: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for route in routes:
        route_key = str(route["route_key"])
        status = inspect_lark_event_inbox(
            project=root,
            config_path=route["event_inbox_config_ref"],
            limit=100,
        )
        statuses.append(status)
        guidance = status.get("reply_guidance")
        for raw_item in status.get("items") or []:
            if isinstance(raw_item, Mapping):
                item = dict(raw_item)
                if item.get("route_key") != route_key:
                    raise ValueError(
                        "routed Lark inbox item route_key must match its configured route"
                    )
                if isinstance(guidance, Mapping):
                    item["reply_guidance"] = dict(guidance)
                items.append(item)
    items.sort(
        key=lambda item: (
            str(item.get("create_time") or ""),
            str(item.get("message_id") or ""),
        )
    )
    bounded = items[: max(1, min(int(limit), 100))]
    pending_count = sum(int(status.get("pending_count") or 0) for status in statuses)
    return {
        "ok": True,
        "schema_version": "lark_event_inbox_projection_v1",
        "enabled": all(status.get("enabled") is True for status in statuses),
        "configured": True,
        "capture_scope": "configured_chat_all",
        "thread_complete": all(
            status.get("thread_complete") is True for status in statuses
        ),
        "route_count": len(routes),
        "routes_with_pending_count": sum(
            int(status.get("pending_count") or 0) > 0 for status in statuses
        ),
        "pending_count": pending_count,
        "captured_count": sum(
            int(status.get("captured_count") or 0) for status in statuses
        ),
        "returned_count": len(bounded),
        "processed_count": sum(
            int(status.get("processed_count") or 0) for status in statuses
        ),
        "invalid_count": sum(
            int(status.get("invalid_count") or 0) for status in statuses
        ),
        "items": bounded,
        "local_private_content_returned": bool(bounded),
        "external_reads_performed": False,
        "chat_ids_returned": False,
        "route_keys_returned": bool(bounded),
        "profiles_returned": False,
        "instruction": (
            "Use each item's route_key to bind it to the stable requirement "
            "context, then process it through the same Agent lane. Message-scoped reply, "
            "reaction, and ACK commands resolve the unique routed inbox while "
            "preserving the item's source-context guidance."
        ),
    }


def project_routed_lark_event_inbox_urgency(
    *, project: str | Path, config_path: str | Path
) -> dict[str, Any]:
    """Aggregate route urgency without returning messages or route identities."""

    kind = lark_inbox_config_kind(project=project, config_path=config_path)
    if kind == "inbox":
        return project_lark_event_inbox_urgency(
            project=project,
            config_path=config_path,
        )
    root, routes = _collector_routes(project=project, config_path=config_path)
    projections = [
        project_lark_event_inbox_urgency(
            project=root,
            config_path=route["event_inbox_config_ref"],
        )
        for route in routes
    ]
    oldest_values = [
        str(projection.get("oldest_pending_at"))
        for projection in projections
        if projection.get("oldest_pending_at")
    ]
    age_values = [
        int(projection["oldest_pending_age_seconds"])
        for projection in projections
        if projection.get("oldest_pending_age_seconds") is not None
    ]
    count_fields = (
        "pending_count",
        "direct_question_count",
        "direct_mention_count",
        "reply_to_bot_count",
        "attention_required_count",
        "material_review_count",
        "material_attachment_count",
    )
    result: dict[str, Any] = {
        "schema_version": "lark_event_inbox_urgency_v1",
        "enabled": all(projection.get("enabled") is True for projection in projections),
        "thread_complete": all(
            projection.get("thread_complete") is True for projection in projections
        ),
        "route_count": len(routes),
        "routes_with_pending_count": sum(
            int(projection.get("pending_count") or 0) > 0 for projection in projections
        ),
        "oldest_pending_at": min(oldest_values) if oldest_values else None,
        "oldest_pending_age_seconds": max(age_values) if age_values else None,
        "reply_due": any(
            projection.get("reply_due") is True for projection in projections
        ),
        "material_review_due": any(
            projection.get("material_review_due") is True for projection in projections
        ),
        "material_review_drain_limit": min(
            (
                int(projection.get("material_review_drain_limit") or 20)
                for projection in projections
                if projection.get("material_review_due") is True
            ),
            default=20,
        ),
        "local_private_content_returned": False,
        "chat_ids_returned": False,
        "profiles_returned": False,
    }
    result.update(
        {
            field: sum(int(projection.get(field) or 0) for projection in projections)
            for field in count_fields
        }
    )
    return result


def settle_routed_lark_event_inbox_material_review(
    *,
    project: str | Path,
    config_path: str | Path,
    message_id: str,
    effect_receipt: Mapping[str, Any] | None = None,
    no_follow_up_reason: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Settle one material against the unique inbox that captured it."""

    routed_config = resolve_routed_lark_inbox_config(
        project=project,
        config_path=config_path,
        message_id=message_id,
    )
    return settle_lark_event_inbox_material_review(
        project=project,
        config_path=routed_config,
        message_id=message_id,
        effect_receipt=effect_receipt,
        no_follow_up_reason=no_follow_up_reason,
        execute=execute,
    )


def resolve_routed_lark_inbox_config(
    *,
    project: str | Path,
    config_path: str | Path,
    message_id: str,
) -> str:
    """Resolve one message to exactly one inbox without exposing route identity."""

    if not MESSAGE_ID_PATTERN.fullmatch(str(message_id or "").strip()):
        raise ValueError("routed Lark inbox lookup requires a valid message id")
    kind = lark_inbox_config_kind(project=project, config_path=config_path)
    if kind == "inbox":
        return str(config_path)
    _, routes = _collector_routes(project=project, config_path=config_path)
    matches: list[str] = []
    for route in routes:
        inbox_path = route["inbox"].get("inbox_path")
        if inbox_path is None:
            # A disabled route inbox has no addressable message store; it can
            # never contain the requested message and must fail closed cleanly
            # instead of raising on a None path.
            continue
        if (inbox_path / f"{message_id}.json").is_file():
            matches.append(str(route["event_inbox_config_ref"]))
    if len(matches) != 1:
        raise ValueError(
            "message id must resolve to exactly one configured Lark inbox route"
        )
    return matches[0]


def resolve_routed_lark_inbox_route(
    *,
    project: str | Path,
    config_path: str | Path,
    route_key: str | None,
) -> str:
    """Resolve one explicit top-level outbound route without exposing its target."""

    kind = lark_inbox_config_kind(project=project, config_path=config_path)
    requested = str(route_key or "").strip()
    if kind == "inbox":
        if requested not in {"", "default"}:
            raise ValueError("single Lark inbox accepts only the default route")
        return str(config_path)
    _, routes = _collector_routes(project=project, config_path=config_path)
    matches = [
        str(route["event_inbox_config_ref"])
        for route in routes
        if str(route["route_key"]) == requested
    ]
    if not requested or len(matches) != 1:
        raise ValueError(
            "routed Lark outbound send requires exactly one configured route_key"
        )
    return matches[0]


def acknowledge_routed_lark_event_inbox(
    *,
    project: str | Path,
    config_path: str | Path,
    message_ids: Sequence[str],
    execute: bool = False,
) -> dict[str, Any]:
    """ACK messages across isolated routes only after all routes resolve."""

    kind = lark_inbox_config_kind(project=project, config_path=config_path)
    if kind == "inbox":
        return acknowledge_lark_event_inbox(
            project=project,
            config_path=config_path,
            message_ids=message_ids,
            execute=execute,
        )
    grouped: dict[str, list[str]] = {}
    for message_id in message_ids:
        route_config = resolve_routed_lark_inbox_config(
            project=project,
            config_path=config_path,
            message_id=message_id,
        )
        grouped.setdefault(route_config, []).append(message_id)
    receipts = [
        acknowledge_lark_event_inbox(
            project=project,
            config_path=route_config,
            message_ids=values,
            execute=execute,
        )
        for route_config, values in grouped.items()
    ]
    return {
        "ok": all(receipt.get("ok") is True for receipt in receipts),
        "schema_version": "lark_event_inbox_ack_v1",
        "execute": execute,
        "requested_count": len(message_ids),
        "new_count": sum(int(receipt.get("new_count") or 0) for receipt in receipts),
        "already_acknowledged_count": sum(
            int(receipt.get("already_acknowledged_count") or 0) for receipt in receipts
        ),
        "write_performed": any(
            receipt.get("write_performed") is True for receipt in receipts
        ),
        "message_ids": list(message_ids),
        "route_count": len(grouped),
        "local_private_content_captured": False,
        "external_writes_performed": False,
        "chat_ids_returned": False,
        "profiles_returned": False,
    }


def ingest_routed_lark_event_inbox(
    *,
    project: str | Path,
    config_path: str | Path,
    events: Sequence[object],
    execute: bool = False,
) -> dict[str, Any]:
    """Backfill collector events by configured chat without cross-route fallback."""

    kind = lark_inbox_config_kind(project=project, config_path=config_path)
    if kind == "inbox":
        return ingest_lark_event_inbox(
            project=project,
            config_path=config_path,
            events=events,
            execute=execute,
        )
    _, routes = _collector_routes(project=project, config_path=config_path)
    by_chat = {str(route["chat_id"]): route for route in routes}
    grouped: dict[str, list[object]] = {}
    invalid_count = 0
    for event in events:
        chat_id = (
            str(event.get("chat_id") or "").strip()
            if isinstance(event, Mapping)
            else ""
        )
        route = by_chat.get(chat_id)
        if route is None:
            invalid_count += 1
            continue
        grouped.setdefault(str(route["event_inbox_config_ref"]), []).append(
            {**event, "route_key": route["route_key"]}
        )
    receipts = [
        ingest_lark_event_inbox(
            project=project,
            config_path=route_config,
            events=values,
            execute=execute,
        )
        for route_config, values in grouped.items()
    ]
    return {
        "ok": True,
        "schema_version": "lark_event_inbox_ingest_v1",
        "execute": execute,
        "requested_count": len(events),
        "accepted_count": sum(
            int(receipt.get("accepted_count") or 0) for receipt in receipts
        ),
        "invalid_count": invalid_count
        + sum(int(receipt.get("invalid_count") or 0) for receipt in receipts),
        "duplicate_count": sum(
            int(receipt.get("duplicate_count") or 0) for receipt in receipts
        ),
        "write_performed": any(
            receipt.get("write_performed") is True for receipt in receipts
        ),
        "route_count": len(grouped),
        "local_private_content_returned": False,
        "external_reads_performed": False,
        "external_writes_performed": False,
        "chat_ids_returned": False,
        "profiles_returned": False,
    }
