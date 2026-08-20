"""Loopback API mixin for binding already-running Agent sessions."""

from __future__ import annotations

from typing import Any

from .attached_session import bind_attached_agent_session


def _compact_id(value: Any, *, limit: int = 160) -> str:
    text = str(value or "").strip()
    if len(text) > limit or any(ord(character) < 32 for character in text):
        raise ValueError("attached session field must be a bounded opaque string")
    return text


class AttachedSessionRequestMixin:
    """Serve the owner-local attached Session binding endpoint."""

    server: Any

    def _read_json(self) -> dict[str, Any]:
        raise NotImplementedError

    def _registry_and_goal(
        self,
        goal_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raise NotImplementedError

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        raise NotImplementedError

    def _send_error(self, message: str, **kwargs: Any) -> None:
        raise NotImplementedError

    def _attach_session(self) -> None:
        try:
            body = self._read_json()
            allowed = {
                "goal_id",
                "agent_id",
                "host_surface",
                "host_session_id",
                "executor_endpoint_id",
                "channel_id",
            }
            if set(body) - allowed:
                raise ValueError("unknown attached session field")
            required = {
                key: _compact_id(body.get(key))
                for key in (
                    "goal_id",
                    "agent_id",
                    "host_surface",
                    "host_session_id",
                    "executor_endpoint_id",
                )
            }
            missing = [key for key, value in required.items() if not value]
            if missing:
                raise ValueError(f"missing attached session fields: {', '.join(missing)}")
            registry, _goal = self._registry_and_goal(required["goal_id"])
            packet = bind_attached_agent_session(
                store=self.server.chat_store,
                registry=registry,
                goal_id=required["goal_id"],
                agent_id=required["agent_id"],
                host_surface=required["host_surface"],
                host_session_id=required["host_session_id"],
                executor_endpoint_id=required["executor_endpoint_id"],
                channel_id=_compact_id(body.get("channel_id")) or None,
                execute=True,
            )
        except Exception as exc:  # noqa: BLE001 - compact loopback validation error.
            self._send_error(str(exc))
            return
        self._send_json(packet, status=201 if packet.get("created") else 200)
