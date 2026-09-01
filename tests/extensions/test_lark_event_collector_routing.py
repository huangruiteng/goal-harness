from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from loopx.cli_commands import lark_inbox
from loopx.extensions.lark.event_collector import (
    _jq_projection,
    load_lark_event_collector_config,
    plan_lark_event_collector,
)
from loopx.extensions.lark.event_collector_runtime import (
    _is_profile_self_message,
    run_lark_event_collector,
)
from loopx.extensions.lark.event_inbox import inspect_lark_event_inbox
from loopx.extensions.lark.routed_inbox import (
    acknowledge_routed_lark_event_inbox,
    ingest_routed_lark_event_inbox,
    inspect_routed_lark_event_inbox,
    project_routed_lark_event_inbox_urgency,
    resolve_routed_lark_inbox_config,
    resolve_routed_lark_inbox_route,
)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text(".loopx/\n", encoding="utf-8")
    return project


def _write_inbox(
    project: Path,
    *,
    name: str,
    chat_id: str,
    profile: str = "shared-context-bot",
) -> str:
    relative = f".loopx/config/lark/{name}.json"
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_config_v0",
                "enabled": True,
                "inbox_dir": f".loopx/inbox/{name}",
                "capture_scope": "configured_chat_all",
                "reply": {
                    "enabled": True,
                    "sender_profile": profile,
                    "sender_identity": "bot",
                    "bot_display_name": "Shared Context Bot",
                    "chat_id": chat_id,
                    "placement_policy": "source_context",
                    "editorial_style": "bullet_points_preferred",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return relative


def _write_collector(
    project: Path,
    *,
    routes: list[dict[str, str]],
    schema_version: str = "lark_event_collector_config_v1",
) -> Path:
    path = project / ".loopx/config/lark/collector.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "enabled": True,
        "service_name": "loopx-shared-context",
        "event_key": "im.message.receive_v1",
        "identity": "bot",
        "supervisor": "systemd",
        "consume_timeout": "30m",
        "lark_cli_bin": "lark-cli",
    }
    if schema_version == "lark_event_collector_config_v0":
        payload.update(routes[0])
    else:
        payload["routes"] = routes
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _two_route_config(tmp_path: Path) -> tuple[Path, Path, str, str]:
    project = _project(tmp_path)
    first_chat = "oc_public_fixture_alpha"
    second_chat = "oc_public_fixture_beta"
    first = _write_inbox(
        project,
        name="requirements-alpha",
        chat_id=first_chat,
    )
    second = _write_inbox(
        project,
        name="requirements-beta",
        chat_id=second_chat,
    )
    collector = _write_collector(
        project,
        routes=[
            {
                "route_key": "requirements-alpha",
                "chat_id": first_chat,
                "event_inbox_config": first,
            },
            {
                "route_key": "requirements-beta",
                "chat_id": second_chat,
                "event_inbox_config": second,
            },
        ],
    )
    return project, collector, first_chat, second_chat


def test_v1_plan_binds_one_profile_to_isolated_multi_chat_routes(
    tmp_path: Path,
) -> None:
    project, collector, first_chat, second_chat = _two_route_config(tmp_path)

    config = load_lark_event_collector_config(
        project=project,
        config_path=collector,
    )
    plan = plan_lark_event_collector(project=project, config_path=collector)

    assert config["schema_version"] == "lark_event_collector_config_v1"
    assert len(config["routes"]) == 2
    assert [route["route_key"] for route in config["routes"]] == [
        "requirements-alpha",
        "requirements-beta",
    ]
    assert config["profile"] == "shared-context-bot"
    assert config["profile_source"] == "event_inbox_reply"
    assert len({route["inbox"]["inbox_path"] for route in config["routes"]}) == 2
    assert plan["route_count"] == 2
    assert plan["multi_chat_routing"] is True
    assert plan["thread_complete"] is True
    assert plan["profile_returned"] is False
    assert plan["chat_id_returned"] is False
    serialized = json.dumps(plan)
    assert first_chat not in serialized
    assert second_chat not in serialized
    assert "shared-context-bot" not in serialized
    assert str(project) not in serialized


