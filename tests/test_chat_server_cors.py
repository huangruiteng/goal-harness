from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

from loopx.chat_server import ChatHTTPServer, ChatRequestHandler
from loopx.extensions.lark.cli_resolution import LarkCliResolution


def _start_server() -> tuple[ChatHTTPServer, threading.Thread]:
    server = ChatHTTPServer(("127.0.0.1", 0), ChatRequestHandler)
    server.verbose = False
    server.selected_goal_id = None
    server.registry_path = Path("/tmp/loopx-test-registry.json")
    server.runtime_root_override = None
    server.scan_roots = []
    server.limit = 20
    server.runtime_controller = _RuntimeController()
    server.lark_cli_resolution = LarkCliResolution(
        command=None,
        available=False,
        source="missing",
        version=None,
        error_code="lark_cli_not_installed",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class _RuntimeController:
    def capabilities(self) -> list[dict[str, object]]:
        return []

    def close(self) -> None:
        return None


def _request(
    port: int,
    *,
    method: str,
    origin: str | None,
    path: str = "/api/chat/capabilities",
) -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Origin": origin} if origin else {}
    connection.request(method, path, headers=headers)
    return connection.getresponse()


def test_chat_json_echoes_loopback_cors_origin() -> None:
    server, thread = _start_server()
    try:
        origin = "http://127.0.0.1:49152"
        response = _request(
            server.server_address[1],
            method="GET",
            origin=origin,
        )
        response.read()

        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") == origin
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_chat_capabilities_expose_public_runtime_identity() -> None:
    server, thread = _start_server()
    try:
        response = _request(
            server.server_address[1],
            method="GET",
            origin=None,
        )
        payload = json.loads(response.read().decode("utf-8"))

        assert response.status == 200
        assert payload["runtime_identity"]["schema_version"] == (
            "loopx_runtime_identity_v1"
        )
        assert set(payload["runtime_identity"]) == {
            "schema_version",
            "package_version",
            "release_id",
            "source_revision",
        }
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_chat_json_rejects_foreign_cors_origin() -> None:
    server, thread = _start_server()
    try:
        response = _request(
            server.server_address[1],
            method="GET",
            origin="https://evil.example",
        )
        response.read()

        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") is None
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_chat_options_exposes_loopback_preflight_only() -> None:
    server, thread = _start_server()
    try:
        origin = "http://127.0.0.1:49152"
        response = _request(
            server.server_address[1],
            method="OPTIONS",
            origin=origin,
        )
        response.read()

        assert response.status == 204
        assert response.getheader("Access-Control-Allow-Origin") == origin
        assert response.getheader("Access-Control-Allow-Methods") == (
            "GET, POST, DELETE, OPTIONS"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_chat_status_forwards_valid_goal_activation_scope(monkeypatch) -> None:
    calls: list[str | None] = []

    def fake_collect_status(**kwargs):
        calls.append(kwargs.get("activation_state_filter"))
        return {"ok": True, "scope": kwargs.get("activation_state_filter")}

    monkeypatch.setattr("loopx.chat_status_api.collect_status", fake_collect_status)
    server, thread = _start_server()
    try:
        response = _request(
            server.server_address[1],
            method="GET",
            origin=None,
            path="/status.json?goal_activation=active",
        )
        payload = json.loads(response.read().decode("utf-8"))

        assert response.status == 200
        assert payload == {"ok": True, "scope": "active"}
        assert calls == ["active"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_chat_status_rejects_invalid_goal_activation_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        "loopx.chat_status_api.collect_status",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must fail before collection")),
    )
    server, thread = _start_server()
    try:
        response = _request(
            server.server_address[1],
            method="GET",
            origin=None,
            path="/status.json?goal_activation=active&goal_activation=stopped",
        )
        payload = json.loads(response.read().decode("utf-8"))

        assert response.status == 400
        assert payload["error_code"] == "invalid_goal_activation"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
