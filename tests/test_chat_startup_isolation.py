from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import loopx.chat_server as chat
from loopx.extensions.lark.cli_resolution import LarkCliResolution
from loopx.extensions.lark.goal_topic_runtime import LarkGoalTopicRuntimeService


def test_real_chat_entrypoint_serves_while_binding_discovery_is_blocked(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    servers: list[chat.ChatHTTPServer] = []
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"goals": []}))
    assets = tmp_path / "web"
    assets.mkdir()
    (assets / "index.html").write_text("<html>workspace fixture</html>")

    class Server(chat.ChatHTTPServer):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            servers.append(self)

    def blocked_snapshot(**_kwargs: Any) -> dict[str, Any]:
        entered.set()
        assert release.wait(10)
        return {}

    monkeypatch.setattr(chat, "ChatHTTPServer", Server)
    monkeypatch.setattr(
        chat, "build_lark_goal_topic_runtime_snapshot", blocked_snapshot
    )
    monkeypatch.setattr(
        chat,
        "resolve_lark_cli_for_runtime",
        lambda **_kwargs: LarkCliResolution(
            None, False, "missing", None, "lark_cli_not_installed"
        ),
    )
    worker = threading.Thread(
        target=chat.serve_chat,
        kwargs={
            "registry_path": registry,
            "runtime_root_override": tmp_path / "runtime",
            "scan_roots": [],
            "port": 0,
            "assets_dir": assets,
            "codex_bin": "nonexistent-loopx-test-codex",
            "claude_bin": "nonexistent-loopx-test-claude",
        },
        daemon=True,
    )
    worker.start()
    try:
        assert entered.wait(5)
        base = f"http://127.0.0.1:{servers[0].server_port}"
        for route in ("/healthz", "/api/chat/capabilities"):
            with urlopen(base + route, timeout=2) as response:
                assert json.load(response)["ok"] is True
        with urlopen(base + chat.DEFAULT_CHAT_PATH, timeout=2) as response:
            assert b"workspace fixture" in response.read()
        servers[0].shutdown()
        worker.join(2)
        assert not worker.is_alive(), "shutdown must not wait for project access"
    finally:
        release.set()
        if servers and worker.is_alive():
            servers[0].shutdown()
        worker.join(5)


def test_late_discovery_cannot_resume_queues_or_start_consumers_after_close(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    applied: list[object] = []

    def snapshot() -> dict[str, Any]:
        entered.set()
        assert release.wait(5)
        return {}

    service = LarkGoalTopicRuntimeService(
        snapshot_provider=snapshot,
        runtime_root=tmp_path,
        runtime_controller=object(),
        profile_poller=lambda *args: applied.append(args),
    )
    monkeypatch.setattr(service, "_resume_session_queues", applied.append)
    service.start()
    original = service._startup_thread
    service.start()
    assert service._startup_thread is original
    try:
        assert entered.wait(2)
        service.close()
    finally:
        release.set()
        assert original is not None
        original.join(2)
    service.refresh()
    service.start()
    assert not original.is_alive()
    assert applied == []
    assert service.active_profiles() == []


def test_initial_discovery_failure_retries_without_an_app_restart(tmp_path: Path) -> None:
    calls = []

    def snapshot() -> dict[str, Any]:
        calls.append(None)
        if len(calls) == 1:
            raise OSError("fixture unavailable")
        return {}

    service = LarkGoalTopicRuntimeService(
        snapshot_provider=snapshot, runtime_root=tmp_path, runtime_controller=object(),
    )
    try:
        service.start()
        assert service._startup_thread is not None
        service._startup_thread.join(7)
        assert not service._startup_thread.is_alive()
        assert len(calls) == 2
        assert service.active_profiles() == []
    finally:
        service.close()
