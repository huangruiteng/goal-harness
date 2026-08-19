"""Owner-local durable state for LoopX Chat sessions and turns."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import threading
from typing import Any
import uuid

from .file_lock import exclusive_file_lock


CHAT_STORE_SCHEMA_VERSION = "loopx_chat_store_v1"
CHAT_SESSION_SCHEMA_VERSION = "loopx_chat_session_state_v1"
CHAT_TURN_SCHEMA_VERSION = "loopx_chat_turn_state_v1"
CHAT_EVENT_SCHEMA_VERSION = "loopx_chat_event_v1"
CHAT_MESSAGE_SCHEMA_VERSION = "loopx_chat_message_v1"
RESUMABLE_SESSION_STATES = {"ready", "busy", "stale", "resuming"}

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _opaque_id(value: Any, *, field: str) -> str:
    token = str(value or "").strip()
    if not _OPAQUE_ID.fullmatch(token):
        raise ValueError(f"{field} must be a compact opaque id")
    return token


def _upstream_id(value: Any) -> str:
    token = str(value or "").strip()
    if not token or len(token) > 1024 or any(ord(character) < 32 for character in token):
        raise ValueError("upstream_thread_id must be a bounded opaque string")
    return token


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _session_channel(payload: dict[str, Any]) -> str:
    channel_id = str(payload.get("channel_id") or "").strip()
    if channel_id:
        return channel_id
    return f"goal.{payload.get('goal_id')}"


def _atomic_write_json(path: Path, payload: dict[str, Any], *, preserve_mode: bool = False) -> None:
    previous_mode = path.stat().st_mode & 0o777 if preserve_mode and path.exists() else 0o600
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, previous_mode)
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    _append_jsonl_rows(path, [payload])


def _append_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a", encoding="utf-8") as handle:
        for payload in rows:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def _replace_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


class ChatSessionStore:
    """Filesystem store kept outside project and public LoopX run history."""

    def __init__(self, runtime_root: Path) -> None:
        self.root = runtime_root.expanduser().resolve() / "chat"
        self.sessions_root = self.root / "sessions"
        self._event_lock = threading.RLock()
        self._event_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._event_pending: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._event_flush_locks: dict[tuple[str, str], threading.Lock] = {}
        self.sessions_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        os.chmod(self.sessions_root, 0o700)
        self.compact_completed_events()

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_root / _opaque_id(session_id, field="session_id")

    def _session_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session.json"

    def _turn_path(self, session_id: str, turn_id: str) -> Path:
        return self._session_dir(session_id) / "turns" / f"{_opaque_id(turn_id, field='turn_id')}.json"

    def _event_path(self, session_id: str, turn_id: str) -> Path:
        return self._session_dir(session_id) / "turns" / f"{_opaque_id(turn_id, field='turn_id')}.events.jsonl"

    def create_session(
        self,
        *,
        goal_id: str,
        agent_id: str,
        adapter_kind: str,
        upstream_thread_id: str,
        upstream_mode: str = "default",
        channel_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        token = _opaque_id(session_id or uuid.uuid4().hex, field="session_id")
        session_dir = self._session_dir(token)
        session_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        (session_dir / "turns").mkdir(mode=0o700)
        payload = {
            "schema_version": CHAT_SESSION_SCHEMA_VERSION,
            "session_id": token,
            "goal_id": _opaque_id(goal_id, field="goal_id"),
            "agent_id": _opaque_id(agent_id, field="agent_id"),
            "adapter_kind": _opaque_id(adapter_kind, field="adapter_kind"),
            "upstream_thread_id": _upstream_id(upstream_thread_id),
            "upstream_mode": _opaque_id(upstream_mode, field="upstream_mode"),
            "channel_id": _opaque_id(channel_id or f"goal.{goal_id}", field="channel_id"),
            "status": "ready",
            "active_turn_id": None,
            "last_error_code": None,
            "created_at": now,
            "updated_at": now,
            "last_activity_at": now,
        }
        _atomic_write_json(self._session_path(token), payload)
        os.chmod(self._session_path(token), 0o600)
        return payload

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        payload = _read_json(self._session_path(session_id))
        return payload if payload.get("schema_version") == CHAT_SESSION_SCHEMA_VERSION else None

    def update_session(self, session_id: str, **changes: Any) -> dict[str, Any]:
        path = self._session_path(session_id)
        with exclusive_file_lock(path, agent_id="loopx-chat", operation="update_chat_session"):
            payload = self.load_session(session_id)
            if payload is None:
                raise KeyError("chat session was not found")
            allowed = {
                "status",
                "active_turn_id",
                "last_activity_at",
                "last_error_code",
                "upstream_thread_id",
                "upstream_mode",
            }
            unknown = set(changes) - allowed
            if unknown:
                raise ValueError(f"unsupported chat session fields: {sorted(unknown)}")
            if "upstream_thread_id" in changes:
                changes["upstream_thread_id"] = _upstream_id(changes["upstream_thread_id"])
            if "upstream_mode" in changes:
                changes["upstream_mode"] = _opaque_id(changes["upstream_mode"], field="upstream_mode")
            payload.update(changes)
            payload["updated_at"] = utc_now()
            _atomic_write_json(path, payload, preserve_mode=True)
            return payload

    def latest_session(
        self,
        *,
        goal_id: str | None,
        agent_id: str,
        channel_id: str | None = None,
    ) -> dict[str, Any] | None:
        if goal_id is None and channel_id is None:
            raise ValueError("channel_id is required when goal_id is omitted")
        selected_channel = channel_id or f"goal.{goal_id}"
        candidates: list[dict[str, Any]] = []
        for path in self.sessions_root.glob("*/session.json"):
            payload = _read_json(path)
            if (
                payload.get("schema_version") == CHAT_SESSION_SCHEMA_VERSION
                and (goal_id is None or payload.get("goal_id") == goal_id)
                and payload.get("agent_id") == agent_id
                and payload.get("status") in RESUMABLE_SESSION_STATES
                and _session_channel(payload) == selected_channel
            ):
                candidates.append(payload)
        return max(candidates, key=lambda item: str(item.get("updated_at") or ""), default=None)

    def list_sessions(
        self,
        *,
        goal_id: str | None = None,
        agent_id: str | None = None,
        channel_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.sessions_root.glob("*/session.json"):
            payload = _read_json(path)
            if payload.get("schema_version") != CHAT_SESSION_SCHEMA_VERSION:
                continue
            if goal_id and payload.get("goal_id") != goal_id:
                continue
            if agent_id and payload.get("agent_id") != agent_id:
                continue
            if channel_id and _session_channel(payload) != channel_id:
                continue
            rows.append(self.public_session(payload))
        return sorted(rows, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        text: str,
        turn_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        session_dir = self._session_dir(session_id)
        path = session_dir / "messages.jsonl"
        payload = {
            "schema_version": CHAT_MESSAGE_SCHEMA_VERSION,
            "message_id": uuid.uuid4().hex,
            "turn_id": _opaque_id(turn_id, field="turn_id") if turn_id else None,
            "role": role,
            "text": str(text),
            **({"attachments": attachments} if attachments else {}),
            "created_at": utc_now(),
        }
        with exclusive_file_lock(path, agent_id="loopx-chat", operation="append_chat_message"):
            _append_jsonl(path, payload)
        return payload

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        return _read_jsonl(self._session_dir(session_id) / "messages.jsonl")

    def create_turn(
        self,
        session_id: str,
        *,
        client_turn_id: str,
        message: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        client_id = _opaque_id(client_turn_id, field="client_turn_id")
        existing = self.turn_for_client(session_id, client_id)
        if existing is not None:
            return existing, False
        session = self.load_session(session_id)
        if session is None:
            raise KeyError("chat session was not found")
        active_turn_id = session.get("active_turn_id")
        if active_turn_id:
            active = self.load_turn(session_id, str(active_turn_id))
            if active and active.get("status") in {"queued", "starting", "running", "interrupting"}:
                raise RuntimeError(str(active_turn_id))
        now = utc_now()
        turn_id = uuid.uuid4().hex
        payload = {
            "schema_version": CHAT_TURN_SCHEMA_VERSION,
            "turn_id": turn_id,
            "session_id": session_id,
            "client_turn_id": client_id,
            "status": "queued",
            "message": str(message),
            "upstream_turn_id": None,
            "response": None,
            "error_code": None,
            "error": None,
            "created_at": now,
            "started_at": None,
            "first_event_at": None,
            "completed_at": None,
            "last_activity_at": now,
            "delta_count": 0,
            "sse_reconnect_count": 0,
        }
        path = self._turn_path(session_id, turn_id)
        _atomic_write_json(path, payload)
        os.chmod(path, 0o600)
        self.update_session(session_id, status="busy", active_turn_id=turn_id, last_activity_at=now)
        self.append_message(
            session_id,
            role="user",
            text=message,
            turn_id=turn_id,
            attachments=attachments,
        )
        self.append_event(session_id, turn_id, kind="turn.queued", payload={})
        return payload, True

    def turn_for_client(self, session_id: str, client_turn_id: str) -> dict[str, Any] | None:
        turns_dir = self._session_dir(session_id) / "turns"
        for path in turns_dir.glob("*.json") if turns_dir.is_dir() else []:
            if path.name.endswith(".events.json"):
                continue
            payload = _read_json(path)
            if payload.get("client_turn_id") == client_turn_id:
                return payload
        return None

    def load_turn(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        payload = _read_json(self._turn_path(session_id, turn_id))
        return payload if payload.get("schema_version") == CHAT_TURN_SCHEMA_VERSION else None

    def update_turn(self, session_id: str, turn_id: str, **changes: Any) -> dict[str, Any]:
        path = self._turn_path(session_id, turn_id)
        with exclusive_file_lock(path, agent_id="loopx-chat", operation="update_chat_turn"):
            payload = self.load_turn(session_id, turn_id)
            if payload is None:
                raise KeyError("chat turn was not found")
            allowed = {
                "status", "upstream_turn_id", "response", "error_code", "error",
                "started_at", "first_event_at", "completed_at", "last_activity_at",
                "delta_count", "sse_reconnect_count",
            }
            unknown = set(changes) - allowed
            if unknown:
                raise ValueError(f"unsupported chat turn fields: {sorted(unknown)}")
            payload.update(changes)
            _atomic_write_json(path, payload, preserve_mode=True)
            return payload

    def _event_rows_locked(self, session_id: str, turn_id: str) -> list[dict[str, Any]]:
        key = (session_id, turn_id)
        rows = self._event_cache.get(key)
        if rows is None:
            rows = _read_jsonl(self._event_path(session_id, turn_id))
            self._event_cache[key] = rows
        return rows

    def _event_flush_lock(self, key: tuple[str, str]) -> threading.Lock:
        with self._event_lock:
            return self._event_flush_locks.setdefault(key, threading.Lock())

    def append_event(
        self,
        session_id: str,
        turn_id: str,
        *,
        kind: str,
        payload: dict[str, Any],
        buffered: bool = False,
    ) -> dict[str, Any]:
        key = (session_id, turn_id)
        with self._event_lock:
            rows = self._event_rows_locked(session_id, turn_id)
            sequence = int(rows[-1].get("sequence") or 0) + 1 if rows else 1
            event = {
                "schema_version": CHAT_EVENT_SCHEMA_VERSION,
                "event_id": str(sequence),
                "sequence": sequence,
                "kind": str(kind),
                "created_at": utc_now(),
                "payload": payload,
            }
            rows.append(event)
            self._event_pending.setdefault(key, []).append(event)
        if not buffered:
            self.flush_events(session_id, turn_id)
        return event

    def flush_events(self, session_id: str, turn_id: str) -> int:
        """Persist queued events in one ordered append and one data fsync."""
        key = (session_id, turn_id)
        path = self._event_path(session_id, turn_id)
        flush_lock = self._event_flush_lock(key)
        flushed = 0
        with flush_lock:
            while True:
                with self._event_lock:
                    pending = self._event_pending.pop(key, [])
                if not pending:
                    return flushed
                try:
                    with exclusive_file_lock(path, agent_id="loopx-chat", operation="append_chat_events"):
                        _append_jsonl_rows(path, pending)
                except Exception:
                    with self._event_lock:
                        later = self._event_pending.get(key, [])
                        self._event_pending[key] = [*pending, *later]
                    raise
                flushed += len(pending)

    def events_after(self, session_id: str, turn_id: str, event_id: str | None) -> list[dict[str, Any]]:
        try:
            after = int(event_id or 0)
        except ValueError:
            after = 0
        with self._event_lock:
            rows = list(self._event_rows_locked(session_id, turn_id))
        return [row for row in rows if int(row.get("sequence") or 0) > after]

    def compact_completed_events(self, *, older_than_hours: float = 24.0) -> int:
        """Drop replay-only deltas after the durable final message is old enough."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0.0, older_than_hours))
        compacted = 0
        for turn_path in self.sessions_root.glob("*/turns/*.json"):
            turn = _read_json(turn_path)
            if turn.get("status") not in {"completed", "interrupted", "timed_out", "failed"}:
                continue
            completed_at = str(turn.get("completed_at") or "")
            try:
                completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if completed > cutoff:
                continue
            session_id = turn_path.parent.parent.name
            turn_id = turn_path.stem
            self.flush_events(session_id, turn_id)
            event_path = turn_path.with_name(f"{turn_path.stem}.events.jsonl")
            with self._event_lock:
                rows = list(self._event_rows_locked(session_id, turn_id))
            retained = [
                row for row in rows
                if row.get("kind") not in {
                    "answer.delta",
                    "assistant.delta",
                    "agent.phase",
                    "turn.activity",
                }
            ]
            if len(retained) == len(rows):
                continue
            with exclusive_file_lock(event_path, agent_id="loopx-chat", operation="compact_chat_events"):
                _replace_jsonl(event_path, retained)
            with self._event_lock:
                self._event_cache[(session_id, turn_id)] = retained
            compacted += 1
        return compacted

    def public_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            key: payload.get(key)
            for key in (
                "session_id", "goal_id", "agent_id", "adapter_kind", "status",
                "active_turn_id", "last_error_code", "created_at", "updated_at", "last_activity_at",
            )
        } | {
            "channel_id": _session_channel(payload),
            "resumable": bool(payload.get("upstream_thread_id"))
            and payload.get("status") in RESUMABLE_SESSION_STATES,
        }

    def session_snapshot(self, session_id: str) -> dict[str, Any]:
        payload = self.load_session(session_id)
        if payload is None:
            raise KeyError("chat session was not found")
        active_turn = None
        if payload.get("active_turn_id"):
            active_turn = self.load_turn(session_id, str(payload["active_turn_id"]))
        return {
            "ok": True,
            "schema_version": CHAT_STORE_SCHEMA_VERSION,
            "session": self.public_session(payload),
            "messages": self.messages(session_id),
            "active_turn": active_turn,
        }
