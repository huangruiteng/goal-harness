from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from threading import Thread
from typing import Iterator
import urllib.request

import pytest

from loopx.status_server import (
    DEFAULT_CONFIGURE_GOAL_APPLY_PATH,
    DEFAULT_CONFIGURE_GOAL_DRY_RUN_PATH,
    DEFAULT_REWARD_APPEND_PATH,
    DEFAULT_REWARD_DRY_RUN_PATH,
    DEFAULT_STATUS_PATH,
    StatusHTTPServer,
    StatusRequestHandler,
)


@contextmanager
def _status_server(tmp_path: Path) -> Iterator[str]:
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"goals": []}) + "\n", encoding="utf-8")
    server = StatusHTTPServer(("127.0.0.1", 0), StatusRequestHandler)
    server.registry_path = registry
    server.runtime_root_override = None
    server.scan_roots = [tmp_path]
    server.limit = 80
    server.status_path = DEFAULT_STATUS_PATH
    server.reward_dry_run_path = DEFAULT_REWARD_DRY_RUN_PATH
    server.reward_append_path = DEFAULT_REWARD_APPEND_PATH
    server.reward_write_enabled = False
    server.configure_goal_dry_run_path = DEFAULT_CONFIGURE_GOAL_DRY_RUN_PATH
    server.configure_goal_apply_path = DEFAULT_CONFIGURE_GOAL_APPLY_PATH
    server.control_plane_write_enabled = False
    server.verbose = False
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_status_endpoint_defers_repository_boundary_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_collect_status(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"ok": True, "contract": {"ok": True}}

    monkeypatch.setattr("loopx.status_server.collect_status", fake_collect_status)

    with _status_server(tmp_path) as base_url:
        with urllib.request.urlopen(f"{base_url}{DEFAULT_STATUS_PATH}", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["ok"] is True
    assert len(calls) == 1
    assert calls[0]["include_public_boundary_scan"] is False
