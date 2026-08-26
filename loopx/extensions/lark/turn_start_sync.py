"""Bounded incremental Lark history sync for the LoopX turn-start hook."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...file_lock import (
    LockAcquireTimeoutError,
    LockAcquisitionPolicy,
    exclusive_file_lock,
)
from .event_collector import _executable_prefix, load_lark_event_collector_config
from .group_history import (
    _canonical_events,
    _page_digest,
    _provider_argv,
    _provider_failure,
    _provider_page,
    _route_context,
    _verify_inbox_events,
)
from .routed_inbox import ingest_routed_lark_event_inbox

CURSOR_SCHEMA_VERSION = "lark_turn_start_sync_cursor_v0"
SYNC_SCHEMA_VERSION = "lark_turn_start_inbox_sync_v0"
Runner = Callable[..., subprocess.CompletedProcess[str]]
SOURCE_FINGERPRINT_PATTERN = re.compile(r"^sha256:([0-9a-f]{24})$")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _cursor_path(project: Path, *, route_key: str, source_fingerprint: str) -> Path:
    match = SOURCE_FINGERPRINT_PATTERN.fullmatch(source_fingerprint)
    if match is None:
        raise ValueError("Lark turn-start sync source fingerprint is invalid")
    return (
        project
        / ".loopx"
        / "inbox"
        / ".turn-start"
        / route_key
        / f"{match.group(1)}.json"
    )


def _load_cursor(
    path: Path, *, route_key: str, source_fingerprint: str
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Lark turn-start sync cursor is unreadable") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != (
        CURSOR_SCHEMA_VERSION
    ):
        raise ValueError("Lark turn-start sync cursor schema is invalid")
    if payload.get("route_key") != route_key:
        raise ValueError("Lark turn-start sync cursor route binding changed")
    if payload.get("source_fingerprint") != source_fingerprint:
        raise ValueError("Lark turn-start sync cursor source binding changed")
    for field in ("window_start", "window_end"):
        value = payload.get(field)
        if not isinstance(value, str):
            raise TypeError("Lark turn-start sync cursor window is invalid")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Lark turn-start sync cursor window is invalid") from exc
        if parsed.tzinfo is None:
            raise ValueError("Lark turn-start sync cursor window is invalid")
    next_page_token = payload.get("next_page_token")
    if next_page_token is not None and (
        not isinstance(next_page_token, str) or not next_page_token.strip()
    ):
        raise ValueError("Lark turn-start sync cursor page token is invalid")
    page_count = payload.get("page_count")
    message_count = payload.get("message_count")
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count < 1
        or isinstance(message_count, bool)
        or not isinstance(message_count, int)
        or message_count < 0
    ):
        raise ValueError("Lark turn-start sync cursor counters are invalid")
    return dict(payload)


def _write_cursor(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _window_state(
    existing: Mapping[str, Any] | None,
    *,
    route_key: str,
    source_fingerprint: str,
    now: datetime,
    initial_lookback_seconds: int,
    overlap_seconds: int,
) -> tuple[dict[str, Any], str]:
    if existing and existing.get("next_page_token"):
        return dict(existing), "page_resumed"
    end = now.astimezone(UTC)
    if existing:
        prior_end = datetime.fromisoformat(str(existing["window_end"])).astimezone(UTC)
        if end <= prior_end:
            end = prior_end + timedelta(microseconds=1)
        start = prior_end - timedelta(seconds=overlap_seconds)
        transition = "tail_advanced"
    else:
        start = end - timedelta(seconds=initial_lookback_seconds)
        transition = "initialized"
    return (
        {
            "schema_version": CURSOR_SCHEMA_VERSION,
            "route_key": route_key,
            "source_fingerprint": source_fingerprint,
            "window_start": _timestamp(start),
            "window_end": _timestamp(end),
            "next_page_token": None,
            "page_count": 0,
            "message_count": 0,
            "last_page_digest": "",
        },
        transition,
    )


def _route_receipt(
    *,
    project: str | Path,
    config_path: str | Path,
    route_key: str,
    now: datetime,
    initial_lookback_seconds: int,
    overlap_seconds: int,
    page_size: int,
    lark_cli_executable: str,
    runner: Runner,
) -> dict[str, Any]:
    config, route, _, source_fingerprint = _route_context(
        project=project,
        config_path=config_path,
        route_key=route_key,
    )
    cursor_path = _cursor_path(
        Path(config["project"]),
        route_key=route_key,
        source_fingerprint=source_fingerprint,
    )
    try:
        lock = exclusive_file_lock(
            cursor_path,
            policy=LockAcquisitionPolicy.SINGLE_FLIGHT,
            operation="lark_turn_start_sync",
        )
        with lock:
            existing = _load_cursor(
                cursor_path,
                route_key=route_key,
                source_fingerprint=source_fingerprint,
            )
            state, _transition = _window_state(
                existing,
                route_key=route_key,
                source_fingerprint=source_fingerprint,
                now=now,
                initial_lookback_seconds=initial_lookback_seconds,
                overlap_seconds=overlap_seconds,
            )
            argv = _provider_argv(
                command_prefix=_executable_prefix(lark_cli_executable),
                profile=str(config["profile"]),
                chat_id=str(route["chat_id"]),
                state=state,
                page_size=page_size,
            )
            try:
                provider = runner(
                    argv,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError):
                return {
                    "ok": False,
                    "status": "provider_unavailable",
                    "error_code": "provider_unavailable",
                    "external_read_performed": False,
                    "local_private_state_mutated": False,
                }
            if provider.returncode != 0:
                failed = _provider_failure(provider, route_key=route_key)
                return {
                    "ok": False,
                    "status": str(failed["status"]),
                    "error_code": str(failed["status"]),
                    "external_read_performed": bool(failed["external_read_performed"]),
                    "local_private_state_mutated": False,
                }
            try:
                payload = json.loads(provider.stdout)
                messages, has_more, next_page_token = _provider_page(payload)
                events, skipped_count, invalid_count = _canonical_events(
                    messages,
                    chat_id=str(route["chat_id"]),
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                return {
                    "ok": False,
                    "status": "provider_contract_error",
                    "error_code": "provider_contract_error",
                    "external_read_performed": True,
                    "local_private_state_mutated": False,
                }
            if invalid_count:
                return {
                    "ok": False,
                    "status": "provider_contract_error",
                    "error_code": "provider_contract_error",
                    "external_read_performed": True,
                    "local_private_state_mutated": False,
                }
            newly_missing = [
                event
                for event in events
                if not (
                    route["inbox"]["inbox_path"] / f"{event['message_id']}.json"
                ).is_file()
            ]
            ingest = ingest_routed_lark_event_inbox(
                project=config["project"],
                config_path=config["config_path"],
                events=events,
                execute=True,
            )
            try:
                verified_count = _verify_inbox_events(route, newly_missing)
            except ValueError:
                return {
                    "ok": False,
                    "status": "inbox_readback_failed",
                    "error_code": "inbox_readback_failed",
                    "external_read_performed": True,
                    "local_private_state_mutated": bool(ingest["write_performed"]),
                }
            updated = {
                **state,
                "next_page_token": next_page_token,
                "page_count": int(state["page_count"]) + 1,
                "message_count": int(state["message_count"]) + len(events),
                "last_page_digest": _page_digest(events, next_page_token),
            }
            try:
                _write_cursor(cursor_path, updated)
                readback = _load_cursor(
                    cursor_path,
                    route_key=route_key,
                    source_fingerprint=source_fingerprint,
                )
                if readback != updated:
                    raise ValueError("Lark turn-start sync cursor readback mismatch")
            except (OSError, TypeError, ValueError):
                return {
                    "ok": False,
                    "status": "cursor_readback_failed",
                    "error_code": "cursor_readback_failed",
                    "accepted_count": int(ingest["accepted_count"]),
                    "external_read_performed": True,
                    "local_private_state_mutated": bool(ingest["write_performed"]),
                }
            return {
                "ok": True,
                "status": "page_pending" if has_more else "synced",
                "error_code": None,
                "accepted_count": int(ingest["accepted_count"]),
                "duplicate_count": int(ingest["duplicate_count"]),
                "skipped_count": skipped_count,
                "verified_count": verified_count,
                "external_read_performed": True,
                "local_private_state_mutated": True,
            }
    except LockAcquireTimeoutError:
        return {
            "ok": False,
            "status": "sync_already_running",
            "error_code": "sync_already_running",
            "external_read_performed": False,
            "local_private_state_mutated": False,
        }


def sync_lark_turn_start_inbox(
    *,
    project: str | Path,
    config_path: str | Path,
    lark_cli_executable: str = "lark-cli",
    runner: Runner = subprocess.run,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Sync one bounded page per configured route and return a content-free receipt."""

    config = load_lark_event_collector_config(
        project=project,
        config_path=config_path,
    )
    policy = config["turn_start_sync"]
    if policy["enabled"] is not True:
        return {
            "ok": True,
            "schema_version": SYNC_SCHEMA_VERSION,
            "status": "not_applicable",
            "observation_count": 0,
            "agent_read_required": False,
            "external_reads_performed": False,
            "local_private_state_mutated": False,
            "error_code": None,
            "private_content_returned": False,
            "provider_payload_returned": False,
        }
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    receipts = [
        _route_receipt(
            project=project,
            config_path=config_path,
            route_key=str(route["route_key"]),
            now=observed_at,
            initial_lookback_seconds=int(policy["initial_lookback_seconds"]),
            overlap_seconds=int(policy["overlap_seconds"]),
            page_size=int(policy["page_size"]),
            lark_cli_executable=lark_cli_executable,
            runner=runner,
        )
        for route in config["routes"]
    ]
    failures = [receipt for receipt in receipts if receipt["ok"] is not True]
    observation_count = sum(
        int(receipt.get("accepted_count") or 0) for receipt in receipts
    )
    if failures and observation_count:
        status = "partial"
        error_code = "route_sync_partial"
    elif failures and len(failures) == len(receipts):
        status = "unavailable"
        error_code = str(failures[0]["error_code"])
    elif failures:
        status = "partial"
        error_code = "route_sync_partial"
    elif observation_count:
        status = "observed"
        error_code = None
    else:
        status = "empty"
        error_code = None
    return {
        "ok": not failures,
        "schema_version": SYNC_SCHEMA_VERSION,
        "status": status,
        "observation_count": observation_count,
        "agent_read_required": bool(observation_count),
        "external_reads_performed": any(
            receipt.get("external_read_performed") is True for receipt in receipts
        ),
        "local_private_state_mutated": any(
            receipt.get("local_private_state_mutated") is True for receipt in receipts
        ),
        "error_code": error_code,
        "private_content_returned": False,
        "provider_payload_returned": False,
    }
