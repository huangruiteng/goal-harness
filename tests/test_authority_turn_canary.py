from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_two_process_authority_turn_canary_fences_stale_epoch() -> None:
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(
                repository
                / "examples"
                / "nokv-shadow-provider"
                / "authority_turn_canary.py"
            ),
        ],
        cwd=repository,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["provider"] == "FileCoordinationProvider(TEST_ONLY)"
    assert payload["race"]["host_count"] == 1
    assert payload["race"]["rejected_before_host"] is True
    assert {"claim_work", "renew_work", "complete_work"}.issubset(
        payload["race"]["authority_commands"]
    )
    assert (
        payload["expiry_reclaim"]["new_epoch"] > payload["expiry_reclaim"]["old_epoch"]
    )
    assert payload["expiry_reclaim"]["reclaim_grace_seconds"] == 3.0
    assert payload["expiry_reclaim"]["blocked_before_expiry_plus_grace"] is True
    assert payload["expiry_reclaim"]["early_reclaimer_host_count"] == 0
    assert payload["expiry_reclaim"]["stale_holder_later_effects"] == 0
    assert {"claim_work", "renew_work", "reclaim_work", "complete_work"}.issubset(
        payload["expiry_reclaim"]["authority_commands"]
    )
    assert payload["crash_resume"] == {
        "crash_exit_code": 73,
        "same_agent": True,
        "same_turn_journal": True,
        "original_binding_reused": True,
        "host_count": 1,
        "writeback_count": 1,
        "quota_spend_count": 1,
        "scheduler_count": 1,
        "recovery_host_invoked": False,
        "claim_work_count": 1,
    }
    assert payload["provider_unavailable"] == {
        "failed_closed_at_admission": True,
        "reason_code": "authority_guard_unavailable",
        "host_count": 0,
    }
    assert (
        "does not claim arbitrary workspace-effect exactly-once" in payload["boundary"]
    )
