"""Tests for the heartbeat pre-quota hook registry integration (P3)."""

from __future__ import annotations

from pathlib import Path

from loopx.heartbeat_prequota import (
    PRE_QUOTA_HOOK_POINT,
    get_pre_quota_hook_registry,
    register_pre_quota_hook,
    render_heartbeat_pre_quota_markdown,
    run_heartbeat_pre_quota,
)


def _run(**overrides):
    return run_heartbeat_pre_quota(
        registry_path=Path("/tmp/loopx-heartbeat-test-registry"),
        runtime_root_arg=None,
        goal_id="goal-1",
        agent_id="agent-1",
        fetch_timeout_seconds=10,
        **overrides,
    )


def _drop_test_hook(hook):
    registry = get_pre_quota_hook_registry()
    registry._hooks[PRE_QUOTA_HOOK_POINT] = [
        (source, fn)
        for (source, fn) in registry._hooks.get(PRE_QUOTA_HOOK_POINT, [])
        if fn is not hook
    ]


def test_run_heartbeat_pre_quota_includes_builtin_hook():
    payload = _run()
    assert payload["ok"] is True
    checks = payload["checks"]
    # Built-in issue-fix reconcile hook is always present by name.
    assert "issue_fix_pr_review_reconcile_hook" in checks["hooks"]
    # Legacy compatibility key is preserved.
    assert isinstance(checks["acknowledged_pr_reviews"], dict)
    assert payload["continue_to_quota"] is True


def test_run_heartbeat_pre_quota_fans_out_to_registered_hooks():
    def custom_hook(*, goal_id, **kwargs):
        return {"ok": True, "hook": "custom", "goal": goal_id}

    register_pre_quota_hook(custom_hook, source="test-pack")
    try:
        payload = _run()
    finally:
        _drop_test_hook(custom_hook)

    hooks = payload["checks"]["hooks"]
    assert hooks["custom_hook"]["goal"] == "goal-1"
    assert payload["degraded"] is False
    assert payload["failure_count"] == 0


def test_run_heartbeat_pre_quota_isolates_failing_hook():
    def failing_hook(**kwargs):
        raise RuntimeError("hook boom")

    register_pre_quota_hook(failing_hook, source="bad-pack")
    try:
        payload = _run()
    finally:
        _drop_test_hook(failing_hook)

    assert payload["degraded"] is True
    assert payload["failure_count"] >= 1
    hooks = payload["checks"]["hooks"]
    assert hooks["failing_hook"]["failure_count"] == 1


def test_run_heartbeat_pre_quota_ignores_non_mapping_results():
    def weird_hook(**kwargs):
        return "not-a-dict"

    register_pre_quota_hook(weird_hook, source="weird-pack")
    try:
        payload = _run()
    finally:
        _drop_test_hook(weird_hook)

    hooks = payload["checks"]["hooks"]
    assert hooks["weird_hook"] == {}


def test_render_heartbeat_pre_quota_markdown_compat_paths():
    # Missing acknowledged_pr_reviews degrades to defaults.
    rendered = render_heartbeat_pre_quota_markdown({"ok": True, "checks": {}})
    assert "reconciled_count: `0`" in rendered
    assert "# LoopX Heartbeat Pre-Quota" in rendered

    # A populated review reconciliation is projected through the legacy key.
    payload = {
        "ok": True,
        "degraded": False,
        "failure_count": 0,
        "checks": {"acknowledged_pr_reviews": {"reconciled_count": 7}},
    }
    rendered = render_heartbeat_pre_quota_markdown(payload)
    assert "reconciled_count: `7`" in rendered
