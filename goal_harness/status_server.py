from __future__ import annotations

import hashlib
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
DEFAULT_REWARD_APPEND_PATH = "/reward/append"

REWARD_REQUEST_FIELDS = {
    "goal_id",
    "run_generated_at",
    "recorded_at",
    "decision",
    "reward",
    "reason_summary",
    "follow_up",
}
REWARD_APPEND_FIELDS = REWARD_REQUEST_FIELDS | {
    "preview_id",
    "write_active_state_summary",
}


def is_loopback_host(host: str) -> bool:
    hostname = host.strip().lower()
    return hostname in {"127.0.0.1", "localhost", "::1", "[::1]"}


def is_loopback_origin(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and is_loopback_host(parsed.hostname or "")


def reward_preview_id(payload: dict[str, Any]) -> str:
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


class StatusHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    registry_path: Path
    runtime_root_override: str | None
    scan_roots: list[Path]
    limit: int
    status_path: str
    reward_dry_run_path: str
    reward_append_path: str
    reward_write_enabled: bool
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

    def _parse_reward_body(self, body: dict[str, Any], *, append: bool) -> tuple[str, str | None, dict[str, Any]]:
        allowed = REWARD_APPEND_FIELDS if append else REWARD_REQUEST_FIELDS
        unknown = sorted(set(body) - allowed)
        if unknown:
            raise ValueError(f"unknown reward field(s): {', '.join(unknown)}")

        goal_id = str(body.get("goal_id") or "").strip()
        decision = str(body.get("decision") or "").strip()
        reward_value = str(body.get("reward") or "").strip()
        reason_summary = str(body.get("reason_summary") or "").strip()
        run_generated_at = body.get("run_generated_at")
        follow_up_value = body.get("follow_up")
        follow_up = str(follow_up_value).strip() if follow_up_value else None
        if not goal_id:
            raise ValueError("goal_id is required")
        if append and not run_generated_at:
            raise ValueError("run_generated_at is required for reward append")
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
        return goal_id, str(run_generated_at).strip() if run_generated_at else None, reward

    def _compact_reward_response(self, payload: dict[str, Any], *, dry_run: bool, appended: bool) -> dict[str, Any]:
        preview_payload = {
            "goal_id": payload.get("goal_id"),
            "raw_index_records_before": payload.get("raw_index_records_before"),
            "selected_run": payload.get("selected_run"),
            "human_reward": payload.get("human_reward"),
        }
        return {
            "ok": True,
            "dry_run": dry_run,
            "appended": appended,
            "goal_id": payload.get("goal_id"),
            "raw_index_records_before": payload.get("raw_index_records_before"),
            "preview_id": reward_preview_id(preview_payload),
            "selected_run": payload.get("selected_run"),
            "human_reward": payload.get("human_reward"),
            "active_state_summary": payload.get("active_state_summary"),
            "project_agent_visibility": payload.get("project_agent_visibility"),
        }

    def _reward_dry_run_payload(self, body: dict[str, Any], *, append: bool = False) -> dict[str, Any]:
        goal_id, run_generated_at, reward = self._parse_reward_body(body, append=append)
        return append_human_reward(
            registry_path=self.server.registry_path,
            runtime_root_override=self.server.runtime_root_override,
            goal_id=goal_id,
            run_generated_at=run_generated_at,
            reward=reward,
            dry_run=True,
            write_active_state_summary=bool(body.get("write_active_state_summary")) if append else False,
        )

    def _handle_reward_dry_run(self) -> None:
        try:
            payload = self._reward_dry_run_payload(self._read_json_body())
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

        self._send_json(self._compact_reward_response(payload, dry_run=True, appended=False))

    def _handle_reward_append(self) -> None:
        if not self.server.reward_write_enabled:
            self._send_json(
                {
                    "ok": False,
                    "dry_run": False,
                    "appended": False,
                    "error": "reward write API is not enabled; restart serve-status with --enable-reward-write-api",
                },
                status=403,
            )
            return
        if not is_loopback_origin(self.headers.get("Origin")):
            self._send_json(
                {
                    "ok": False,
                    "dry_run": False,
                    "appended": False,
                    "error": "reward append only accepts loopback browser origins",
                },
                status=403,
            )
            return

        try:
            body = self._read_json_body()
            preview_id = str(body.get("preview_id") or "").strip()
            if not preview_id:
                raise ValueError("preview_id is required")
            dry_run_payload = self._reward_dry_run_payload(body, append=True)
            expected_preview = self._compact_reward_response(dry_run_payload, dry_run=True, appended=False).get("preview_id")
            if preview_id != expected_preview:
                self._send_json(
                    {
                        "ok": False,
                        "dry_run": False,
                        "appended": False,
                        "error": "stale reward preview; run Dry-run Check again before appending",
                    },
                    status=409,
                )
                return
            goal_id, run_generated_at, reward = self._parse_reward_body(body, append=True)
            payload = append_human_reward(
                registry_path=self.server.registry_path,
                runtime_root_override=self.server.runtime_root_override,
                goal_id=goal_id,
                run_generated_at=run_generated_at,
                reward=reward,
                dry_run=False,
                write_active_state_summary=bool(body.get("write_active_state_summary", True)),
            )
        except Exception as exc:  # noqa: BLE001 - preserve validation diagnostics for the local UI.
            self._send_json(
                {
                    "ok": False,
                    "dry_run": False,
                    "appended": False,
                    "error": str(exc),
                },
                status=400,
            )
            return

        self._send_json(self._compact_reward_response(payload, dry_run=False, appended=True))

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
                    "reward_append_url": self.server.reward_append_path if self.server.reward_write_enabled else None,
                    "reward_write_enabled": self.server.reward_write_enabled,
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
        if path == self.server.reward_append_path:
            self._handle_reward_append()
            return
        self._send_json(
            {
                "ok": False,
                "error": f"unknown path: {path}",
                "reward_dry_run_url": self.server.reward_dry_run_path,
                "reward_append_url": self.server.reward_append_path if self.server.reward_write_enabled else None,
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
    enable_reward_write_api: bool,
    verbose: bool,
) -> None:
    normalized_path = normalize_status_path(status_path)
    if enable_reward_write_api and not is_loopback_host(host):
        raise ValueError("--enable-reward-write-api requires a loopback --host such as 127.0.0.1")
    server = StatusHTTPServer((host, port), StatusRequestHandler)
    server.registry_path = registry_path
    server.runtime_root_override = runtime_root_override
    server.scan_roots = scan_roots
    server.limit = limit
    server.status_path = normalized_path
    server.reward_dry_run_path = DEFAULT_REWARD_DRY_RUN_PATH
    server.reward_append_path = DEFAULT_REWARD_APPEND_PATH
    server.reward_write_enabled = enable_reward_write_api
    server.verbose = verbose
    print(f"Serving Goal Harness status at http://{host}:{port}{normalized_path}", flush=True)
    print(f"Reward dry-run: http://{host}:{port}{server.reward_dry_run_path}", flush=True)
    if enable_reward_write_api:
        print(f"Reward append: http://{host}:{port}{server.reward_append_path}", flush=True)
    print(f"Health check: http://{host}:{port}/healthz", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Goal Harness status server")
    finally:
        server.server_close()
