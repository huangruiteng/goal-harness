from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from loopx.cli import build_parser
from loopx.control_plane.goals.botmux_runtime import (
    BOTMUX_RUNTIME_BINDING_SCHEMA_VERSION,
    BotmuxApiError,
    BotmuxTransportError,
    botmux_binding_for_goal,
    disable_botmux_runtime,
    doctor_botmux_runtime,
    read_botmux_runtime_binding,
    setup_botmux_runtime,
    status_botmux_runtime,
    trigger_botmux_runtime,
)


GOAL_ID = "goal-public-fixture"
BOT_ID = "cli_public_fixture"
CHAT_ID = "oc_public_fixture"
SESSION_ID = "session-public-fixture"


def _registry(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    state_path = tmp_path / "ACTIVE_GOAL_STATE.md"
    state_path.write_text("# Active Goal\n\n- next: validate botmux\n", encoding="utf-8")
    registry = {
        "goals": [
            {
                "id": GOAL_ID,
                "objective": "Validate a public-safe botmux runtime binding.",
                "repo": str(tmp_path),
                "state_file": str(state_path),
            }
        ]
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return registry, registry_path


def _relative_registry(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    state_path = tmp_path / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("# Active Goal\n\n- next: relative state\n", encoding="utf-8")
    registry = {
        "goals": [
            {
                "id": GOAL_ID,
                "objective": "Validate a relative project state path.",
                "repo": str(tmp_path),
                "state_file": str(state_path.relative_to(tmp_path)),
            }
        ]
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return registry, registry_path


def _requester(
    calls: list[dict[str, Any]],
    working_dir: Path,
):
    def request(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        path = str(kwargs["path"])
        if path == "/__health":
            return {"ok": True}
        if path == "/api/bots":
            return {
                "bots": [
                    {
                        "larkAppId": BOT_ID,
                        "online": True,
                        "defaultWorkingDir": str(working_dir),
                    }
                ]
            }
        if path == "/api/groups":
            return {
                "chats": [
                    {
                        "chatId": chat_id,
                        "memberBots": [
                            {
                                "larkAppId": BOT_ID,
                                "inChat": True,
                                "oncallChat": None,
                            }
                        ],
                    }
                    for chat_id in (CHAT_ID, "oc_second_public_fixture")
                ]
            }
        if path == "/api/trigger":
            body = kwargs["payload"]
            if body["options"].get("dryRun") is True:
                return {"ok": True, "action": "dry_run"}
            return {
                "ok": True,
                "action": "queued",
                "triggerId": "trigger-public-fixture",
                "target": {"sessionId": SESSION_ID},
            }
        if path.endswith("/trigger-result"):
            return {
                "ok": True,
                "state": "completed",
                "output": {"content": "validated"},
            }
        raise AssertionError(f"unexpected botmux request: {kwargs}")

    return request


def _assert_public_packet(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert BOT_ID not in serialized
    assert CHAT_ID not in serialized
    assert SESSION_ID not in serialized
    assert "BOTMUX_TEST_TOKEN" not in serialized
    assert str(Path.home()) not in serialized


def test_runtime_cli_parses_setup_doctor_trigger_and_status() -> None:
    parser = build_parser()

    setup = parser.parse_args(
        [
            "goal-channel",
            "runtime",
            "setup",
            "--goal-id",
            GOAL_ID,
            "--bot-id",
            BOT_ID,
            "--chat-id",
            CHAT_ID,
        ]
    )
    doctor = parser.parse_args(
        ["goal-channel", "runtime", "doctor", "--goal-id", GOAL_ID]
    )
    trigger = parser.parse_args(
        ["goal-channel", "runtime", "trigger", "--goal-id", GOAL_ID]
    )
    status = parser.parse_args(
        ["goal-channel", "runtime", "status", "--goal-id", GOAL_ID]
    )
    disable = parser.parse_args(
        ["goal-channel", "runtime", "disable", "--goal-id", GOAL_ID]
    )

    assert setup.goal_channel_runtime_command == "setup"
    assert setup.endpoint == "http://127.0.0.1:7891"
    assert doctor.goal_channel_runtime_command == "doctor"
    assert trigger.goal_channel_runtime_command == "trigger"
    assert status.goal_channel_runtime_command == "status"
    assert disable.goal_channel_runtime_command == "disable"


def test_setup_is_dry_run_then_writes_owner_private_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")

    preview = setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        requester=_requester(calls, tmp_path),
    )

    assert preview["ok"] is True
    assert preview["status"] == "preview_ready"
    assert not binding_path.exists()
    assert calls[-1]["payload"]["options"] == {"dryRun": True}

    configured = setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester(calls, tmp_path),
    )

    assert configured["ok"] is True
    assert configured["status"] == "configured"
    assert configured["readback_verified"] is True
    assert binding_path.stat().st_mode & 0o777 == 0o600
    stored = read_botmux_runtime_binding(binding_path)
    assert stored["schema_version"] == BOTMUX_RUNTIME_BINDING_SCHEMA_VERSION
    binding = botmux_binding_for_goal(stored, GOAL_ID)
    assert binding is not None
    assert binding["bot_id"] == BOT_ID
    assert binding["chat_id"] == CHAT_ID
    assert binding["token_env"] == "BOTMUX_TEST_TOKEN"
    _assert_public_packet(configured)


def test_doctor_accepts_runtime_agnostic_bot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )

    def another_runtime(**kwargs: Any) -> dict[str, Any]:
        if kwargs["path"] == "/__health":
            return {"ok": True}
        if kwargs["path"] == "/api/bots":
            return {
                "bots": [
                    {
                        "larkAppId": BOT_ID,
                        "cliId": "codex",
                        "online": True,
                        "defaultWorkingDir": str(tmp_path),
                    }
                ]
            }
        if kwargs["path"] == "/api/groups":
            return {
                "chats": [
                    {
                        "chatId": CHAT_ID,
                        "memberBots": [
                            {"larkAppId": BOT_ID, "inChat": True, "oncallChat": None}
                        ],
                    }
                ]
            }
        if kwargs["path"] == "/api/trigger":
            return {"ok": True, "action": "dry_run"}
        raise AssertionError(f"unexpected request: {kwargs}")

    result = doctor_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        requester=another_runtime,
    )

    assert result["ok"] is True
    assert result["status"] == "ready"
    _assert_public_packet(result)


def test_setup_rejects_explicitly_offline_bot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")

    def offline(**kwargs: Any) -> dict[str, Any]:
        if kwargs["path"] == "/__health":
            return {"ok": True}
        if kwargs["path"] == "/api/bots":
            return {
                "bots": [
                    {
                        "larkAppId": BOT_ID,
                        "online": False,
                        "defaultWorkingDir": str(tmp_path),
                    }
                ]
            }
        raise AssertionError("offline bot must stop readiness before chat probing")

    result = setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=offline,
    )

    assert result["ok"] is False
    assert result["blocker"] == "botmux_configuration_invalid"
    assert not binding_path.exists()


def test_disable_is_goal_scoped_and_previewable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )

    preview = disable_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
    )
    before = botmux_binding_for_goal(
        read_botmux_runtime_binding(binding_path),
        GOAL_ID,
    )
    disabled = disable_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
    )
    after = botmux_binding_for_goal(
        read_botmux_runtime_binding(binding_path),
        GOAL_ID,
    )

    assert preview["status"] == "preview_ready"
    assert before is not None and before["enabled"] is True
    assert disabled["status"] == "disabled"
    assert after is not None
    assert after["enabled"] is False
    assert after["session"] == {}
    _assert_public_packet(disabled)


