"""Loopback status route owned by the Chat HTTP surface."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from .chat import redact_local_paths
from .status import collect_status
from .status_server import parse_goal_activation_filter


class ChatStatusRequestMixin:
    """Serve the full dashboard status contract through the Chat origin."""

    def _status(self) -> None:
        query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        try:
            activation_state_filter = parse_goal_activation_filter(query)
        except ValueError as exc:
            self._send_error(
                str(exc),
                status=400,
                error_code="invalid_goal_activation",
            )
            return
        try:
            projection = collect_status(
                registry_path=self.server.registry_path,
                runtime_root_override=self.server.runtime_root_override,
                scan_roots=self.server.scan_roots,
                limit=self.server.limit,
                goal_id=self.server.selected_goal_id,
                include_public_boundary_scan=False,
                activation_state_filter=activation_state_filter,
            )
            projection = json.loads(
                redact_local_paths(
                    json.dumps(projection, ensure_ascii=False),
                    protected_paths=[self.server.registry_path, *self.server.scan_roots],
                )
            )
        except Exception:  # noqa: BLE001 - do not expose local projection failures.
            self._send_error(
                "LoopX status could not be projected for the workspace.",
                status=500,
            )
            return
        self._send_json(projection)
