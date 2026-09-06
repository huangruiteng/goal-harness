"""Bounded, read-only history pages over the canonical Todo reader.

Snapshots keep concurrent completions from shifting page boundaries. They are
short-lived and server-local, never a second source of Todo authority.
"""
from collections import OrderedDict
import json
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs, urlparse


class CompletedTodoPages:
    page_size = 40
    max_snapshots = 8
    ttl_seconds = 300
    max_cache_bytes = 16 * 1024 * 1024

    def __init__(self):
        self._snapshots = OrderedDict()
        self._lock = Lock()

    def page(self, *, scope, cursor, load):
        with self._lock:
            now = monotonic()
            for key, (created, _, _, _) in list(self._snapshots.items()):
                if now - created >= self.ttl_seconds:
                    del self._snapshots[key]
            if cursor:
                try:
                    key, raw_offset = cursor.split(":")
                    offset = int(raw_offset)
                    _, saved_scope, rows, _ = self._snapshots[key]
                    if saved_scope != scope or offset < 0 or offset % self.page_size or offset >= len(rows):
                        raise ValueError()
                except (ValueError, KeyError):
                    raise ValueError("history_cursor_expired") from None
            else:
                rows = load()
                size = len(json.dumps(rows, ensure_ascii=False).encode("utf-8"))
                if size > self.max_cache_bytes:
                    raise ValueError("history_snapshot_too_large")
                key, offset = token_urlsafe(18), 0
                while self._snapshots and (len(self._snapshots) >= self.max_snapshots or sum(snapshot[3] for snapshot in self._snapshots.values()) + size > self.max_cache_bytes):
                    self._snapshots.popitem(last=False)
                self._snapshots[key] = (now, scope, rows, size)
            end = offset + self.page_size
            return {
                "ok": True,
                "items": rows[offset:end],
                "total": len(rows),
                "next_cursor": f"{key}:{end}" if end < len(rows) else None,
            }


class CompletedTodoRequestMixin:
    def _completed_todos(self) -> None:
        # This loopback-only workspace read preserves task text and evidence.
        # Select display fields without returning the authority's internal metadata.
        from .todos import list_goal_todos

        if not self._require_loopback_origin():
            return
        query = parse_qs(urlparse(self.path).query)
        goal_id = query.get("goal_id", [""])[0]
        agent_id = query.get("agent_id", [""])[0]
        cursor = query.get("cursor", [""])[0]
        try:
            self._registry_and_goal(goal_id)

            def load():
                payload = list_goal_todos(
                    registry_path=self.server.registry_path, goal_id=goal_id,
                    role="agent", status="done",
                    runtime_root_arg=self.server.runtime_root_override,
                )
                ordered = sorted(enumerate(payload["todos"]), key=lambda pair: (str(pair[1].get("completed_at") or ""), pair[0]), reverse=True)
                return [
                    {
                        "todo_id": item["todo_id"],
                        "text": str(item.get("text") or item.get("title") or ""),
                        "claimed_by": item.get("claimed_by"),
                        "evidence": item.get("evidence") or item.get("note") or None,
                        "priority": item.get("priority"),
                        "task_class": item.get("task_class"),
                    }
                    for _, item in ordered
                    if item.get("todo_id") and item.get("task_class") != "continuous_monitor"
                    and (not agent_id or item.get("claimed_by") == agent_id)
                ]

            self._send_json(self.server.completed_todo_pages.page(
                scope=(goal_id, agent_id), cursor=cursor, load=load,
            ))
        except ValueError as exc:
            expired = str(exc) == "history_cursor_expired"
            self._send_error("history_cursor_expired" if expired else "Completed history is unavailable for this Goal.", status=409 if expired else 400)
        except (OSError, RuntimeError):
            self._send_error("Completed history could not be loaded.", status=503)
