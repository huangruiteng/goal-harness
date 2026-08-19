from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from loopx.cli import main
from loopx.extensions.capability_admission import (
    bind_external_capability_to_goal,
    invoke_external_capability,
    load_goal_external_capability_binding,
    resolve_external_capability_binding,
    validate_external_capability_result,
)
from loopx.extensions.manifest import load_extension_manifest
from loopx.extensions.runtime import default_extension_state_file, install_extension


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
                        "result_schema": ("loopx_external_domain_capability_result_v0"),
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


def _goal_binding(
    state_file: Path,
    *,
    operations: list[str] | None = None,
    revision: str | None = None,
) -> dict[str, object]:
    active = resolve_external_capability_binding(
        state_file=state_file,
        capability_id="fixture-requirement-delivery",
        operation="observe",
    )
    return {
        "schema_version": "loopx_goal_external_capability_binding_v0",
        "goal_id": "fixture-goal",
        "capability_id": "fixture-requirement-delivery",
        "operations": operations or ["observe"],
        "provider": {
            "extension_id": active["extension_id"],
            "revision": revision or active["revision"],
            "profile_digest": active["integration_profile_digest"],
        },
    }


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


def _external_result(observations: list[object]) -> dict[str, object]:
    return {
        "schema_version": "loopx_external_domain_capability_result_v0",
        "invocation_id": "capability-fixture",
        "status": "succeeded",
        "observations": observations,
        "domain_state_mutations": [],
        "domain_transition_receipts": [],
        "transition_proposals": [],
        "effect_receipt": None,
        "follow_up": {"kind": "none"},
    }


def _installed_extension(tmp_path: Path) -> Path:
    provider = _provider(tmp_path / "provider")
    _profile(tmp_path / "profile.json")
    manifest = _manifest(tmp_path / "extension.toml", provider=provider)
    state_file = tmp_path / "extensions.json"
    install_extension(manifest, state_file=state_file, execute=True)
    return state_file


def _registry(path: Path, *, runtime_root: Path | None = None) -> Path:
    payload: dict[str, object] = {
        "schema_version": "loopx_registry_v1",
        "goals": [
            {
                "id": "fixture-goal",
                "title": "Fixture Goal",
                "repo": str(path.parent),
            }
        ],
    }
    if runtime_root is not None:
        payload["common_runtime_root"] = str(runtime_root)
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    return path


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


def test_manifest_rejects_unimplemented_external_write_profile(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path / "provider")
    profile = _profile(tmp_path / "profile.json")
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("read_only", "external_write"),
        encoding="utf-8",
    )
    manifest = _manifest(tmp_path / "extension.toml", provider=provider)

    with pytest.raises(ValueError, match="must be `read_only` in the v0 profile"):
        load_extension_manifest(manifest)


