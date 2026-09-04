"""Focused negative-path smoke for provider runtime recovery contracts."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

contract = importlib.import_module("loopx_codex_provider_routing.contract")
qualify_desktop_patch = contract.qualify_desktop_patch
qualify_outage_recovery = contract.qualify_outage_recovery
qualify_quota_recovery = contract.qualify_quota_recovery
qualify_tool_transport = contract.qualify_tool_transport


def main() -> int:
    desktop_patch = qualify_desktop_patch(
        {
            "anchor_state": "patched_unique",
            "changed_file_count": 2,
            "per_file_integrity_match_count": 2,
            "header_integrity_matches_bundle_metadata": True,
            "signature_valid": True,
            "launch_succeeded": True,
            "heartbeat_readback_succeeded": True,
        }
    )
    assert desktop_patch["qualified"] is True

    stale_asar = qualify_desktop_patch(
        {
            "anchor_state": "unsupported",
            "changed_file_count": 2,
            "per_file_integrity_match_count": 0,
            "header_integrity_matches_bundle_metadata": False,
            "signature_valid": True,
            "launch_succeeded": False,
            "heartbeat_readback_succeeded": False,
        }
    )
    assert stale_asar["qualified"] is False
    assert {
        "desktop_patch_anchor_unsupported",
        "asar_file_integrity_stale",
        "asar_header_integrity_stale",
        "desktop_launch_failed",
        "heartbeat_transport_readback_failed",
    } <= set(stale_asar["failure_codes"])

    outage_recovery = qualify_outage_recovery(
        {
            "outage_ended": True,
            "outage_ended_observed_at": "2026-09-03T16:00:00Z",
            "cooldown_source_observed_at": "2026-09-03T14:50:00Z",
            "cooldown_expires_at": "2026-09-03T18:50:00Z",
            "cooldown_invalidated": True,
            "post_recovery_probe": "success",
            "degraded_fallback_binding_cleared": True,
            "native_capability_requested": True,
            "fallback_attempted": False,
        }
    )
    assert outage_recovery["qualified"] is True
    assert outage_recovery["expected_action"] == (
        "invalidate_cooldown_and_revalidate_affinity"
    )

    stale_outage_state = qualify_outage_recovery(
        {
            "outage_ended": True,
            "outage_ended_observed_at": "2026-09-03T16:00:00Z",
            "cooldown_source_observed_at": "2026-09-03T14:50:00Z",
            "cooldown_expires_at": "2026-09-03T18:50:00Z",
            "cooldown_invalidated": False,
            "post_recovery_probe": "not_attempted",
            "degraded_fallback_binding_cleared": False,
            "native_capability_requested": True,
            "fallback_attempted": True,
        }
    )
    assert stale_outage_state["qualified"] is False
    assert set(stale_outage_state["failure_codes"]) == {
        "stale_outage_cooldown_retained",
        "recovery_probe_missing",
        "fallback_selected_after_recovery_probe",
        "degraded_fallback_binding_used_for_native_request",
    }

    ongoing_outage_native_fallback = qualify_outage_recovery(
        {
            "outage_ended": False,
            "outage_ended_observed_at": None,
            "cooldown_source_observed_at": "2026-09-03T14:50:00Z",
            "cooldown_expires_at": "2026-09-03T18:50:00Z",
            "cooldown_invalidated": False,
            "post_recovery_probe": "not_attempted",
            "degraded_fallback_binding_cleared": False,
            "native_capability_requested": True,
            "fallback_attempted": True,
        }
    )
    assert ongoing_outage_native_fallback["qualified"] is False
    assert ongoing_outage_native_fallback["failure_codes"] == [
        "degraded_fallback_binding_used_for_native_request"
    ]

    quota_recovery = qualify_quota_recovery(
        {
            "reset_outcome": "applied",
            "reset_observed_at": "2026-09-01T11:00:00Z",
            "cooldown_source_observed_at": "2026-09-01T10:00:00Z",
            "cooldown_expires_at": "2026-09-05T10:00:00Z",
            "cooldown_invalidated": True,
            "post_reset_probe": "success",
            "fallback_attempted": False,
        }
    )
    assert quota_recovery["qualified"] is True
    assert quota_recovery["expected_action"] == "invalidate_and_probe"

    stale_cooldown = qualify_quota_recovery(
        {
            "reset_outcome": "applied",
            "reset_observed_at": "2026-09-01T11:00:00Z",
            "cooldown_source_observed_at": "2026-09-01T10:00:00Z",
            "cooldown_expires_at": "2026-09-05T10:00:00Z",
            "cooldown_invalidated": False,
            "post_reset_probe": "not_attempted",
            "fallback_attempted": True,
        }
    )
    assert stale_cooldown["qualified"] is False
    assert set(stale_cooldown["failure_codes"]) == {
        "stale_quota_cooldown_retained",
        "post_reset_probe_missing",
        "fallback_selected_before_recovered_account_probe",
    }

    tool_transport = qualify_tool_transport(
        {
            "requested_transport": "custom_tool_call",
            "observed_transport": "custom_tool_call",
            "dispatch_outcome": "completed",
        }
    )
    assert tool_transport["qualified"] is True

    downgraded_tool = qualify_tool_transport(
        {
            "requested_transport": "custom_tool_call",
            "observed_transport": "function_call",
            "dispatch_outcome": "rejected_incompatible_payload",
        }
    )
    assert downgraded_tool["qualified"] is False
    assert downgraded_tool["responsible_layer"] == "provider_response_adapter"
    assert set(downgraded_tool["failure_codes"]) == {
        "tool_transport_downgraded",
        "tool_dispatch_incomplete",
    }

    print("ok: provider recovery contracts smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
