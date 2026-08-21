from __future__ import annotations

import json
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from loopx.control_plane.effect_program import SettlementIdentity
from loopx.control_plane.effect_runtime import EffectRuntimeRejected
from loopx.extensions.capability_admission import (
    bind_external_capability_to_goal,
    invoke_external_capability,
)
from loopx.extensions.governed_capability_execution import (
    reconcile_governed_external_capability,
    start_governed_external_capability,
)
from loopx.extensions.runtime import install_extension


def _provider(path: Path, *, call_log: Path) -> Path:
    path.write_text(
        f"""#!{sys.executable}
import json
import sys
from pathlib import Path

if "--doctor" in sys.argv:
    raise SystemExit(0)

request = json.load(sys.stdin)
phase = request["lifecycle"]["phase"]
with Path({str(call_log)!r}).open("a", encoding="utf-8") as output:
    output.write(phase + "\\n")
result = {{
    "schema_version": "fixture_material_capability_result_v0",
    "invocation_id": request["invocation_id"],
    "status": "running" if phase == "start" else "succeeded",
    "observations": [{{"kind": "synthetic-progress", "phase": phase}}],
    "domain_state_mutations": [],
    "domain_transition_receipts": [],
    "transition_proposals": [],
    "effect_receipt": None,
    "follow_up": {{"kind": "poll", "ref": "synthetic-run-1"}},
}}
if phase == "reconcile":
    result["domain_state_mutations"] = [{{"kind": "synthetic-update"}}]
    result["domain_transition_receipts"] = [{{"kind": "synthetic-commit"}}]
    result["effect_receipt"] = {{
        "schema_version": "loopx_external_effect_receipt_v0",
        "invocation_id": request["invocation_id"],
        "idempotency_key": request["lifecycle"]["idempotency_key"],
        "status": "committed",
        "external_ref": "synthetic-run-1",
        "evidence_digest": "sha256:synthetic-evidence",
    }}
json.dump(result, sys.stdout)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _installed_material_extension(tmp_path: Path) -> tuple[Path, Path, Path]:
    call_log = tmp_path / "provider-calls.txt"
    provider = _provider(tmp_path / "provider", call_log=call_log)
    (tmp_path / "profile.json").write_text(
        json.dumps(
            {
                "schema_version": "loopx_external_domain_capability_profile_v0",
                "capability_id": "fixture-material-delivery",
                "protocol": "fixture_material_provider_v0",
                "operations": [
                    {
                        "id": "publish",
                        "effect_class": "external_write",
                        "todo_contract": {
                            "action_kinds": ["fixture_material_delivery"],
                            "target_key_prefixes": ["fixture-material:"],
                        },
                        "required_permission": "fixture.delivery.write",
                        "request_schema": "fixture_material_capability_request_v0",
                        "result_schema": "fixture_material_capability_result_v0",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "extension.toml"
    manifest.write_text(
        f"""\
schema_version = "loopx_extension_manifest_v0"
id = "fixture-material-provider"
version = "0.1.0"
requires_loopx_api = ">=1,<2"
permissions = ["fixture.delivery.write"]

[runtime]
protocol = "fixture_material_provider_v0"
entrypoint = {json.dumps(str(provider))}
doctor_args = ["--doctor"]
required_permissions = ["fixture.delivery.write"]
timeout_seconds = 5

[[provides]]
id = "fixture-material-delivery"
kind = "requirement_delivery"
title = "Fixture material delivery"
status = "active-preview"
user_value = "Publish one synthetic external change."
next_real_step = "Reconcile one governed provider run."
real_world_anchor = "A synthetic external service."
entry_command = "loopx capability invoke"
visibility = "public"
integration_profile = "profile.json"
""",
        encoding="utf-8",
    )
    state_file = tmp_path / "extensions.json"
    install_extension(manifest, state_file=state_file, execute=True)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "loopx_registry_v1",
                "goals": [
                    {
                        "id": "fixture-goal",
                        "title": "Fixture Goal",
                        "repo": str(tmp_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    bind_external_capability_to_goal(
        registry_path=registry,
        state_file=state_file,
        goal_id="fixture-goal",
        capability_id="fixture-material-delivery",
        operations=["publish"],
        execute=True,
    )
    return state_file, registry, call_log


def _identity(
    *, turn_instance_id: str = "fixture-material-turn-1"
) -> SettlementIdentity:
    return SettlementIdentity(
        goal_id="fixture-goal",
        agent_id="fixture-agent",
        todo_id="todo_fixturematerial1",
        turn_instance_id=turn_instance_id,
    )


def _admission(identity: SettlementIdentity) -> dict[str, object]:
    return {
        "ok": True,
        "should_run": True,
        "selected_todo": {
            "todo_id": identity.todo_id,
            "role": "agent",
            "status": "open",
            "action_kind": "fixture_material_delivery",
            "target_key": "fixture-material:delivery-1",
        },
        "heartbeat_receipt": {"settlement_identity": identity.as_dict()},
    }


def _start_arguments(tmp_path: Path) -> dict[str, object]:
    state_file, registry, _call_log = _installed_material_extension(tmp_path)
    identity = _identity()
    return {
        "state_file": state_file,
        "run_dir": tmp_path / "runs",
        "registry_path": registry,
        "goal_id": identity.goal_id,
        "agent_id": identity.agent_id,
        "todo_id": identity.todo_id,
        "turn_instance_id": identity.turn_instance_id,
        "capability_id": "fixture-material-delivery",
        "operation": "publish",
        "provider_input": {
            "context_refs": [
                {
                    "kind": "synthetic-requirement",
                    "ref": "REQ-1",
                    "digest": "sha256:synthetic-context",
                }
            ],
            "input": {"requirement_key": "REQ-1"},
        },
        "admission": _admission(identity),
    }


def test_material_start_is_previewable_and_provider_idempotent(tmp_path: Path) -> None:
    arguments = _start_arguments(tmp_path)
    call_log = tmp_path / "provider-calls.txt"

    preview = start_governed_external_capability(**arguments)
    started = start_governed_external_capability(**arguments, execute=True)
    replay = start_governed_external_capability(**arguments, execute=True)

    assert preview["status"] == "ready"
    assert preview["executed"] is False
    assert started["status"] == "running"
    assert replay["invocation_id"] == started["invocation_id"]
    assert call_log.read_text(encoding="utf-8").splitlines() == ["start"]
    journal = Path(arguments["run_dir"]) / f"{started['invocation_id']}.json"
    assert stat.S_IMODE(journal.stat().st_mode) == 0o600


def test_material_operation_remains_unavailable_through_direct_invoke(
    tmp_path: Path,
) -> None:
    arguments = _start_arguments(tmp_path)

    with pytest.raises(ValueError, match="requires a governed Turn adapter"):
        invoke_external_capability(
            state_file=arguments["state_file"],
            registry_path=arguments["registry_path"],
            goal_id="fixture-goal",
            capability_id="fixture-material-delivery",
            operation="publish",
            provider_input=arguments["provider_input"],
            execute=True,
        )


def test_material_reconcile_writes_receipt_before_spending_and_replays(
    tmp_path: Path,
) -> None:
    arguments = _start_arguments(tmp_path)
    started = start_governed_external_capability(**arguments, execute=True)
    identity = _identity()
    calls: list[str] = []

    def writeback(context: Mapping[str, object]) -> dict[str, object]:
        calls.append("writeback")
        return {
            "ok": True,
            "appended": True,
            "settlement_identity": context["settlement_identity"],
            "effect_receipt_digest": context["effect_receipt_digest"],
        }

    def spend(context: Mapping[str, object]) -> dict[str, object]:
        calls.append("spend")
        return {
            "ok": True,
            "appended": True,
            "settlement_identity": context["settlement_identity"],
        }

    committed = reconcile_governed_external_capability(
        run_dir=arguments["run_dir"],
        invocation_id=str(started["invocation_id"]),
        writeback=writeback,
        spend=spend,
    )
    replay = reconcile_governed_external_capability(
        run_dir=arguments["run_dir"],
        invocation_id=str(started["invocation_id"]),
        writeback=writeback,
        spend=spend,
    )

    assert committed["status"] == "committed"
    assert committed["effect_id"] == identity.effect_id
    assert committed["effects"] == {
        "provider_invoked": True,
        "external_write_observed": True,
        "loopx_state_written": True,
        "quota_spent": True,
    }
    assert calls == ["writeback", "spend"]
    assert replay["status"] == "committed"
    assert calls == ["writeback", "spend"]
    assert (tmp_path / "provider-calls.txt").read_text(
        encoding="utf-8"
    ).splitlines() == ["start", "reconcile"]


def test_material_start_rejects_a_different_selected_turn(tmp_path: Path) -> None:
    arguments = _start_arguments(tmp_path)
    arguments["admission"] = _admission(
        _identity(turn_instance_id="different-material-turn")
    )

    with pytest.raises(ValueError, match="does not match the invocation"):
        start_governed_external_capability(**arguments, execute=True)


def test_material_start_rejects_an_unrelated_selected_todo_action(
    tmp_path: Path,
) -> None:
    arguments = _start_arguments(tmp_path)
    admission = _admission(_identity())
    selected_todo = admission["selected_todo"]
    assert isinstance(selected_todo, dict)
    selected_todo["action_kind"] = "different_material_action"
    arguments["admission"] = admission

    with pytest.raises(
        EffectRuntimeRejected,
        match="not authorized by selected_todo",
    ):
        start_governed_external_capability(**arguments, execute=True)

    assert not (tmp_path / "provider-calls.txt").exists()


def test_material_start_requires_a_runnable_admission(tmp_path: Path) -> None:
    arguments = _start_arguments(tmp_path)
    arguments["admission"] = {
        **arguments["admission"],
        "should_run": False,
    }

    with pytest.raises(ValueError, match="requires should_run=true"):
        start_governed_external_capability(**arguments, execute=True)

    assert not (tmp_path / "provider-calls.txt").exists()


def test_material_start_recovers_an_existing_journal_without_new_run_authority(
    tmp_path: Path,
) -> None:
    arguments = _start_arguments(tmp_path)
    started = start_governed_external_capability(**arguments, execute=True)
    arguments["admission"] = {
        **arguments["admission"],
        "should_run": False,
    }
    arguments["admission"].pop("selected_todo")

    replay = start_governed_external_capability(**arguments, execute=True)

    assert replay["invocation_id"] == started["invocation_id"]
    assert (tmp_path / "provider-calls.txt").read_text(
        encoding="utf-8"
    ).splitlines() == ["start"]


def test_material_turn_rejects_a_second_distinct_invocation(tmp_path: Path) -> None:
    arguments = _start_arguments(tmp_path)
    first = start_governed_external_capability(**arguments, execute=True)
    second_arguments = {
        **arguments,
        "provider_input": {
            "context_refs": [
                {
                    "kind": "synthetic-requirement",
                    "ref": "REQ-2",
                    "digest": "sha256:synthetic-context-2",
                }
            ],
            "input": {"requirement_key": "REQ-2"},
        },
    }
    second_preview = start_governed_external_capability(**second_arguments)

    assert second_preview["invocation_id"] == first["invocation_id"]
    assert second_preview["request_digest"] != first["request_digest"]
    with pytest.raises(ValueError, match="replay does not match"):
        start_governed_external_capability(**second_arguments, execute=True)
    assert (tmp_path / "provider-calls.txt").read_text(
        encoding="utf-8"
    ).splitlines() == ["start"]


def test_material_settlement_fails_closed_without_effect_receipt_writeback(
    tmp_path: Path,
) -> None:
    arguments = _start_arguments(tmp_path)
    started = start_governed_external_capability(**arguments, execute=True)
    calls: list[str] = []

    def incomplete_writeback(context: Mapping[str, object]) -> dict[str, object]:
        calls.append("writeback")
        return {
            "ok": True,
            "appended": True,
            "settlement_identity": context["settlement_identity"],
        }

    def spend(context: Mapping[str, object]) -> dict[str, object]:
        calls.append("spend")
        return {
            "ok": True,
            "appended": True,
            "settlement_identity": context["settlement_identity"],
        }

    failed = reconcile_governed_external_capability(
        run_dir=arguments["run_dir"],
        invocation_id=str(started["invocation_id"]),
        writeback=incomplete_writeback,
        spend=spend,
    )

    assert failed["ok"] is False
    assert failed["status"] == "settlement_failed"
    assert calls == ["writeback"]


def test_material_reconcile_rejects_tampered_journal_request(tmp_path: Path) -> None:
    arguments = _start_arguments(tmp_path)
    started = start_governed_external_capability(**arguments, execute=True)
    journal_path = Path(arguments["run_dir"]) / f"{started['invocation_id']}.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["request"]["input"]["requirement_key"] = "tampered"
    journal_path.write_text(
        json.dumps(journal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="request digest is invalid"):
        reconcile_governed_external_capability(
            run_dir=arguments["run_dir"],
            invocation_id=str(started["invocation_id"]),
            writeback=lambda _context: {},
            spend=lambda _context: {},
        )


def test_material_reconcile_resumes_at_spend_without_repeating_writeback(
    tmp_path: Path,
) -> None:
    arguments = _start_arguments(tmp_path)
    started = start_governed_external_capability(**arguments, execute=True)
    calls: list[str] = []
    spend_attempts = 0

    def writeback(context: Mapping[str, object]) -> dict[str, object]:
        calls.append("writeback")
        return {
            "ok": True,
            "appended": True,
            "settlement_identity": context["settlement_identity"],
            "effect_receipt_digest": context["effect_receipt_digest"],
        }

    def spend(context: Mapping[str, object]) -> dict[str, object]:
        nonlocal spend_attempts
        calls.append("spend")
        spend_attempts += 1
        return {
            "ok": spend_attempts > 1,
            "appended": spend_attempts > 1,
            "settlement_identity": context["settlement_identity"],
            "reason": "synthetic first-attempt failure",
        }

    first = reconcile_governed_external_capability(
        run_dir=arguments["run_dir"],
        invocation_id=str(started["invocation_id"]),
        writeback=writeback,
        spend=spend,
    )
    second = reconcile_governed_external_capability(
        run_dir=arguments["run_dir"],
        invocation_id=str(started["invocation_id"]),
        writeback=writeback,
        spend=spend,
    )

    assert first["status"] == "settlement_failed"
    assert second["status"] == "committed"
    assert calls == ["writeback", "spend", "spend"]
    assert (tmp_path / "provider-calls.txt").read_text(
        encoding="utf-8"
    ).splitlines() == ["start", "reconcile"]
