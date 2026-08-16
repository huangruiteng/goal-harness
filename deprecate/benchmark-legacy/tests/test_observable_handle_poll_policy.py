"""Thin pytest: benchmark observable handle poll policy lifecycle.

Covers GH-C50 core assertions — launch handle, running/completed/failed/missing
policy states, terminal marker detection, no-adapter assumptions, public safety.
"""

from __future__ import annotations

import json
import re

from loopx.benchmark_core.observable_handles import (
    build_benchmark_launch_observable_handle,
    build_benchmark_observable_handle_policy,
)

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


# -- Synthetic snapshots -------------------------------------------------------

def _snapshot(pid="", pid_alive=False, status="", exists=True, results=None):
    return {
        "exists": exists,
        "label": "run-001",
        "pid": pid,
        "pid_alive": pid_alive,
        "status": status,
        "compact_results": results or [],
    }


def _running():
    return _snapshot(pid="42", pid_alive=True, status="running", results=[
        {"summary": {"official_score_status": "running"}}])


def _completed():
    return _snapshot(pid="42", status="complete", results=[{
        "summary": {"official_score_status": "completed", "official_score": 0.85,
                     "n_resolved": 7, "n_unresolved": 3}}])


def _failed():
    return _snapshot(status="exception=timeout", results=[{
        "summary": {"ready_for_compact_failure_marker": True,
                     "compact_failure_class": "timeout",
                     "terminal_closeout": True}}])


# -- Tests --------------------------------------------------------------------

class TestLaunchHandle:
    def test_schema_and_boundary(self):
        h = build_benchmark_launch_observable_handle(
            benchmark_id="test", launch_mode="one_shot",
            process_state="running", will_execute=True,
            read_boundary={"compact_only": True})
        assert h["will_execute"] is True
        assert h["monitor_poll_allowed"] is True
        obs = h["observable_handle"]
        assert obs["raw_handle_payload_recorded"] is False
        assert obs["private_handle_values_recorded"] is False
        poll = h["allowed_poll_command"]
        assert poll["argv_recorded"] is False
        assert poll["requires_private_paths"] is False
        rb = h["read_boundary"]
        assert rb["compact_only"] is True
        assert not rb["raw_logs_read"]
        assert not rb["trajectory_read"]
        b = h["boundary"]
        assert not b["scheduler_payload_recorded"]
        assert not b["credential_values_recorded"]
        assert _public_safe(h)

    def test_scheduler_kinds(self):
        for sk in ("manual", "systemd", "launchd", "custom-cron"):
            h = build_benchmark_launch_observable_handle(
                benchmark_id="x", launch_mode="one_shot", scheduler_kind=sk)
            assert h["scheduler_kind"] == sk


class TestPollPolicyStates:
    def test_running_next_action_is_poll(self):
        p = build_benchmark_observable_handle_policy(_running())
        assert p["next_action"] == "poll_observable_handle"
        assert not p["terminal_closeout"]
        assert p["monitor_poll_allowed"]
        assert p["observable_handle"]["state"] == "running"
        assert p["observable_handle"]["pid_alive"]
        assert _public_safe(p)

    def test_completed_closeout(self):
        p = build_benchmark_observable_handle_policy(_completed())
        assert p["terminal_closeout"]
        assert p["compact_result_closeout"]
        assert not p["monitor_poll_allowed"]
        assert p["cleanup_required"]
        assert p["next_action"] == (
            "disable_one_shot_scheduler_label_and_ingest_compact_closeout")
        assert p["observable_handle"]["state"] == "ended"
        assert _public_safe(p)

    def test_failed_closeout(self):
        p = build_benchmark_observable_handle_policy(_failed())
        assert p["terminal_closeout"]
        assert p["compact_failure_closeout"]
        assert not p["monitor_poll_allowed"]
        assert p["cleanup_required"]
        assert "ingest_compact_closeout" in p["next_action"]
        assert _public_safe(p)

    def test_missing_directory_writes_blocker(self):
        p = build_benchmark_observable_handle_policy(
            {"exists": False, "label": "x", "pid": "", "pid_alive": False,
             "status": "", "compact_results": []})
        assert p["next_action"] == "write_missing_run_directory_blocker"
        assert not p["terminal_closeout"]
        assert p["observable_handle"]["state"] == "not_found"
        assert _public_safe(p)

    def test_non_benchmark_artifact_shape(self):
        p = build_benchmark_observable_handle_policy(
            _snapshot(pid="1001", pid_alive=True, status="generating", results=[
                {"summary": {"artifacts_produced": 5, "format": "pdf"}}]))
        assert p["next_action"] == "poll_observable_handle"
        assert p["monitor_poll_allowed"]

    def test_rc_exit_without_closeout_is_not_terminal(self):
        p = build_benchmark_observable_handle_policy(
            _snapshot(status="rc=0"))
        assert not p["terminal_closeout"]
        assert p["blocker_required_before_rerun"]
        assert _public_safe(p)

    def test_scored_is_terminal(self):
        p = build_benchmark_observable_handle_policy(_snapshot(
            status="completed", results=[
                {"summary": {"official_score_status": "scored",
                             "official_score": 0.92}}]))
        assert p["terminal_closeout"]

    def test_failure_attribution_is_terminal(self):
        p = build_benchmark_observable_handle_policy(_snapshot(
            status="exception=crash", results=[
                {"summary": {"score_failure_attribution": "env-failure"}}]))
        assert p["terminal_closeout"]


class TestFullPollCycle:
    def test_launch_to_terminal(self):
        h = build_benchmark_launch_observable_handle(
            benchmark_id="cycle", launch_mode="one_shot",
            process_state="queued", will_execute=True)
        assert h["will_execute"]

        p1 = build_benchmark_observable_handle_policy(_running())
        assert p1["next_action"] == "poll_observable_handle"

        p2 = build_benchmark_observable_handle_policy(_running())
        assert p2["next_action"] == "poll_observable_handle"

        p3 = build_benchmark_observable_handle_policy(_completed())
        assert p3["terminal_closeout"]
        assert "ingest_compact_closeout" in p3["next_action"]