def test_top_level_outbound_route_requires_one_explicit_route_key(
    tmp_path: Path,
) -> None:
    project, collector, _, _ = _two_route_config(tmp_path)

    resolved = resolve_routed_lark_inbox_route(
        project=project,
        config_path=collector,
        route_key="requirements-beta",
    )

    assert resolved.endswith("requirements-beta.json")
    with pytest.raises(ValueError, match="exactly one configured route_key"):
        resolve_routed_lark_inbox_route(
            project=project,
            config_path=collector,
            route_key=None,
        )
    with pytest.raises(ValueError, match="exactly one configured route_key"):
        resolve_routed_lark_inbox_route(
            project=project,
            config_path=collector,
            route_key="missing-route",
        )


def test_v0_config_is_normalized_to_one_route(tmp_path: Path) -> None:
    project = _project(tmp_path)
    chat_id = "oc_public_fixture_single"
    inbox = _write_inbox(project, name="requirements-single", chat_id=chat_id)
    collector = _write_collector(
        project,
        schema_version="lark_event_collector_config_v0",
        routes=[{"chat_id": chat_id, "event_inbox_config": inbox}],
    )

    config = load_lark_event_collector_config(
        project=project,
        config_path=collector,
    )
    plan = plan_lark_event_collector(project=project, config_path=collector)

    assert len(config["routes"]) == 1
    assert config["routes"][0]["route_key"] == "default"
    assert config["routes"][0]["chat_id"] == chat_id
    assert plan["route_count"] == 1
    assert plan["multi_chat_routing"] is False


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("duplicate_chat", "unique chat ids"),
        ("missing_route_key", "public-safe token"),
        ("duplicate_route_key", "unique route keys"),
        ("unsafe_route_key", "public-safe token"),
        ("duplicate_inbox", "independent event inbox"),
        ("reply_chat_mismatch", "must match the inbox reply chat_id"),
        ("profile_mismatch", "must match one profile-bound event stream"),
    ],
)
def test_multi_chat_routes_fail_closed_on_ambiguous_bindings(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    project, collector, first_chat, _ = _two_route_config(tmp_path)
    payload = json.loads(collector.read_text(encoding="utf-8"))
    if mutation == "duplicate_chat":
        payload["routes"][1]["chat_id"] = first_chat
    elif mutation == "missing_route_key":
        payload["routes"][0].pop("route_key")
    elif mutation == "duplicate_route_key":
        payload["routes"][1]["route_key"] = payload["routes"][0]["route_key"]
    elif mutation == "unsafe_route_key":
        payload["routes"][0]["route_key"] = "Private Requirement Group"
    elif mutation == "duplicate_inbox":
        payload["routes"][1]["event_inbox_config"] = payload["routes"][0][
            "event_inbox_config"
        ]
    elif mutation == "reply_chat_mismatch":
        first_inbox = project / payload["routes"][0]["event_inbox_config"]
        inbox_payload = json.loads(first_inbox.read_text(encoding="utf-8"))
        inbox_payload["reply"]["chat_id"] = "oc_public_fixture_other"
        first_inbox.write_text(json.dumps(inbox_payload), encoding="utf-8")
    else:
        second_inbox = project / payload["routes"][1]["event_inbox_config"]
        inbox_payload = json.loads(second_inbox.read_text(encoding="utf-8"))
        inbox_payload["reply"]["sender_profile"] = "different-context-bot"
        second_inbox.write_text(json.dumps(inbox_payload), encoding="utf-8")
    collector.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_lark_event_collector_config(
            project=project,
            config_path=collector,
        )


def test_jq_projection_filters_one_stream_to_all_configured_chats() -> None:
    projection = _jq_projection(["oc_public_fixture_alpha", "oc_public_fixture_beta"])

    assert '.chat_id == "oc_public_fixture_alpha"' in projection
    assert '.chat_id == "oc_public_fixture_beta"' in projection
    assert " or " in projection
    assert "chat_id:.chat_id" in projection
    assert "sender_type:(.sender_type // .sender.sender_type)" in projection
    assert "sender_id:(.sender_id // .sender.id // .sender.sender_id)" in projection


def test_self_message_match_requires_typed_app_and_exact_verified_identity() -> None:
    identity = "cli_public_fixture_bot"

    assert _is_profile_self_message(
        {"sender_type": "app", "sender_id": identity},
        profile_app_id=identity,
    )
    assert not _is_profile_self_message(
        {"sender_type": "user", "sender_id": identity},
        profile_app_id=identity,
    )
    assert not _is_profile_self_message(
        {"sender_type": "app", "sender_id": identity},
        profile_app_id=None,
    )
    assert not _is_profile_self_message(
        {"sender_type": "app", "sender_id": "cli_public_fixture_other"},
        profile_app_id=identity,
    )


def test_cli_drain_accepts_routed_collector_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, collector, first_chat, second_chat = _two_route_config(tmp_path)
    receipt = ingest_routed_lark_event_inbox(
        project=project,
        config_path=collector,
        events=[
            {
                "schema_version": "lark_event_inbox_event_v0",
                "message_id": "om_public_alpha",
                "content": "alpha request",
                "chat_id": first_chat,
            },
            {
                "schema_version": "lark_event_inbox_event_v0",
                "message_id": "om_public_beta",
                "content": "beta request",
                "chat_id": second_chat,
            },
        ],
        execute=True,
    )
    monkeypatch.setattr(
        lark_inbox,
        "_resolve_lark_activation",
        lambda *_args, **_kwargs: {"enabled": True},
    )
    rendered: list[dict[str, object]] = []
    args = argparse.Namespace(
        command="lark-inbox",
        lark_inbox_command="drain",
        project=str(project),
        config=str(collector),
        goal_id=None,
        agent_id=None,
        limit=20,
    )

    code = lark_inbox.handle_lark_inbox_command(
        args,
        registry_path=tmp_path / "registry.json",
        runtime_root_arg=None,
        output_format=lambda _args: "json",
        print_payload=lambda payload, *_args: rendered.append(payload),
    )

    assert receipt["accepted_count"] == 2
    assert code == 0
    assert rendered[0]["route_count"] == 2
    assert rendered[0]["pending_count"] == 2
    assert [item["route_key"] for item in rendered[0]["items"]] == [
        "requirements-alpha",
        "requirements-beta",
    ]
    assert rendered[0]["extension_activation"] == {"enabled": True}


def test_cli_send_resolves_route_and_forwards_safe_delivery_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, collector, _, _ = _two_route_config(tmp_path)
    monkeypatch.setattr(
        lark_inbox,
        "_resolve_lark_activation",
        lambda *_args, **_kwargs: {"enabled": True},
    )
    calls: list[dict[str, object]] = []

    def fake_send(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "ok": True,
            "schema_version": "lark_outbound_message_v0",
            "status": "preview_ready",
            "external_write_performed": False,
        }

    monkeypatch.setattr(lark_inbox, "send_lark_inbox_message", fake_send)
    rendered: list[dict[str, object]] = []
    args = argparse.Namespace(
        command="lark-inbox",
        lark_inbox_command="send",
        project=str(project),
        config=str(collector),
        goal_id=None,
        agent_id=None,
        route_key="requirements-beta",
        text='<at open_id="ou_fixture">Fixture Reviewer</at> please review',
        provider_preflight=True,
        execute=False,
    )

    code = lark_inbox.handle_lark_inbox_command(
        args,
        registry_path=tmp_path / "registry.json",
        runtime_root_arg=None,
        output_format=lambda _args: "json",
        print_payload=lambda payload, *_args: rendered.append(payload),
    )

    assert code == 0
    assert len(calls) == 1
    assert str(calls[0]["config_path"]).endswith("requirements-beta.json")
    assert calls[0]["provider_preflight"] is True
    assert calls[0]["execute"] is False
    assert rendered[0]["status"] == "preview_ready"
    assert rendered[0]["extension_activation"] == {"enabled": True}


def test_runtime_collector_captures_without_provider_acknowledgement(
    tmp_path: Path,
) -> None:
    project, collector, first_chat, second_chat = _two_route_config(tmp_path)
    events = [
        {
            "schema_version": "lark_event_inbox_event_v0",
            "event_id": "evt-alpha",
            "message_id": "om_public_alpha",
            "create_time": "2026-08-25T00:00:00Z",
            "content": "alpha request",
            "chat_id": first_chat,
            "mentioned": True,
        },
        {
            "schema_version": "lark_event_inbox_event_v0",
            "event_id": "evt-beta",
            "message_id": "om_public_beta",
            "create_time": "2026-08-25T00:01:00Z",
            "content": "beta request",
            "chat_id": second_chat,
            "mentioned": True,
        },
        {
            "schema_version": "lark_event_inbox_event_v0",
            "event_id": "evt-unconfigured",
            "message_id": "om_public_unconfigured",
            "create_time": "2026-08-25T00:02:00Z",
            "content": "unconfigured request",
            "chat_id": "oc_public_fixture_unconfigured",
            "mentioned": True,
        },
    ]
    runtime_cli = tmp_path / "runtime-lark-cli"
    runtime_cli.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        f"events = {events!r}\n"
        "args = sys.argv[1:]\n"
        "if args.count('consume') != 1:\n"
        "    raise SystemExit(2)\n"
        "projection = args[args.index('--jq') + 1]\n"
        f"if {first_chat!r} not in projection or {second_chat!r} not in projection:\n"
        "    raise SystemExit(3)\n"
        "for event in events:\n"
        "    print(json.dumps(event), flush=True)\n",
        encoding="utf-8",
    )
    runtime_cli.chmod(0o755)

    def unexpected_runner(
        argv: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"unexpected provider lookup: {argv}")

    result = run_lark_event_collector(
        project=project,
        config_path=collector,
        lark_cli_executable=str(runtime_cli),
        runner=unexpected_runner,
    )

    assert result == {
        "ok": True,
        "schema_version": "lark_event_collector_run_v1",
        "status": "completed",
        "captured_count": 2,
        "route_count": 2,
        "routed_route_count": 2,
        "multi_chat_routing": True,
        "reply_context_verified_count": 0,
        "reply_to_bot_count": 0,
        "received_reaction_count": 0,
        "received_reaction_failure_count": 0,
        "self_message_skipped_count": 0,
        "external_writes_performed": False,
        "profile_identity_checked": False,
        "profile_identity_verified": False,
        "chat_ids_returned": False,
        "local_paths_returned": False,
        "private_content_returned": False,
    }
    first = inspect_lark_event_inbox(
        project=project,
        config_path=".loopx/config/lark/requirements-alpha.json",
        limit=10,
    )
    second = inspect_lark_event_inbox(
        project=project,
        config_path=".loopx/config/lark/requirements-beta.json",
        limit=10,
    )
    assert [item["message_id"] for item in first["items"]] == ["om_public_alpha"]
    assert [item["message_id"] for item in second["items"]] == ["om_public_beta"]
    assert first["items"][0]["route_key"] == "requirements-alpha"
    assert second["items"][0]["route_key"] == "requirements-beta"
    aggregate = inspect_routed_lark_event_inbox(
        project=project,
        config_path=collector,
        limit=10,
    )
    assert aggregate["route_count"] == 2
    assert aggregate["routes_with_pending_count"] == 2
    assert aggregate["pending_count"] == 2
    assert [item["message_id"] for item in aggregate["items"]] == [
        "om_public_alpha",
        "om_public_beta",
    ]
    assert all("reply_guidance" in item for item in aggregate["items"])
    assert [item["route_key"] for item in aggregate["items"]] == [
        "requirements-alpha",
        "requirements-beta",
    ]
    assert aggregate["route_keys_returned"] is True
    urgency = project_routed_lark_event_inbox_urgency(
        project=project,
        config_path=collector,
    )
    assert urgency["route_count"] == 2
    assert urgency["routes_with_pending_count"] == 2
    assert urgency["pending_count"] == 2
    assert urgency["local_private_content_returned"] is False
    assert first_chat not in json.dumps(urgency)
    assert second_chat not in json.dumps(urgency)
    assert (
        resolve_routed_lark_inbox_config(
            project=project,
            config_path=collector,
            message_id="om_public_beta",
        )
        == ".loopx/config/lark/requirements-beta.json"
    )

    acknowledged = acknowledge_routed_lark_event_inbox(
        project=project,
        config_path=collector,
        message_ids=["om_public_alpha"],
        execute=True,
    )
    assert acknowledged["new_count"] == 1
    assert (
        inspect_lark_event_inbox(
            project=project,
            config_path=".loopx/config/lark/requirements-alpha.json",
            limit=10,
        )["pending_count"]
        == 0
    )
    assert (
        inspect_lark_event_inbox(
            project=project,
            config_path=".loopx/config/lark/requirements-beta.json",
            limit=10,
        )["pending_count"]
        == 1
    )


