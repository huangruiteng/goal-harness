from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from threading import Thread
from typing import Iterator
import urllib.request
import urllib.error

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


def test_status_endpoint_forwards_goal_activation_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_collect_status(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"ok": True, "contract": {"ok": True}}

    monkeypatch.setattr("loopx.status_server.collect_status", fake_collect_status)

    with _status_server(tmp_path) as base_url:
        with urllib.request.urlopen(
            f"{base_url}{DEFAULT_STATUS_PATH}?goal_activation=active",
            timeout=5,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["ok"] is True
    assert calls[0]["activation_state_filter"] == "active"


def test_status_endpoint_rejects_unknown_goal_activation_scope(tmp_path: Path) -> None:
    with _status_server(tmp_path) as base_url:
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(
                f"{base_url}{DEFAULT_STATUS_PATH}?goal_activation=archived",
                timeout=5,
            )

    assert raised.value.code == 400
    payload = json.loads(raised.value.read().decode("utf-8"))
    assert payload["error"] == "goal_activation must be active or stopped"


def test_status_service_identity_is_public_and_versioned(tmp_path: Path) -> None:
    with _status_server(tmp_path) as base_url:
        with urllib.request.urlopen(base_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

    assert payload["source"] == "serve-status"
    assert payload["runtime_identity"]["schema_version"] == (
        "loopx_runtime_identity_v1"
    )
    assert set(payload["runtime_identity"]) == {
        "schema_version",
        "package_version",
        "release_id",
        "source_revision",
    }


def test_status_endpoint_rejects_blank_goal_activation_scope(tmp_path: Path) -> None:
    """A blank `?goal_activation=` value must fail closed with HTTP 400."""
    with _status_server(tmp_path) as base_url:
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(
                f"{base_url}{DEFAULT_STATUS_PATH}?goal_activation=",
                timeout=5,
            )

    assert raised.value.code == 400
    payload = json.loads(raised.value.read().decode("utf-8"))
    assert payload["error"] == "goal_activation must be active or stopped"


def test_status_endpoint_rejects_mixed_blank_goal_activation_scope(
    tmp_path: Path,
) -> None:
    """`?goal_activation=active&goal_activation=` must not collapse to one value."""
    with _status_server(tmp_path) as base_url:
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(
                f"{base_url}{DEFAULT_STATUS_PATH}?goal_activation=active&goal_activation=",
                timeout=5,
            )

    assert raised.value.code == 400
    payload = json.loads(raised.value.read().decode("utf-8"))
    assert payload["error"] == "goal_activation must be active or stopped"
