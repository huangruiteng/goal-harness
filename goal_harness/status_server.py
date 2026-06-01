from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .feedback import append_human_reward, compact_reward
from .status import collect_status


DEFAULT_STATUS_HOST = "127.0.0.1"
DEFAULT_STATUS_PORT = 8765
DEFAULT_STATUS_PATH = "/status.json"
DEFAULT_REWARD_DRY_RUN_PATH = "/reward/dry-run"


class StatusHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    registry_path: Path
    runtime_root_override: str | None
    scan_roots: list[Path]
    limit: int
    status_path: str
    reward_dry_run_path: str
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length") or "0")
        if content_length <= 0:
            raise ValueError("request body is empty")
        if content_length > 64_000:
            raise ValueError("request body is too large")
        raw = self.rfile.read(content_length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _handle_reward_dry_run(self) -> None:
        try:
            body = self._read_json_body()
            goal_id = str(body.get("goal_id") or "").strip()
            decision = str(body.get("decision") or "").strip()
            reward_value = str(body.get("reward") or "").strip()
            reason_summary = str(body.get("reason_summary") or "").strip()
            run_generated_at = body.get("run_generated_at")
            follow_up_value = body.get("follow_up")
            follow_up = str(follow_up_value).strip() if follow_up_value else None
            if not goal_id:
                raise ValueError("goal_id is required")
            if not decision:
                raise ValueError("decision is required")
            if not reason_summary:
                raise ValueError("reason_summary is required")

            reward = compact_reward(
                recorded_at=str(body.get("recorded_at")).strip() if body.get("recorded_at") else None,
                decision=decision,
                reward=reward_value,
                reason_summary=reason_summary,
                follow_up=follow_up,
            )
            payload = append_human_reward(
                registry_path=self.server.registry_path,
                runtime_root_override=self.server.runtime_root_override,
                goal_id=goal_id,
                run_generated_at=str(run_generated_at).strip() if run_generated_at else None,
                reward=reward,
                dry_run=True,
            )
        except Exception as exc:  # noqa: BLE001 - preserve validation diagnostics for the local UI.
            self._send_json(
                {
                    "ok": False,
                    "dry_run": True,
                    "appended": False,
                    "error": str(exc),
                },
                status=400,
            )
            return

        self._send_json(
            {
                "ok": True,
                "dry_run": True,
                "appended": False,
                "goal_id": payload.get("goal_id"),
                "raw_index_records_before": payload.get("raw_index_records_before"),
                "selected_run": payload.get("selected_run"),
                "human_reward": payload.get("human_reward"),
            }
        )

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
                    "reward_dry_run_url": self.server.reward_dry_run_path,
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

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == self.server.reward_dry_run_path:
            self._handle_reward_dry_run()
            return
        self._send_json(
            {
                "ok": False,
                "error": f"unknown path: {path}",
                "reward_dry_run_url": self.server.reward_dry_run_path,
            },
            status=404,
        )

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
    server.reward_dry_run_path = DEFAULT_REWARD_DRY_RUN_PATH
    server.verbose = verbose
    print(f"Serving Goal Harness status at http://{host}:{port}{normalized_path}", flush=True)
    print(f"Reward dry-run: http://{host}:{port}{server.reward_dry_run_path}", flush=True)
    print(f"Health check: http://{host}:{port}/healthz", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Goal Harness status server")
    finally:
        server.server_close()
