from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.capabilities.periodic_report.request_action import (
    discover_periodic_report_request_ports,
)
from loopx.extensions.runtime import install_extension
from loopx.extensions.lark import periodic_report_request


def _event(message_id: str, content: str) -> dict[str, object]:
    return {
        "schema_version": "lark_event_inbox_event_v0",
        "event_id": f"evt_{message_id}",
        "message_id": message_id,
        "create_time": "2026-09-06T05:00:00Z",
        "content": content,
        "attachment_count": 0,
        "sender_type": "user",
        "addressed_to_bot": True,
        "addressing_source": "provider_mention",
        "provider_mention_count": 1,
        "target_mention_count": 1,
        "reply_context_verified": False,
        "reply_to_bot": False,
    }


def test_lark_adapter_binds_only_agent_selected_source_without_text_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    selected = "om_selected"
    (inbox / f"{selected}.json").write_text(
        json.dumps(
            _event(selected, "I wrote a weekly report; let's discuss its format.")
        ),
        encoding="utf-8",
    )
    (inbox / "om_other.json").write_text(
        json.dumps(_event("om_other", "请生成周报")),
        encoding="utf-8",
    )
    context = {
        "project": tmp_path,
        "selected_config_ref": ".loopx/inbox.json",
        "config": {"inbox_path": inbox},
        "binding_revision": "sha256:" + "a" * 64,
    }
    monkeypatch.setattr(
        periodic_report_request,
        "_resolved_request_context",
        lambda **_kwargs: context,
    )
    ack_calls: list[list[str]] = []
    monkeypatch.setattr(
        periodic_report_request,
        "acknowledge_lark_event_inbox",
        lambda **kwargs: (
            ack_calls.append(list(kwargs["message_ids"]))
            or {
                "ok": True,
                "new_count": 1,
                "already_acknowledged_count": 0,
                "write_performed": True,
            }
        ),
    )

    receipt = periodic_report_request.bind_lark_periodic_report_source(
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
        goal_id="goal-alpha",
        agent_id="agent-alpha",
        source_ref=selected,
    )

    assert receipt["source_ref"] == selected
    assert receipt["raw_content_returned"] is False
    assert "content" not in receipt
    assert ack_calls == []
    settled = periodic_report_request.settle_lark_periodic_report_source(
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
        goal_id="goal-alpha",
        agent_id="agent-alpha",
        source_receipt=receipt,
        execute=True,
    )
    assert settled["status"] == "settled"
    assert ack_calls == [[selected]]


def test_lark_request_ports_are_discovered_from_manifest(tmp_path: Path) -> None:
    state_file = tmp_path / "runtime" / "extensions" / "state.json"
    manifest = Path(periodic_report_request.__file__).with_name("extension.toml")
    installed = install_extension(manifest, state_file=state_file, execute=True)
    assert installed["doctor"]["verified"] is True

    ports = discover_periodic_report_request_ports(
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
        goal_id="goal-alpha",
        agent_id="agent-alpha",
        extension_state_file=state_file,
    )

    assert ports.adapter_id == "lark-periodic-report-source"
    assert callable(ports.bind_source)
    assert callable(ports.settle_source)