def test_runtime_excludes_only_verified_profile_self_messages(tmp_path: Path) -> None:
    project, collector, first_chat, _second_chat = _two_route_config(tmp_path)
    profile_app_id = "cli_public_fixture_bot"
    events = [
        {
            "schema_version": "lark_event_inbox_event_v0",
            "event_id": "evt-self",
            "message_id": "om_public_self",
            "create_time": "2026-08-25T00:00:00Z",
            "content": "Bot delivery status",
            "chat_id": first_chat,
            "sender_type": "app",
            "sender_id": profile_app_id,
        },
        {
            "schema_version": "lark_event_inbox_event_v0",
            "event_id": "evt-other-app",
            "message_id": "om_public_other_app",
            "create_time": "2026-08-25T00:01:00Z",
            "content": "@Shared Context Bot please review",
            "chat_id": first_chat,
            "sender_type": "app",
            "sender_id": "cli_public_fixture_other",
            "mentions": [{"name": "Shared Context Bot"}],
        },
    ]
    runtime_cli = tmp_path / "runtime-lark-cli-self-filter"
    runtime_cli.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"events = {events!r}\n"
        "for event in events:\n"
        "    print(json.dumps(event), flush=True)\n",
        encoding="utf-8",
    )
    runtime_cli.chmod(0o755)

    def identity_runner(
        argv: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        assert "whoami" in argv
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=json.dumps({"appId": profile_app_id}),
            stderr="",
        )

    result = run_lark_event_collector(
        project=project,
        config_path=collector,
        lark_cli_executable=str(runtime_cli),
        runner=identity_runner,
    )

    assert result["self_message_skipped_count"] == 1
    assert result["captured_count"] == 1
    assert result["profile_identity_checked"] is True
    assert result["profile_identity_verified"] is True
    inbox = project / ".loopx/inbox/requirements-alpha"
    assert not (inbox / "om_public_self.json").exists()
    assert (inbox / "om_public_other_app.json").is_file()


