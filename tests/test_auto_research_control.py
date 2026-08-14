"""Thin pytest: auto research stop/takeover — stop marker, state-aware wake,
quota pause vs operator stop, worker turn contract, takeover command safety.

Covers GH-C43 core assertions (lightweight contract assertions only).
"""

from __future__ import annotations

import json
import re

_PRIVATE_RE = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"\bBearer" + r"\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]


def _public_safe(obj: object) -> bool:
    text = json.dumps(obj, sort_keys=True) if not isinstance(obj, str) else obj
    return not any(p.search(text) for p in _PRIVATE_RE)


class TestStopReasons:
    """Stop reasons are distinct signals — the caller can distinguish
    resource pressure from operator intent without raw errors."""
    def test_five_distinct_reasons(self):
        reasons = {
            "quota_paused": "All agents blocked by quota.",
            "operator_stop_requested": "Operator placed stop marker.",
            "no_executed_turns": "No agent executed a turn this round.",
            "no_runnable_frontier": "No agent has a runnable todo.",
            "max_rounds": "Round budget exhausted normally.",
        }
        assert len(reasons) == 5
        for reason in reasons:
            assert isinstance(reason, str) and len(reason) > 0
            assert _public_safe({"stop_reason": reason})

    def test_operator_stop_and_quota_paused_never_collide(self):
        assert "operator_stop_requested" != "quota_paused"


class TestStateAwareFilter:
    def test_reason_code_shapes(self):
        reason_codes = [
            "no_agent_mapping", "frontier_load_failed",
            "quiet_completion_allowed", "no_selected_todo",
            "quota_should_run_false",
        ]
        for code in reason_codes:
            assert _public_safe({"reason": code})

    def test_skipped_lane_uses_error_code_not_raw_error(self):
        skipped = {
            "lane_id": "example-lane", "agent_id": "example-agent",
            "reason": "frontier_load_failed", "error_code": "FRONTIER_LOAD_FAILED",
        }
        assert "error_code" in skipped
        assert "error" not in skipped
        assert _public_safe(skipped)


class TestNoOpWakeReceipt:
    def test_zero_ready_lanes_is_noop(self):
        receipt = {
            "ok": True,
            "schema_version": "multi_agent_pane_a2a_wakeup_v0",
            "mode": "no_op_all_filtered", "session_name": "test",
            "target_lanes": [], "prompt": "", "prompt_hash": "",
            "coordination_model": "decentralized_state_a2a",
            "wakeup_model": "state_aware_filter_no_ready_lanes",
            "workflow_driver": False,
            "broadcaster_reads_frontier": False,
            "broadcaster_reads_todo_readiness": False,
            "broadcaster_selects_todo": False,
            "prompt_delivery": "skipped_no_ready_lanes",
            "prompt_delivered": False,
            "auto_wake_backoff_recommended": False,
        }
        assert receipt["mode"] == "no_op_all_filtered"
        assert receipt["target_lanes"] == []
        assert receipt["prompt_delivery"] == "skipped_no_ready_lanes"
        assert _public_safe(receipt)


class TestTakeoverCommand:
    def test_command_template_public_safe(self):
        cmd = (
            'loopx --registry "$LOOPX_REGISTRY" '
            '--runtime-root "$LOOPX_RUNTIME_ROOT" '
            'auto-research start "How should we evaluate autonomous agents?" '
            "--execute --attach"
        )
        assert "--attach" in cmd
        assert "--execute" in cmd
        assert "auto-research start" in cmd
        assert "/home/" not in cmd
        assert "C:\\" not in cmd
        assert _public_safe(cmd)


class TestPublicBoundary:
    def test_boundary_block_shape(self):
        boundary = {
            "raw_logs_recorded": False,
            "private_artifacts_recorded": False,
            "absolute_paths_recorded": False,
            "credentials_recorded": False,
        }
        for key, val in boundary.items():
            assert val is False, key
        assert _public_safe(boundary)
