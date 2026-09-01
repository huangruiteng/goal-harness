from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest

from loopx.feedback import append_human_reward, validate_goal_id
from loopx.status_server import (
    StatusHTTPServer,
    StatusRequestHandler,
)


@pytest.mark.parametrize(
    "goal_id",
    ["loopx-meta", "example.goal_1", "goal-42", "ABC_xyz"],
)
def test_validate_goal_id_accepts_safe_ids(goal_id: str) -> None:
    assert validate_goal_id(goal_id) == goal_id


@pytest.mark.parametrize(
    "goal_id",
    ["", "../evil", "a/b", "a\\b", "..", "a b", "a;b", "a|b", "a$b"],
)
def test_validate_goal_id_rejects_unsafe_ids(goal_id: str) -> None:
    with pytest.raises(ValueError, match="invalid goal_id"):
        validate_goal_id(goal_id)


def test_validate_goal_id_rejects_absolute_path_segment() -> None:
    # Relative traversal is covered above; absolute paths must also fail closed
    # before any runtime goals/{goal_id}/ path join.
    with pytest.raises(ValueError, match="invalid goal_id"):
        validate_goal_id("/etc/passwd")


def test_append_human_reward_rejects_traversal_before_any_io(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid goal_id"):
        append_human_reward(
            registry_path=tmp_path / "missing-registry.json",
            runtime_root_override=None,
            goal_id="../../etc/passwd",
            run_generated_at=None,
            reward={"decision": "positive", "reason_summary": "x"},
            dry_run=True,
        )


def _start_server() -> tuple[StatusHTTPServer, threading.Thread]:
    server = StatusHTTPServer(("127.0.0.1", 0), StatusRequestHandler)
    server.verbose = False
    server.registry_path = Path("/nonexistent")
    server.runtime_root_override = None
    server.scan_roots = []
    server.limit = 10
    server.status_path = "/status.json"
    server.reward_dry_run_path = "/reward/dry-run"
    server.reward_append_path = "/reward/append"
    server.reward_write_enabled = False
    server.configure_goal_dry_run_path = "/configure-goal/dry-run"
    server.configure_goal_apply_path = "/configure-goal/apply"
    server.control_plane_write_enabled = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _post(
    port: int,
    path: str,
    body: dict[str, object],
) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(
        "POST",
        path,
        body=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    return conn.getresponse()


def test_reward_dry_run_rejects_traversal_goal_id() -> None:
    server, thread = _start_server()
    try:
        response = _post(
            server.server_address[1],
            "/reward/dry-run",
            {
                "goal_id": "../../etc/passwd",
                "run_generated_at": "2026-08-12T00:00:00Z",
                "decision": "positive",
                "reward": "good",
                "reason_summary": "works",
            },
        )
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 400
        assert payload["ok"] is False
        assert "invalid goal_id" in payload["error"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_configure_goal_dry_run_rejects_traversal_goal_id() -> None:
    server, thread = _start_server()
    try:
        response = _post(
            server.server_address[1],
            "/configure-goal/dry-run",
            {"goal_id": "..%2F..%2Fetc"},
        )
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 400
        assert "invalid goal_id" in payload["error"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
