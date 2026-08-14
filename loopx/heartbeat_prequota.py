from __future__ import annotations

from pathlib import Path
from typing import Any

from .capabilities.issue_fix.pr_gate_reconcile import (
    reconcile_acknowledged_issue_fix_pr_reviews,
)
from .control_plane.capabilities_bridge import CapabilityHookRegistry


HEARTBEAT_PRE_QUOTA_SCHEMA_VERSION = "heartbeat_pre_quota_v0"

# Hook point for best-effort, no-quota reconciliation hooks that run before the
# heartbeat quota decision. Capability packs self-register under this point so
# this module no longer needs a static import per pack.
PRE_QUOTA_HOOK_POINT = "pre_quota"

# A process-wide hook registry. Capability packs (and tests) register their
# pre-quota hooks here; the host flow runs whatever is registered.
_capability_hook_registry = CapabilityHookRegistry()


def issue_fix_pr_review_reconcile_hook(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    agent_id: str,
    fetch_timeout_seconds: int = 10,
) -> dict[str, Any]:
    """The built-in issue-fix PR-review reconcile hook (legacy default)."""
    try:
        review_reconciliation = reconcile_acknowledged_issue_fix_pr_reviews(
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            goal_id=goal_id,
            agent_id=agent_id,
            project=None,
            fetch_metadata=True,
            fetch_timeout_seconds=fetch_timeout_seconds,
            execute=True,
        )
        return {
            "ok": True,
            "hook": "issue_fix_pr_review_reconcile",
            "degraded": bool(review_reconciliation.get("degraded")),
            "failure_count": int(review_reconciliation.get("failure_count") or 0),
            "review_reconciliation": review_reconciliation,
        }
    except Exception as exc:  # noqa: BLE001 - best-effort hook
        return {
            "ok": False,
            "hook": "issue_fix_pr_review_reconcile",
            "degraded": True,
            "failure_count": 1,
            "failure_categories": [type(exc).__name__],
        }


def register_pre_quota_hook(hook: Any, *, source: str = "") -> None:
    """Register a capability-pack pre-quota hook (public extension point).

    Hook contract: ``hook(*, registry_path, runtime_root_arg, goal_id, agent_id,
    fetch_timeout_seconds=10) -> dict``. The hook is invoked with exactly these
    keyword arguments; a hook whose signature does not accept them is treated as
    failed (``degraded``). The returned dict is merged into the pre-quota
    ``checks.hooks`` result keyed by the hook's ``__name__`` (falling back to
    ``"hook"`` for anonymous callables). Hooks that raise or return a non-dict
    value are reported as failures without breaking the other hooks.
    """
    _capability_hook_registry.register(PRE_QUOTA_HOOK_POINT, hook, source=source)


def get_pre_quota_hook_registry() -> CapabilityHookRegistry:
    """Expose the process-wide registry (for inspection/testing)."""
    return _capability_hook_registry


def run_heartbeat_pre_quota(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    agent_id: str,
    fetch_timeout_seconds: int = 10,
) -> dict[str, Any]:
    """Run pre-quota checks, fanning out to registered capability hooks.

    Returns ``{"ok", "schema_version", "goal_id", "agent_id", "degraded",
    "failure_count", "checks": {"acknowledged_pr_reviews", "hooks"}, ...}``.
    Each hook result is keyed in ``checks.hooks`` by the hook ``__name__``;
    the legacy ``checks.acknowledged_pr_reviews`` key is preserved as the
    built-in issue-fix reconcile projection so downstream renderers keep
    working unchanged. See ``register_pre_quota_hook`` for the hook contract.
    """
    # Collect hooks from the registry, always including the built-in issue-fix
    # reconcile hook so behavior is unchanged when no pack has registered.
    hooks = _capability_hook_registry.hooks_for(PRE_QUOTA_HOOK_POINT)
    if not any(getattr(h, "__name__", "") == "issue_fix_pr_review_reconcile_hook" for h in hooks):
        hooks = [*hooks, issue_fix_pr_review_reconcile_hook]

    degraded = False
    failure_count = 0
    checks: dict[str, Any] = {}

    for hook in hooks:
        try:
            result = hook(
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                goal_id=goal_id,
                agent_id=agent_id,
                fetch_timeout_seconds=fetch_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - isolate hook failures
            result = {
                "ok": False,
                "degraded": True,
                "failure_count": 1,
                "failure_categories": [type(exc).__name__],
            }
        if not isinstance(result, dict):
            result = {}
        if result.get("degraded"):
            degraded = True
        failure_count += int(result.get("failure_count") or 0)
        # Key by the hook callable name so the built-in issue-fix hook can be
        # located deterministically for the compatibility projection below.
        hook_name = getattr(hook, "__name__", None) or str(result.get("hook") or "hook")
        checks[hook_name] = result

    # Preserve the legacy ``acknowledged_pr_reviews`` key for compatibility.
    review_reconciliation = checks.get("issue_fix_pr_review_reconcile_hook", {})
    acknowledged = review_reconciliation.get("review_reconciliation", review_reconciliation)

    return {
        "ok": True,
        "schema_version": HEARTBEAT_PRE_QUOTA_SCHEMA_VERSION,
        "goal_id": goal_id,
        "agent_id": agent_id,
        "degraded": degraded,
        "failure_count": failure_count,
        "checks": {
            "acknowledged_pr_reviews": acknowledged,
            "hooks": checks,
        },
        "quota_spend_required": False,
        "continue_to_quota": True,
    }


def render_heartbeat_pre_quota_markdown(payload: dict[str, Any]) -> str:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    review = (
        checks.get("acknowledged_pr_reviews")
        if isinstance(checks.get("acknowledged_pr_reviews"), dict)
        else {}
    )
    return "\n".join(
        [
            "# LoopX Heartbeat Pre-Quota",
            "",
            f"- ok: `{payload.get('ok')}`",
            f"- degraded: `{payload.get('degraded')}`",
            f"- reconciled_count: `{review.get('reconciled_count', 0)}`",
            f"- failure_count: `{payload.get('failure_count')}`",
            f"- continue_to_quota: `{payload.get('continue_to_quota')}`",
            "- quota_spend_required: `False`",
        ]
    )