def test_read_only_external_capability_is_bound_to_goal_not_turn(
    tmp_path: Path,
) -> None:
    state_file = _installed_extension(tmp_path)
    goal_binding = _goal_binding(state_file)

    preview = invoke_external_capability(
        state_file=state_file,
        capability_id="fixture-requirement-delivery",
        operation="observe",
        goal_binding=goal_binding,
        provider_input=_provider_input(),
    )
    executed = invoke_external_capability(
        state_file=state_file,
        capability_id="fixture-requirement-delivery",
        operation="observe",
        goal_binding=goal_binding,
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
    assert executed["goal_binding"] == {
        "goal_id": "fixture-goal",
        "binding_digest": preview["goal_binding"]["binding_digest"],
        "turn_required": False,
    }


def test_goal_binding_preview_execute_and_idempotent_readback(tmp_path: Path) -> None:
    state_file = _installed_extension(tmp_path)
    registry_path = _registry(tmp_path / "registry.json")
    original = registry_path.read_text(encoding="utf-8")

    preview = bind_external_capability_to_goal(
        registry_path=registry_path,
        state_file=state_file,
        goal_id="fixture-goal",
        capability_id="fixture-requirement-delivery",
        operations=["observe"],
    )

    assert preview["status"] == "ready"
    assert preview["changed"] is True
    assert preview["written"] is False
    assert preview["turn_required"] is False
    assert preview["quota_spent"] is False
    assert registry_path.read_text(encoding="utf-8") == original

    written = bind_external_capability_to_goal(
        registry_path=registry_path,
        state_file=state_file,
        goal_id="fixture-goal",
        capability_id="fixture-requirement-delivery",
        operations=["observe"],
        execute=True,
    )
    repeated = bind_external_capability_to_goal(
        registry_path=registry_path,
        state_file=state_file,
        goal_id="fixture-goal",
        capability_id="fixture-requirement-delivery",
        operations=["observe"],
        execute=True,
    )
    stored = load_goal_external_capability_binding(
        registry_path=registry_path,
        goal_id="fixture-goal",
        capability_id="fixture-requirement-delivery",
    )

    assert written["status"] == "written"
    assert written["written"] is True
    assert repeated["status"] == "no_change"
    assert repeated["changed"] is False
    assert repeated["written"] is False
    assert stored == written["binding"]


def test_external_capability_resolves_durable_goal_binding(tmp_path: Path) -> None:
    state_file = _installed_extension(tmp_path)
    registry_path = _registry(tmp_path / "registry.json")
    bind_external_capability_to_goal(
        registry_path=registry_path,
        state_file=state_file,
        goal_id="fixture-goal",
        capability_id="fixture-requirement-delivery",
        operations=["observe"],
        execute=True,
    )

    executed = invoke_external_capability(
        state_file=state_file,
        registry_path=registry_path,
        goal_id="fixture-goal",
        capability_id="fixture-requirement-delivery",
        operation="observe",
        provider_input=_provider_input(),
        execute=True,
    )

    assert executed["status"] == "succeeded"
    assert executed["goal_binding"]["goal_id"] == "fixture-goal"
    assert executed["goal_binding"]["turn_required"] is False


def test_durable_goal_binding_fails_closed_after_provider_revision_drift(
    tmp_path: Path,
) -> None:
    state_file = _installed_extension(tmp_path)
    registry_path = _registry(tmp_path / "registry.json")
    bind_external_capability_to_goal(
        registry_path=registry_path,
        state_file=state_file,
        goal_id="fixture-goal",
        capability_id="fixture-requirement-delivery",
        operations=["observe"],
        execute=True,
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["goals"][0]["external_capability_bindings"][0]["provider"]["revision"] = (
        "sha256:stale-provider-revision"
    )
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(ValueError, match="active provider revision"):
        invoke_external_capability(
            state_file=state_file,
            registry_path=registry_path,
            goal_id="fixture-goal",
            capability_id="fixture-requirement-delivery",
            operation="observe",
            provider_input=_provider_input(),
        )


@pytest.mark.parametrize(
    ("requested_goal_id", "binding_goal_id"),
    [
        ("fixture-goal", "different-goal"),
        ("different-goal", "fixture-goal"),
    ],
)
def test_durable_goal_binding_rejects_cross_goal_lineage(
    tmp_path: Path,
    requested_goal_id: str,
    binding_goal_id: str,
) -> None:
    state_file = _installed_extension(tmp_path)
    registry_path = _registry(tmp_path / "registry.json")
    bind_external_capability_to_goal(
        registry_path=registry_path,
        state_file=state_file,
        goal_id="fixture-goal",
        capability_id="fixture-requirement-delivery",
        operations=["observe"],
        execute=True,
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    binding = registry["goals"][0]["external_capability_bindings"][0]
    if requested_goal_id == "fixture-goal":
        binding["goal_id"] = binding_goal_id
    else:
        registry["goals"].append(
            {
                "id": requested_goal_id,
                "title": "Different Goal",
                "repo": str(tmp_path),
                "external_capability_bindings": [binding],
            }
        )
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match containing Goal"):
        invoke_external_capability(
            state_file=state_file,
            registry_path=registry_path,
            goal_id=requested_goal_id,
            capability_id="fixture-requirement-delivery",
            operation="observe",
            provider_input=_provider_input(),
        )


def test_external_capability_rejects_operation_outside_goal_binding(
    tmp_path: Path,
) -> None:
    state_file = _installed_extension(tmp_path)

    with pytest.raises(ValueError, match="not enabled for this Goal"):
        invoke_external_capability(
            state_file=state_file,
            capability_id="fixture-requirement-delivery",
            operation="observe",
            goal_binding=_goal_binding(state_file, operations=["different"]),
            provider_input=_provider_input(),
        )


def test_external_capability_rejects_wrong_goal_capability(tmp_path: Path) -> None:
    state_file = _installed_extension(tmp_path)
    goal_binding = _goal_binding(state_file)
    goal_binding["capability_id"] = "different-capability"

    with pytest.raises(ValueError, match="capability_id does not match"):
        invoke_external_capability(
            state_file=state_file,
            capability_id="fixture-requirement-delivery",
            operation="observe",
            goal_binding=goal_binding,
            provider_input=_provider_input(),
        )


def test_external_capability_rejects_stale_goal_provider_binding(
    tmp_path: Path,
) -> None:
    state_file = _installed_extension(tmp_path)

    with pytest.raises(ValueError, match="active provider revision"):
        invoke_external_capability(
            state_file=state_file,
            capability_id="fixture-requirement-delivery",
            operation="observe",
            goal_binding=_goal_binding(
                state_file,
                revision="sha256:stale-provider-revision",
            ),
            provider_input=_provider_input(),
        )


def test_external_capability_rejects_stale_goal_profile_binding(
    tmp_path: Path,
) -> None:
    state_file = _installed_extension(tmp_path)
    goal_binding = _goal_binding(state_file)
    provider = goal_binding["provider"]
    assert isinstance(provider, dict)
    provider["profile_digest"] = "sha256:stale-integration-profile"

    with pytest.raises(ValueError, match="active provider revision/profile"):
        invoke_external_capability(
            state_file=state_file,
            capability_id="fixture-requirement-delivery",
            operation="observe",
            goal_binding=goal_binding,
            provider_input=_provider_input(),
        )


@pytest.mark.parametrize(
    ("observation", "match"),
    [
        ({"access_token": "synthetic-secret-value"}, "credential-bearing field"),
        (
            {"nested": [{"apiKey": "synthetic-secret-value"}]},
            "credential-bearing field",
        ),
        (
            {"nested": [{"providerToken": "synthetic-secret-value"}]},
            "credential-bearing field",
        ),
        (
            {"nested": {"value": "sk-" + "live-synthetic-abcdefghijklmnop"}},
            "credential-like value",
        ),
        (
            {"nested": {"sk-" + "live-synthetic-abcdefghijklmnop": "value"}},
            "unsafe field name",
        ),
        (
            {"nested": [{"path": "/" + "home/example/private.txt"}]},
            "absolute local path",
        ),
        (
            {"nested": {"path": "C:" + "\\Users\\example\\private.txt"}},
            "absolute local path",
        ),
        ({"responseBody": {"status": "ok"}}, "unbounded payload field"),
    ],
)
def test_read_only_result_rejects_nested_private_material(
    observation: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        validate_external_capability_result(
            _external_result([observation]),
            invocation_id="capability-fixture",
            operation={
                "effect_class": "read_only",
                "result_schema": "loopx_external_domain_capability_result_v0",
            },
        )


def test_read_only_result_accepts_bounded_noncredential_metadata() -> None:
    result = validate_external_capability_result(
        _external_result(
            [
                {
                    "token_count": 12,
                    "path_hint": "docs/reference/extensions.md",
                    "nested": [{"status": "ready"}],
                }
            ]
        ),
        invocation_id="capability-fixture",
        operation={
            "effect_class": "read_only",
            "result_schema": "loopx_external_domain_capability_result_v0",
        },
    )

    assert result["observations"][0]["token_count"] == 12


def test_capability_invoke_cli_uses_managed_runtime(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_file = _installed_extension(tmp_path)
    registry_path = _registry(tmp_path / "registry.json")
    provider_input = tmp_path / "provider-input.json"
    provider_input.write_text(json.dumps(_provider_input()), encoding="utf-8")

    assert (
        main(
            [
                "--registry",
                str(registry_path),
                "--format",
                "json",
                "capability",
                "bind",
                "fixture-requirement-delivery",
                "--goal-id",
                "fixture-goal",
                "--operation",
                "observe",
                "--state-file",
                str(state_file),
                "--execute",
            ]
        )
        == 0
    )
    binding_receipt = json.loads(capsys.readouterr().out)
    assert binding_receipt["status"] == "written"
    assert binding_receipt["turn_required"] is False

    assert (
        main(
            [
                "--registry",
                str(registry_path),
                "--format",
                "json",
                "capability",
                "invoke",
                "fixture-requirement-delivery",
                "--operation",
                "observe",
                "--goal-id",
                "fixture-goal",
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
    assert payload["provider_result"]["observations"][0]["requirement_ref"] == ("REQ-1")


def test_capability_bind_cli_resolves_registry_runtime_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_root = tmp_path / "runtime"
    provider = _provider(tmp_path / "provider")
    _profile(tmp_path / "profile.json")
    manifest = _manifest(tmp_path / "extension.toml", provider=provider)
    install_extension(
        manifest,
        state_file=default_extension_state_file(runtime_root),
        execute=True,
    )
    registry_path = _registry(
        tmp_path / "registry.json",
        runtime_root=runtime_root,
    )

    assert (
        main(
            [
                "--registry",
                str(registry_path),
                "--format",
                "json",
                "capability",
                "bind",
                "fixture-requirement-delivery",
                "--goal-id",
                "fixture-goal",
                "--operation",
                "observe",
                "--execute",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "written"
