#!/usr/bin/env python3
"""Smoke-test active user gate delivery through the Lark Goal Channel lifecycle."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loopx.extensions.bundled import bundled_extension_manifest
from loopx.extensions.lark.goal_channel_contracts import (
    GOAL_CHANNEL_BINDING_SCHEMA_VERSION,
    read_goal_channel_binding,
    semantic_key,
    write_goal_channel_binding,
)
from loopx.extensions.lark.goal_channel_lifecycle import (
    sync_human_gate_after_refresh,
)
from loopx.extensions.runtime import (
    default_extension_state_file,
    install_extension,
)
from loopx.control_plane.runtime.public_safety import public_safe_compact_text
from loopx.paths import registry_project_root
from loopx.quota import build_quota_should_run
from loopx.status import collect_status


GOAL_ID = "goal-channel-human-gate-smoke"
GATE_TODO_ID = "todo_gate_fixture"
CHAT_ID = "oc_public_fixture"
MESSAGE_ID = "om_public_fixture"
APP_ID = "cli_public_fixture"


def result(payload: object) -> dict[str, object]:
    return {
        "returncode": 0,
        "stdout": json.dumps(payload),
        "stderr": "",
        "timed_out": False,
    }


class FakeLarkRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.sent_text = ""

    def __call__(
        self,
        args: list[str],
        cwd: Path | None,
        timeout: float | None,
    ) -> dict[str, object]:
        self.calls.append(args)
        if "auth" in args and "status" in args:
            return result(
                {
                    "ok": True,
                    "appId": APP_ID,
                    "identities": {
                        "bot": {
                            "available": True,
                            "verified": True,
                            "appName": "LoopX Bot",
                        }
                    },
                }
            )
        if "chats" in args and "get" in args:
            return result({"ok": True})
        if "+messages-send" in args:
            self.sent_text = args[args.index("--text") + 1]
            return result({"ok": True, "data": {"message_id": MESSAGE_ID}})
        if "+messages-mget" in args:
            return result(
                {
                    "ok": True,
                    "data": {
                        "items": [
                            {
                                "message_id": MESSAGE_ID,
                                "body": {"content": self.sent_text},
                            }
                        ]
                    },
                }
            )
        raise AssertionError(f"unexpected Lark command: {args}")


def write_project(root: Path) -> tuple[Path, Path]:
    project = root / "project"
    runtime = root / "runtime"
    state_path = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    registry_path = project / ".loopx" / "registry.json"
    binding_path = project / ".loopx" / "goal-channel.json"
    state_path.parent.mkdir(parents=True)
    registry_path.parent.mkdir(parents=True)
    state_path.write_text(
        "---\n"
        "status: active\n"
        "owner_mode: goal\n"
        'objective: "Deliver one public-safe human gate fixture."\n'
        "updated_at: 2026-08-08T00:00:00+00:00\n"
        f"adapter_id: {GOAL_ID}\n"
        "---\n\n"
        "# Active Goal State\n\n"
        "## Objective\n\n"
        "Deliver one public-safe human gate fixture.\n\n"
        "## User Todo / Owner Review Reading Queue\n\n"
        "- [ ] [P0] Approve the bounded external write.\n"
        f"  <!-- loopx:todo todo_id={GATE_TODO_ID} status=open "
        "task_class=user_gate action_kind=approve_external_write "
        "global_gate=true -->\n\n"
        "## Agent Todo\n\n"
        "- [ ] [P1] Wait for owner approval.\n"
        "  <!-- loopx:todo todo_id=todo_agent_fixture status=blocked "
        "task_class=advancement_task action_kind=external_write -->\n\n"
        "## Next Action\n\n"
        "- Wait for owner approval.\n",
        encoding="utf-8",
    )
    registry_path.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "objective": "Deliver one public-safe human gate fixture.",
                        "repo": str(project),
                        "state_file": str(state_path),
                        "adapter": {
                            "kind": "read_only_project_map_v0",
                            "status": "connected-read-only",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    write_goal_channel_binding(
        binding_path,
        {
            "schema_version": GOAL_CHANNEL_BINDING_SCHEMA_VERSION,
            "bindings": {
                GOAL_ID: {
                    "goal_id": GOAL_ID,
                    "provider": "lark",
                    "enabled": True,
                    "channel": {
                        "chat_id": CHAT_ID,
                        "chat_name": f"LoopX - {GOAL_ID}",
                    },
                    "kanban": {},
                    "identity": {
                        "mode": "project_bot",
                        "sender_profile": "",
                        "sender_identity": "bot",
                        "bot_app_id": APP_ID,
                        "bot_display_name": "LoopX Bot",
                        "cli_bin": "lark-cli",
                    },
                    "automation": {
                        "human_gate_auto_notify_enabled": True,
                    },
                    "receipts": {},
                }
            },
        },
    )
    install_extension(
        bundled_extension_manifest("loopx-lark"),
        state_file=default_extension_state_file(runtime),
        execute=True,
    )
    return registry_path, binding_path


def main() -> None:
    with tempfile.TemporaryDirectory(
        prefix="loopx-goal-channel-human-gate-"
    ) as raw:
        registry_path, binding_path = write_project(Path(raw))
        runner = FakeLarkRunner()
        first = sync_human_gate_after_refresh(
            registry_path=registry_path,
            runtime_root_override=None,
            goal_id=GOAL_ID,
            agent_id=None,
            external_sink_delivery_authorized=True,
            runner=runner,
        )
        send_count = sum("+messages-send" in args for args in runner.calls)
        second = sync_human_gate_after_refresh(
            registry_path=registry_path,
            runtime_root_override=None,
            goal_id=GOAL_ID,
            agent_id=None,
            external_sink_delivery_authorized=True,
            runner=runner,
        )

        assert first["status"] == "sent_verified", first
        assert first["external_write_performed"] is True, first
        assert first["readback_verified"] is True, first
        notification = first["notification"]
        status = collect_status(
            registry_path=registry_path,
            runtime_root_override=str(Path(raw) / "runtime"),
            scan_roots=[registry_project_root(registry_path)],
            limit=20,
            goal_id=GOAL_ID,
        )
        quota = build_quota_should_run(status, goal_id=GOAL_ID)
        expected_key = semantic_key(
            GOAL_ID,
            "lark",
            "notify_gate",
            GATE_TODO_ID,
            public_safe_compact_text(quota["gate_prompt"], limit=900),
            CHAT_ID,
        )
        assert notification["idempotency_key"] == expected_key, notification
        assert second["status"] == "already_sent", second
        assert sum("+messages-send" in args for args in runner.calls) == send_count
        receipts = read_goal_channel_binding(binding_path)["bindings"][GOAL_ID][
            "receipts"
        ]
        assert expected_key in receipts, receipts
        assert "Approve the bounded external write." in runner.sent_text
        assert "LoopX remains the source of truth" not in runner.sent_text
        public_packet = json.dumps(first, ensure_ascii=False)
        assert CHAT_ID not in public_packet
        assert MESSAGE_ID not in public_packet
        assert str(Path(raw)) not in public_packet

    print("lark-goal-channel-human-gate-delivery-smoke ok")


if __name__ == "__main__":
    main()
