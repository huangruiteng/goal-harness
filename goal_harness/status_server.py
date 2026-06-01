from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .status import collect_status


DEFAULT_STATUS_HOST = "127.0.0.1"
DEFAULT_STATUS_PORT = 8765
DEFAULT_STATUS_PATH = "/status.json"


class StatusHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    registry_path: Path
    runtime_root_override: str | None
    scan_roots: list[Path]
    limit: int
    status_path: str
    verbose: bool


class StatusRequestHandler(BaseHTTPRequestHandler):
    server: StatusHTTPServer

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send_json({"ok": True})
            return
        if path in {"", "/"}:
            self._send_json(
                {
                    "ok": True,
                    "status_url": self.server.status_path,
                    "health_url": "/healthz",
                }
            )
            return
        if path != self.server.status_path:
            self._send_json(
                {
                    "ok": False,
                    "error": f"unknown path: {path}",
                    "status_url": self.server.status_path,
                },
                status=404,
            )
            return

        try:
            payload = collect_status(
                registry_path=self.server.registry_path,
                runtime_root_override=self.server.runtime_root_override,
                scan_roots=self.server.scan_roots,
                limit=self.server.limit,
            )
        except Exception as exc:  # noqa: BLE001 - the HTTP layer should preserve diagnostics.
            self._send_json(
                {
                    "ok": False,
                    "registry": str(self.server.registry_path),
                    "runtime_root": self.server.runtime_root_override,
                    "error": str(exc),
                },
                status=500,
            )
            return

        self._send_json(payload)

    def log_message(self, format: str, *args: object) -> None:
        if self.server.verbose:
            super().log_message(format, *args)


def normalize_status_path(path: str) -> str:
    trimmed = path.strip() or DEFAULT_STATUS_PATH
    if not trimmed.startswith("/"):
        trimmed = f"/{trimmed}"
    return trimmed


def serve_status(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    scan_roots: list[Path],
    limit: int,
    host: str,
    port: int,
    status_path: str,
    verbose: bool,
) -> None:
    normalized_path = normalize_status_path(status_path)
    server = StatusHTTPServer((host, port), StatusRequestHandler)
    server.registry_path = registry_path
    server.runtime_root_override = runtime_root_override
    server.scan_roots = scan_roots
    server.limit = limit
    server.status_path = normalized_path
    server.verbose = verbose
    print(f"Serving Goal Harness status at http://{host}:{port}{normalized_path}", flush=True)
    print(f"Health check: http://{host}:{port}/healthz", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Goal Harness status server")
    finally:
        server.server_close()
