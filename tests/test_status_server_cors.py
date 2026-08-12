from __future__ import annotations

import http.client
import threading

from loopx.status_server import (
    StatusHTTPServer,
    StatusRequestHandler,
    cors_response_headers,
)


def test_cors_response_headers_loopback_origin_is_echoed() -> None:
    headers = cors_response_headers("http://127.0.0.1:8123")

    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8123"
    assert headers["Access-Control-Allow-Methods"] == "GET, POST, OPTIONS"
    assert headers["Vary"] == "Origin"


def test_cors_response_headers_localhost_origin_is_echoed() -> None:
    headers = cors_response_headers("http://localhost:8123")

    assert headers["Access-Control-Allow-Origin"] == "http://localhost:8123"


def test_cors_response_headers_foreign_origin_is_rejected() -> None:
    assert cors_response_headers("https://evil.example") == {}


def test_cors_response_headers_missing_origin_needs_no_cors() -> None:
    assert cors_response_headers(None) == {}


def _start_server() -> tuple[StatusHTTPServer, threading.Thread]:
    server = StatusHTTPServer(("127.0.0.1", 0), StatusRequestHandler)
    server.verbose = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _get(port: int, *, origin: str | None) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Origin": origin} if origin else {}
    conn.request("GET", "/healthz", headers=headers)
    return conn.getresponse()


def test_healthz_without_origin_omits_acao() -> None:
    server, thread = _start_server()
    try:
        response = _get(server.server_address[1], origin=None)
        body = response.read()
        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") is None
        assert b'"ok": true' in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_healthz_with_foreign_origin_omits_acao() -> None:
    server, thread = _start_server()
    try:
        response = _get(server.server_address[1], origin="https://evil.example")
        response.read()
        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") is None
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_healthz_with_loopback_origin_echoes_acao() -> None:
    server, thread = _start_server()
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        response = _get(server.server_address[1], origin=origin)
        response.read()
        assert response.status == 200
        assert response.getheader("Access-Control-Allow-Origin") == origin
    finally:
        server.shutdown()
        thread.join(timeout=5)
