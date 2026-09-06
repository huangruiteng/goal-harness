"""Loopback status route owned by the Chat HTTP surface."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from .chat import redact_local_paths
from .chat_goal_subagent_api import goal_subagent_configuration_enabled
from .chat_workspace_directory import workspace_goal_directory
from .feedback import validate_goal_id
from .history import load_registry
from .registry import registry_goals
from .status import collect_status
from .status_server import parse_goal_activation_filter


class ChatStatusRequestMixin:
    """Serve the full dashboard status contract through the Chat origin."""

    server: Any

    def _send_error(self, message: str, **kwargs: Any) -> None:
        raise NotImplementedError

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        raise NotImplementedError

    def _status(self) -> None:
        query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        query_error_code = "invalid_goal_activation"
        try:
            activation_state_filter = parse_goal_activation_filter(query)
            query_error_code = "invalid_workspace_query"
            views = query.get("view")
            if views is not None and views != ["workspace-directory"]:
                raise ValueError("unsupported workspace status view")
            requested_goals = query.get("goal_id")
            goal_id = self.server.selected_goal_id
            if requested_goals is not None:
                if len(requested_goals) != 1 or not requested_goals[0].strip():
                    raise ValueError("one nonempty goal_id is required")
                requested_goal = requested_goals[0]
                validate_goal_id(requested_goal)
                if goal_id and requested_goal != goal_id:
                    raise ValueError("goal_id is outside this workspace")
                goal_id = requested_goal
        except ValueError as exc:
            self._send_error(
                str(exc),
                status=400,
                error_code=query_error_code,
            )
            return
        try:
            if views is not None or requested_goals is not None:
                registry = load_registry(self.server.registry_path)
                if goal_id and goal_id not in {
                    str(g.get("id")) for g in registry_goals(registry)
                }:
                    self._send_error("Goal is no longer registered.", status=404)
                    return
                directory = workspace_goal_directory(
                    registry, selected_goal_id=goal_id
                )
                if views is not None:
                    self._send_json(directory)
                    return
            projection = collect_status(
                registry_path=self.server.registry_path,
                runtime_root_override=self.server.runtime_root_override,
                scan_roots=self.server.scan_roots,
                limit=self.server.limit,
                goal_id=goal_id,
                include_public_boundary_scan=False,
                activation_state_filter=activation_state_filter,
                include_goal_subagent_configuration=(
                    goal_subagent_configuration_enabled(self.server)
                ),
            )
            if requested_goals is not None:
                latest = workspace_goal_directory(
                    load_registry(self.server.registry_path)
                )
                if latest["registry_revision"] != directory["registry_revision"]:
                    self._send_error(
                        "Goal directory changed; refresh the workspace.", status=409
                    )
                    return
                projection["workspace_registry_revision"] = directory[
                    "registry_revision"
                ]
            protected_paths = [self.server.registry_path, *self.server.scan_roots]
            projection = json.loads(
                redact_local_paths(
                    json.dumps(projection, ensure_ascii=False),
                    protected_paths=protected_paths,
                )
            )
        except Exception:  # noqa: BLE001 - do not expose local projection failures.
            self._send_error(
                "LoopX status could not be projected for the workspace.",
                status=500,
            )
            return
        self._send_json(projection)