def test_doctor_rejects_failed_health_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )

    result = doctor_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        requester=lambda **kwargs: {"ok": False},
    )

    assert result["ok"] is False
    assert result["blocker"] == "botmux_configuration_invalid"


def test_setup_rejects_botmux_route_for_another_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")

    result = setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path / "another-project"),
    )

    assert result["ok"] is False
    assert result["blocker"] == "botmux_configuration_invalid"
    assert not binding_path.exists()


def test_trigger_is_previewable_idempotent_and_reuses_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    calls: list[dict[str, Any]] = []

    preview = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        requester=_requester(calls, tmp_path),
    )
    queued = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester(calls, tmp_path),
    )
    duplicate = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester(calls, tmp_path),
    )

    assert preview["status"] == "preview_ready"
    assert preview["external_write_performed"] is False
    assert queued["status"] == "queued"
    assert queued["external_write_performed"] is True
    assert duplicate["status"] == "already_dispatched"
    trigger_calls = [call for call in calls if call["path"] == "/api/trigger"]
    assert len(trigger_calls) == 1
    first_target = trigger_calls[0]["payload"]["target"]
    assert first_target == {
        "kind": "turn",
        "botId": BOT_ID,
        "chatId": CHAT_ID,
    }
    _assert_public_packet(queued)
    _assert_public_packet(duplicate)

    followup_calls: list[dict[str, Any]] = []
    followup = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        turn_key="explicit-next-segment",
        execute=True,
        requester=_requester(followup_calls, tmp_path),
    )
    followup_body = followup_calls[0]["payload"]
    assert followup["status"] == "queued"
    assert followup_body["target"] == {
        "kind": "turn",
        "botId": BOT_ID,
        "sessionId": SESSION_ID,
    }
    assert "turnIdempotencyKey" in followup_body["options"]


