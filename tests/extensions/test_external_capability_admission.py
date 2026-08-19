from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from loopx.cli import main
from loopx.control_plane.quota.turn_envelope import (
    turn_envelope_action_signature_document,
)
from loopx.control_plane.turn_driver import build_loopx_turn_plan
from loopx.extensions.capability_admission import (
    invoke_external_capability,
    validate_external_capability_result,
)
from loopx.extensions.manifest import load_extension_manifest
from loopx.extensions.runtime import install_extension


def _provider(path: Path) -> Path:
    path.write_text(
        f"""#!{sys.executable}
import json
import sys

if "--doctor" in sys.argv:
    raise SystemExit(0)

request = json.load(sys.stdin)
json.dump({{
    "schema_version": "loopx_external_domain_capability_result_v0",
    "invocation_id": request["invocation_id"],
    "status": "succeeded",
    "observations": [{{
        "schema_version": "fixture_projection_v0",
        "requirement_ref": request["input"]["requirement_key"],
        "snapshot_digest": "sha256:fixture",
    }}],
    "domain_state_mutations": [],
    "domain_transition_receipts": [],
    "transition_proposals": [],
    "effect_receipt": None,
    "follow_up": {{"kind": "none"}},
}}, sys.stdout)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _profile(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "loopx_external_domain_capability_profile_v0",
                "capability_id": "fixture-requirement-delivery",
                "protocol": "external_fixture_provider_v0",
                "operations": [
                    {
                        "id": "observe",
                        "effect_class": "read_only",
                        "required_permission": "fixture.requirement.read",
                        "request_schema": (
                            "loopx_external_domain_capability_request_v0"
                        ),
                        "result_schema": (
                            "loopx_external_domain_capability_result_v0"
                        ),
                        "todo_contract": {
                            "action_kinds": ["fixture_requirement_observe"],
                            "target_key_prefixes": ["fixture:requirement:"],
                            "capability_binding_refs": ["fixture-binding-1"],
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _manifest(path: Path, *, provider: Path) -> Path:
    path.write_text(
        f"""\
schema_version = "loopx_extension_manifest_v0"
id = "fixture-delivery-provider"
version = "0.1.0"
requires_loopx_api = ">=1,<2"
permissions = ["fixture.requirement.read"]

[runtime]
protocol = "external_fixture_provider_v0"
entrypoint = {json.dumps(str(provider))}
doctor_args = ["--doctor"]
required_permissions = ["fixture.requirement.read"]
timeout_seconds = 5

[[provides]]
id = "fixture-requirement-delivery"
kind = "requirement_delivery"
title = "Fixture requirement delivery"
status = "active-preview"
user_value = "Observe a bounded requirement projection."
next_real_step = "Validate one external provider invocation."
real_world_anchor = "A synthetic requirement service."
entry_command = "loopx capability invoke"
visibility = "public"
integration_profile = "profile.json"
""",
        encoding="utf-8",
    )
    return path


def _turn_plan(
    *,
    action_kind: str = "fixture_requirement_observe",
    capability_binding_ref: str = "fixture-binding-1",
) -> dict[str, object]:
    envelope = {
        "ok": True,
        "schema_version": "loopx_turn_envelope_v0",
        "goal_id": "fixture-goal",
        "agent_id": "codex-fixture",
        "should_run": True,
        "effective_action": "normal_run",
        "action": {
            "must_attempt": True,
            "delivery_allowed": True,
            "quiet_noop_allowed": False,
            "selected_todo": {
                "todo_id": "todo_fixture0001",
                "action_kind": action_kind,
                "target_key": "fixture:requirement:REQ-1",
                "capability_binding_ref": capability_binding_ref,
                "text": "Observe one synthetic requirement.",
            },
        },
        "user": {
            "action_required": False,
            "open_count": 0,
            "notify": "DONT_NOTIFY",
        },
        "writeback": {"spend_after_validation": True},
        "scheduler": {"action": "run_now"},
        "compaction": {"within_budget": True},
    }
    signature_document = turn_envelope_action_signature_document(envelope)
    signature_hash = "sha256:" + sha256(
        json.dumps(
            signature_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    envelope["action_signature"] = {
        "matches": True,
        "source_hash": signature_hash,
        "envelope_hash": signature_hash,
    }
    return build_loopx_turn_plan(
        envelope,
        host="codex-cli",
        execution_mode="isolated-headless",
        turn_instance_id="fixture-turn-1",
    )


def _provider_input() -> dict[str, object]:
    return {
        "context_refs": [
            {
                "kind": "fixture-requirement",
                "ref": "REQ-1",
                "digest": "sha256:context",
            }
        ],
        "input": {"requirement_key": "REQ-1"},
    }


def _installed_extension(tmp_path: Path) -> Path:
    provider = _provider(tmp_path / "provider")
    _profile(tmp_path / "profile.json")
    manifest = _manifest(tmp_path / "extension.toml", provider=provider)
    state_file = tmp_path / "extensions.json"
    install_extension(manifest, state_file=state_file, execute=True)
    return state_file


def test_manifest_snapshots_external_capability_profile_and_digest(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path / "provider")
    _profile(tmp_path / "profile.json")
    manifest = load_extension_manifest(
        _manifest(tmp_path / "extension.toml", provider=provider)
    )

    capability = manifest["capabilities"][0]
    assert capability["integration_profile"]["capability_id"] == (
        "fixture-requirement-delivery"
    )
    assert capability["integration_profile_digest"].startswith("sha256:")


def test_manifest_rejects_profile_path_escape(tmp_path: Path) -> None:
    provider = _provider(tmp_path / "provider")
    _profile(tmp_path / "profile.json")
    escaped = _profile(tmp_path.parent / "escaped-profile.json")
    manifest = _manifest(tmp_path / "extension.toml", provider=provider)
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'integration_profile = "profile.json"',
            f"integration_profile = {json.dumps(str(escaped))}",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be a relative JSON path"):
        load_extension_manifest(manifest)


def test_read_only_external_capability_is_bound_to_one_turn_and_todo(
    tmp_path: Path,
) -> None:
    state_file = _installed_extension(tmp_path)
    plan = _turn_plan()

    preview = invoke_external_capability(
        state_file=state_file,
        capability_id="fixture-requirement-delivery",
        operation="observe",
        turn_plan=plan,
        provider_input=_provider_input(),
    )
    executed = invoke_external_capability(
        state_file=state_file,
        capability_id="fixture-requirement-delivery",
        operation="observe",
        turn_plan=plan,
        provider_input=_provider_input(),
        execute=True,
    )

    assert preview["status"] == "ready"
    assert preview["executed"] is False
    assert preview["invocation_id"] == executed["invocation_id"]
    assert executed["status"] == "succeeded"
    assert executed["effects"] == {
        "provider_invoked": True,
        "external_write_performed": False,
        "loopx_state_written": False,
        "quota_spent": False,
    }
    assert executed["turn"] == {
        "goal_id": "fixture-goal",
        "agent_id": "codex-fixture",
        "todo_id": "todo_fixture0001",
        "turn_key": plan["transaction"]["turn_key"],
        "turn_instance_id": "fixture-turn-1",
    }


def test_external_capability_rejects_todo_outside_profile(tmp_path: Path) -> None:
    state_file = _installed_extension(tmp_path)
    plan = _turn_plan(action_kind="unrelated_action")

    with pytest.raises(ValueError, match="action_kind is outside"):
        invoke_external_capability(
            state_file=state_file,
            capability_id="fixture-requirement-delivery",
            operation="observe",
            turn_plan=plan,
            provider_input=_provider_input(),
        )


def test_external_capability_rejects_wrong_capability_binding(tmp_path: Path) -> None:
    state_file = _installed_extension(tmp_path)
    plan = _turn_plan(capability_binding_ref="different-binding")

    with pytest.raises(ValueError, match="capability_binding_ref is outside"):
        invoke_external_capability(
            state_file=state_file,
            capability_id="fixture-requirement-delivery",
            operation="observe",
            turn_plan=plan,
            provider_input=_provider_input(),
        )


def test_external_capability_rejects_tampered_turn_key(tmp_path: Path) -> None:
    state_file = _installed_extension(tmp_path)
    plan = _turn_plan()
    plan["transaction"]["turn_key"] = "sha256:" + "f" * 64

    with pytest.raises(ValueError, match="turn_key does not match"):
        invoke_external_capability(
            state_file=state_file,
            capability_id="fixture-requirement-delivery",
            operation="observe",
            turn_plan=plan,
            provider_input=_provider_input(),
        )


def test_read_only_result_rejects_secret_fields() -> None:
    with pytest.raises(ValueError, match="forbidden field"):
        validate_external_capability_result(
            {
                "schema_version": "loopx_external_domain_capability_result_v0",
                "invocation_id": "capability-fixture",
                "status": "succeeded",
                "observations": [{"access_token": "synthetic-secret-value"}],
                "domain_state_mutations": [],
                "domain_transition_receipts": [],
                "transition_proposals": [],
                "effect_receipt": None,
                "follow_up": {"kind": "none"},
            },
            invocation_id="capability-fixture",
            operation={
                "effect_class": "read_only",
                "result_schema": "loopx_external_domain_capability_result_v0",
            },
        )


def test_capability_invoke_cli_uses_managed_runtime(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_file = _installed_extension(tmp_path)
    turn_plan = tmp_path / "turn-plan.json"
    provider_input = tmp_path / "provider-input.json"
    turn_plan.write_text(json.dumps(_turn_plan()), encoding="utf-8")
    provider_input.write_text(json.dumps(_provider_input()), encoding="utf-8")

    assert (
        main(
            [
                "--format",
                "json",
                "capability",
                "invoke",
                "fixture-requirement-delivery",
                "--operation",
                "observe",
                "--turn-plan-json",
                str(turn_plan),
                "--input-json",
                str(provider_input),
                "--state-file",
                str(state_file),
                "--execute",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["provider_result"]["observations"][0]["requirement_ref"] == (
        "REQ-1"
    )
