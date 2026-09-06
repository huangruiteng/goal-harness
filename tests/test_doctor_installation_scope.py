from __future__ import annotations

import pytest

from loopx import doctor


@pytest.mark.parametrize(
    "failed_check",
    [None, "typescript_effect_runtime_ready", "representative_cli_imports"],
)
def test_installation_scope_preserves_required_checks_without_opening_user_state(
    monkeypatch, failed_check
):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "installation validation must not inspect user projects/integrations"
        )

    for name in [
        "installed_skill_summary",
        "probe_registry_write_path",
        "latest_promotion_readiness_event",
    ]:
        monkeypatch.setattr(doctor, name, forbidden)
    monkeypatch.setattr(
        "loopx.control_plane.runtime.runtime_projection_route.collect_runtime_projection_route_diagnostics",
        forbidden,
    )
    monkeypatch.setattr(
        "loopx.control_plane.effect_runtime.collect_effect_runtime_readiness",
        lambda *, deep: {
            "ready": failed_check != "typescript_effect_runtime_ready",
            "status": "ready"
            if failed_check != "typescript_effect_runtime_ready"
            else "missing",
            "deep": deep,
        },
    )
    required = [
        "command_package_same_root",
        "representative_cli_commands",
        "representative_cli_imports",
        "representative_package_paths",
    ]
    monkeypatch.setattr(
        "loopx.release_candidate.collect_deep_install_checks",
        lambda **kwargs: {
            "checks": [
                {"id": name, "required": True, "ok": name != failed_check}
                for name in required
            ]
        },
    )
    result = doctor.collect_doctor(deep=True, installation_only=True)
    assert result["scope"] == "installation_only"
    assert result["mode"] == "deep"
    assert result["ok"] is (failed_check is None)
    assert result["typescript_control_plane"]["deep"] is True
    assert set(required) <= {check["id"] for check in result["checks"]}


def test_installation_scope_cannot_claim_host_integration_health():
    from loopx.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(
        ["doctor", "--deep", "--installation-only"]
    ).installation_only
    with pytest.raises(SystemExit):
        parser.parse_args(["doctor", "--installation-only", "--agent-type", "codex"])