def test_relative_state_file_changes_default_dispatch_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _relative_registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )

    first = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        requester=_requester([], tmp_path),
    )
    state_path = tmp_path / registry["goals"][0]["state_file"]
    state_path.write_text("# Active Goal\n\n- next: changed state\n", encoding="utf-8")
    second = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        requester=_requester([], tmp_path),
    )

    assert first["idempotency_key"] != second["idempotency_key"]


def test_rebinding_to_another_chat_drops_prior_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester([], tmp_path),
    )

    new_chat = "oc_second_public_fixture"
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=new_chat,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )

    binding = botmux_binding_for_goal(
        read_botmux_runtime_binding(binding_path),
        GOAL_ID,
    )
    assert binding is not None
    assert binding["chat_id"] == new_chat
    assert binding["session"] == {}
    assert binding["receipts"] == {}


def test_status_reads_typed_lifecycle_and_updates_local_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester([], tmp_path),
    )

    result = status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester([], tmp_path),
    )

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["readback_verified"] is True
    assert result["details"] == {
        "dispatch_state": "completed",
        "output_available": True,
        "local_receipt_updated": True,
    }
    _assert_public_packet(result)


def test_status_transport_failure_does_not_regress_terminal_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester([], tmp_path),
    )
    status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester([], tmp_path),
    )

    def unavailable(**kwargs: Any) -> dict[str, Any]:
        raise BotmuxTransportError("fixture status failure")

    observed = status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=unavailable,
    )
    binding = botmux_binding_for_goal(
        read_botmux_runtime_binding(binding_path),
        GOAL_ID,
    )
    assert binding is not None
    dispatch_key = binding["session"]["active_dispatch_key"]

    assert observed["status"] == "unknown"
    assert binding["receipts"][dispatch_key]["state"] == "completed"


@pytest.mark.parametrize(
    ("local_state", "provider_state"),
    [
        ("completed", "running"),
        ("failed", "unknown"),
        ("not_found", None),
    ],
)
def test_status_ignores_provider_regression_after_local_terminal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_state: str,
    provider_state: str | None,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester([], tmp_path),
    )

    def terminal(**kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "state": local_state}

    status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=terminal,
    )

    def stale(**kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "state": provider_state}

    observed = status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=stale,
    )
    binding = botmux_binding_for_goal(
        read_botmux_runtime_binding(binding_path),
        GOAL_ID,
    )
    assert binding is not None
    dispatch_key = binding["session"]["active_dispatch_key"]

    assert observed["ok"] is True
    assert observed["status"] == local_state
    assert "blocker" not in observed
    assert observed["details"] == {
        "dispatch_state": local_state,
        "output_available": False,
        "local_receipt_updated": True,
        "provider_observation": provider_state or "unknown",
        "provider_observation_ignored": True,
    }
    assert binding["receipts"][dispatch_key]["state"] == local_state
    assert (
        binding["receipts"][dispatch_key]["provider_observation"]
        == (provider_state or "unknown")
    )
    assert (
        binding["receipts"][dispatch_key]["provider_observation_ignored"]
        is True
    )
    _assert_public_packet(observed)


def test_status_maps_confirmed_unknown_session_to_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester([], tmp_path),
    )

    def missing(**kwargs: Any) -> dict[str, Any]:
        raise BotmuxApiError(404, {"error": "unknown_session"})

    result = status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        requester=missing,
    )

    assert result["ok"] is True
    assert result["status"] == "not_found"


def test_terminal_failure_requires_new_turn_key_before_redispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester([], tmp_path),
    )

    def failed(**kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "state": "failed"}

    status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=failed,
    )
    calls: list[dict[str, Any]] = []
    duplicate = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=_requester(calls, tmp_path),
    )

    assert duplicate["status"] == "already_dispatched"
    assert calls == []


