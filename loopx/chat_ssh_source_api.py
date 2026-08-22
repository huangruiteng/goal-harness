"""Loopback Chat API boundary for managed SSH status sources."""

from __future__ import annotations

from typing import Any

from .control_plane.status.ssh_tunnel import ensure_ssh_source
from .status_server import is_loopback_host


SSH_SOURCE_ENSURE_PATH = "/api/ssh-source/ensure"


class SshSourceRequestMixin:
    """Serve the owner-local SSH source ensure endpoint."""

    server: Any

    def _read_json(self) -> dict[str, Any]:
        raise NotImplementedError

    def _require_loopback_origin(self) -> bool:
        raise NotImplementedError

    def _send_error(self, message: str, **kwargs: Any) -> None:
        raise NotImplementedError

    def _send_json(self, payload: dict[str, object], *, status: int = 200) -> None:
        raise NotImplementedError

    def _ssh_source_ensure(self) -> None:
        if not is_loopback_host(str(self.server.server_address[0])):
            self._send_error(
                "SSH source management requires a loopback LoopX Chat server.",
                status=403,
            )
            return
        if not self._require_loopback_origin():
            return
        try:
            body = self._read_json()
            result = ensure_ssh_source(
                str(body.get("host_alias") or ""),
                body.get("local_port"),
                ssh_config_path=getattr(self.server, "ssh_config_path", None),
            )
        except (ValueError, TypeError) as exc:
            self._send_error(str(exc), status=400)
            return
        self._send_json(result)
