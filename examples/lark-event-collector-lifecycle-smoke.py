#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loopx.capabilities.lark.event_collector import (  # noqa: E402
    inspect_lark_event_collector,
    install_lark_event_collector,
    plan_lark_event_collector,
)


def completed(argv: list[str], returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout="", stderr="")


with tempfile.TemporaryDirectory(prefix="loopx-lark-collector-") as raw:
    temp = Path(raw)
    project = temp / "project"
    home = temp / "home"
    bin_dir = temp / "bin"
    project.mkdir()
    home.mkdir()
    bin_dir.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text(".loopx/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", ".gitignore"], check=True)
    lark_cli = bin_dir / "lark-cli"
    lark_cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    lark_cli.chmod(0o755)
    node = bin_dir / "node"
    node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    node.chmod(0o755)
    config_dir = project / ".loopx" / "config" / "lark"
    config_dir.mkdir(parents=True)
    inbox_config = config_dir / "event-inbox.json"
    inbox_config.write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_config_v0",
                "enabled": True,
                "inbox_dir": ".loopx/inbox/team-feedback",
                "capture_scope": "configured_chat_all",
                "reply": {
                    "enabled": True,
                    "sender_profile": "project-review-bot",
                    "sender_identity": "bot",
                    "bot_display_name": "Project Review Bot",
                    "chat_id": "oc_private_fixture_chat",
                },
            }
        ),
        encoding="utf-8",
    )
    collector_config = config_dir / "collector.json"
    collector_config.write_text(
        json.dumps(
            {
                "schema_version": "lark_event_collector_config_v0",
                "enabled": True,
                "service_name": "loopx-lark-feedback",
                "event_key": "im.message.receive_v1",
                "identity": "bot",
                "supervisor": "launchd",
                "chat_id": "oc_private_fixture_chat",
                "consume_timeout": "30m",
                "lark_cli_bin": "lark-cli",
                "event_inbox_config": ".loopx/config/lark/event-inbox.json",
            }
        ),
        encoding="utf-8",
    )
    previous_home = os.environ.get("HOME")
    previous_path = os.environ.get("PATH")
    os.environ["HOME"] = str(home)
    os.environ["PATH"] = f"{bin_dir}:{previous_path or ''}"
    calls: list[list[str]] = []

    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if argv[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout="state = running\n", stderr=""
            )
        return completed(argv)

    try:
        plan = plan_lark_event_collector(project=project, config_path=collector_config)
        assert plan["status"] == "install_ready", plan
        assert plan["thread_complete"] is True, plan
        assert plan["profile_bound"] is True, plan
        assert plan["profile_source"] == "event_inbox_reply", plan
        assert plan["profile_returned"] is False, plan
        assert "project-review-bot" not in json.dumps(plan), plan
        assert plan["chat_id_returned"] is False, plan
        assert "oc_private_fixture_chat" not in json.dumps(plan), plan
        preview = install_lark_event_collector(
            project=project,
            config_path=collector_config,
            runner=runner,
        )
        assert preview["status"] == "preview_ready", preview
        assert preview["would_write_service"] is True, preview
        assert calls == [
            [str(node), str(lark_cli), "event", "consume", "--help"]
        ], calls

        installed = install_lark_event_collector(
            project=project,
            config_path=collector_config,
            execute=True,
            runner=runner,
        )
        assert installed["status"] == "installed", installed
        assert installed["write_performed"] is True, installed
        assert any(call[:2] == ["launchctl", "bootstrap"] for call in calls), calls
        plist = home / "Library" / "LaunchAgents" / "loopx-lark-feedback.plist"
        assert plist.is_file(), plist
        plist_text = plist.read_text(encoding="utf-8")
        assert str(node) in plist_text, plist_text
        assert str(lark_cli) in plist_text, plist_text
        service_argv = plistlib.loads(plist.read_bytes())["ProgramArguments"]
        assert service_argv[:6] == [
            str(node),
            str(lark_cli),
            "--profile",
            "project-review-bot",
            "event",
            "consume",
        ], service_argv

        inbox = project / ".loopx" / "inbox" / "team-feedback"
        inbox.mkdir(parents=True)
        (inbox / "om_fixture.json").write_text(
            json.dumps(
                {
                    "schema_version": "lark_event_inbox_event_v0",
                    "event_id": "om_fixture",
                    "message_id": "om_fixture",
                    "create_time": "1",
                    "content": "public-safe fixture",
                }
            ),
            encoding="utf-8",
        )
        status = inspect_lark_event_collector(
            project=project,
            config_path=collector_config,
            probe_event_bus=True,
            runner=runner,
        )
        assert status["healthy"] is True, status
        assert status["real_event_evidence_present"] is True, status
        assert status["captured_event_count"] == 1, status
        assert status["profile_bound"] is True, status
        assert status["profile_source"] == "event_inbox_reply", status
        assert status["profile_returned"] is False, status
        assert "project-review-bot" not in json.dumps(status), status
        assert status["local_paths_returned"] is False, status
        assert status["chat_id_returned"] is False, status

        unsupported = json.loads(collector_config.read_text())
        unsupported["event_key"] = "im.message.reaction.created_v1"
        collector_config.write_text(json.dumps(unsupported), encoding="utf-8")
        try:
            plan_lark_event_collector(
                project=project,
                config_path=collector_config,
            )
        except ValueError as exc:
            assert "im.message.receive_v1" in str(exc), exc
        else:
            raise AssertionError("unsupported event key should fail closed")
        unsupported["event_key"] = "im.message.receive_v1"
        unsupported["identity"] = "user"
        collector_config.write_text(json.dumps(unsupported), encoding="utf-8")
        try:
            plan_lark_event_collector(
                project=project,
                config_path=collector_config,
            )
        except ValueError as exc:
            assert "identity must be bot" in str(exc), exc
        else:
            raise AssertionError("unsupported identity should fail closed")
        unsupported["identity"] = "bot"
        collector_config.write_text(json.dumps(unsupported), encoding="utf-8")

        mismatched = json.loads(collector_config.read_text())
        mismatched["profile"] = "another-review-bot"
        collector_config.write_text(json.dumps(mismatched), encoding="utf-8")
        try:
            plan_lark_event_collector(
                project=project,
                config_path=collector_config,
            )
        except ValueError as exc:
            assert "must match" in str(exc), exc
        else:
            raise AssertionError("collector and reply profiles must not diverge")
        mismatched.pop("profile")
        collector_config.write_text(json.dumps(mismatched), encoding="utf-8")

        no_profile = json.loads(inbox_config.read_text())
        no_profile.pop("reply")
        inbox_config.write_text(json.dumps(no_profile), encoding="utf-8")
        try:
            plan_lark_event_collector(
                project=project,
                config_path=collector_config,
            )
        except ValueError as exc:
            assert "explicit non-default profile" in str(exc), exc
        else:
            raise AssertionError("enabled collector must not use the default profile")
        explicit = json.loads(collector_config.read_text())
        explicit["profile"] = "project-review-bot"
        collector_config.write_text(json.dumps(explicit), encoding="utf-8")
        explicit_plan = plan_lark_event_collector(
            project=project,
            config_path=collector_config,
        )
        assert explicit_plan["profile_source"] == "collector_config", explicit_plan
        explicit.pop("profile")
        collector_config.write_text(json.dumps(explicit), encoding="utf-8")
        no_profile["reply"] = {
            "enabled": True,
            "sender_profile": "project-review-bot",
            "sender_identity": "bot",
            "bot_display_name": "Project Review Bot",
            "chat_id": "oc_private_fixture_chat",
        }
        inbox_config.write_text(json.dumps(no_profile), encoding="utf-8")

        addressed = json.loads(inbox_config.read_text())
        addressed["capture_scope"] = "addressed_only"
        inbox_config.write_text(json.dumps(addressed), encoding="utf-8")
        failed = subprocess.run(
            [
                sys.executable,
                "-m",
                "loopx.cli",
                "--format",
                "json",
                "lark-inbox",
                "collector-plan",
                "--project",
                str(project),
                "--config",
                str(collector_config),
            ],
            cwd=ROOT,
            env=os.environ,
            capture_output=True,
            text=True,
            check=False,
        )
        assert failed.returncode == 1, failed.stdout
        error = json.loads(failed.stdout)
        assert "configured_chat_all" in error["error"], error
    finally:
        if previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous_home
        if previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous_path

print("lark event collector lifecycle smoke: ok")