@pytest.mark.parametrize(
    ("failure_kind", "expected_reason"),
    [
        ("transport", "transport_failure"),
        ("invalid_receipt", "invalid_provider_receipt"),
    ],
)
def test_unknown_dispatch_is_persisted_and_status_never_reports_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_reason: str,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    provider_calls = 0

    def uncertain_provider(**kwargs: Any) -> dict[str, Any]:
        nonlocal provider_calls
        provider_calls += 1
        if failure_kind == "transport":
            raise BotmuxTransportError("fixture transport failure")
        return {"ok": True, "action": "queued"}

    dispatched = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=uncertain_provider,
    )
    binding = botmux_binding_for_goal(
        read_botmux_runtime_binding(binding_path),
        GOAL_ID,
    )
    assert binding is not None
    active_key = str(binding["session"]["active_dispatch_key"])
    receipt = binding["receipts"][active_key]

    assert dispatched["status"] == "dispatch_unknown"
    assert receipt["state"] == "unknown"
    assert receipt["unknown_reason"] == expected_reason
    assert "attempted_at" in receipt

    status = status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
    )
    assert status["ok"] is False
    assert status["status"] == "unknown"
    assert status["blocker"] == "botmux_dispatch_outcome_unknown"
    assert status["details"]["dispatch_state"] == "unknown"

    duplicate = trigger_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
        requester=uncertain_provider,
    )
    assert duplicate["status"] == "already_dispatched"
    assert duplicate["details"]["dispatch_state"] == "unknown"
    assert provider_calls == 1


def test_status_promotes_unresolved_attempt_to_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    payload = read_botmux_runtime_binding(binding_path)
    binding = botmux_binding_for_goal(payload, GOAL_ID)
    assert binding is not None
    dispatch_key = "sha256:" + ("a" * 64)
    binding["receipts"] = {
        dispatch_key: {
            "state": "attempting",
            "attempted_at": "2026-01-01T00:00:00+00:00",
            "session_reused": False,
        }
    }
    binding["session"] = {"active_dispatch_key": dispatch_key}
    payload["bindings"][GOAL_ID] = binding
    binding_path.write_text(json.dumps(payload), encoding="utf-8")

    status = status_botmux_runtime(
        goal_id=GOAL_ID,
        binding_path=binding_path,
        execute=True,
    )
    persisted = botmux_binding_for_goal(
        read_botmux_runtime_binding(binding_path),
        GOAL_ID,
    )

    assert status["status"] == "unknown"
    assert status["details"]["local_receipt_updated"] is True
    assert persisted is not None
    assert persisted["receipts"][dispatch_key]["state"] == "unknown"
    assert (
        persisted["receipts"][dispatch_key]["unknown_reason"]
        == "unresolved_attempt"
    )


def test_concurrent_trigger_dispatches_provider_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, registry_path = _registry(tmp_path)
    binding_path = tmp_path / ".loopx" / "goal-channel-runtime.json"
    monkeypatch.setenv("BOTMUX_TEST_TOKEN", "secret-public-fixture")
    setup_botmux_runtime(
        registry=registry,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        binding_path=binding_path,
        endpoint="http://127.0.0.1:7891",
        bot_id=BOT_ID,
        chat_id=CHAT_ID,
        token_env="BOTMUX_TEST_TOKEN",
        execute=True,
        requester=_requester([], tmp_path),
    )
    provider_call_count = 0
    provider_call_lock = threading.Lock()
    results: list[dict[str, Any]] = []

    def delayed_provider(**kwargs: Any) -> dict[str, Any]:
        nonlocal provider_call_count
        with provider_call_lock:
            provider_call_count += 1
        time.sleep(0.05)
        return {
            "ok": True,
            "action": "queued",
            "triggerId": "trigger-public-fixture",
            "target": {"sessionId": SESSION_ID},
        }

    def run_trigger() -> None:
        results.append(
            trigger_botmux_runtime(
                registry=registry,
                registry_path=registry_path,
                goal_id=GOAL_ID,
                binding_path=binding_path,
                execute=True,
                requester=delayed_provider,
            )
        )

    threads = [threading.Thread(target=run_trigger) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert provider_call_count == 1
    assert sorted(result["status"] for result in results) == [
        "already_dispatched",
        "queued",
    ]