@pytest.mark.parametrize("tampered_route_key", [None, "requirements-beta"])
def test_routed_drain_fails_closed_on_missing_or_mismatched_persisted_route_key(
    tmp_path: Path,
    tampered_route_key: str | None,
) -> None:
    project, collector, first_chat, _ = _two_route_config(tmp_path)
    receipt = ingest_routed_lark_event_inbox(
        project=project,
        config_path=collector,
        events=[
            {
                "schema_version": "lark_event_inbox_event_v0",
                "message_id": "om_public_alpha",
                "content": "alpha request",
                "chat_id": first_chat,
            }
        ],
        execute=True,
    )
    assert receipt["accepted_count"] == 1
    event_path = project / ".loopx/inbox/requirements-alpha/om_public_alpha.json"
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    if tampered_route_key is None:
        payload.pop("route_key")
    else:
        payload["route_key"] = tampered_route_key
    event_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="route_key must match"):
        inspect_routed_lark_event_inbox(
            project=project,
            config_path=collector,
            limit=10,
        )


def test_disabled_route_inbox_message_resolution_fails_closed(
    tmp_path: Path,
) -> None:
    """A disabled route inbox has no message store; resolving a message id on a
    paused collector must fail closed with a clean error, not raise on a None
    inbox path.
    """

    project = _project(tmp_path)
    disabled_inbox = ".loopx/config/lark/disabled.json"
    path = project / disabled_inbox
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_config_v0",
                "enabled": False,
                "inbox_dir": ".loopx/inbox/disabled",
                "capture_scope": "configured_chat_all",
                "reply": {
                    "enabled": False,
                    "sender_profile": "disabled-context-bot",
                    "sender_identity": "bot",
                    "bot_display_name": "Disabled Context Bot",
                    "chat_id": "oc_public_fixture_disabled",
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    collector = _write_collector(
        project,
        routes=[
            {
                "route_key": "requirements-disabled",
                "chat_id": "oc_public_fixture_disabled",
                "event_inbox_config": disabled_inbox,
            },
        ],
    )
    payload = json.loads(collector.read_text(encoding="utf-8"))
    payload["enabled"] = False
    collector.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="must resolve to exactly one configured Lark inbox route",
    ):
        resolve_routed_lark_inbox_config(
            project=project,
            config_path=collector,
            message_id="om_public_fixture_disabled",
        )
