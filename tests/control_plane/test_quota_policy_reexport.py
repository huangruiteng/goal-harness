from __future__ import annotations

import loopx.control_plane.quota.policy_constants as policy_constants
import loopx.quota as quota


REEXPORTED_NAMES = (
    "DEFAULT_COMPUTE_QUOTA",
    "DEFAULT_WINDOW_HOURS",
    "DEFAULT_SLOT_MINUTES",
    "FOCUS_WAIT_LIFECYCLE_MARKERS",
    "FOCUS_WAIT_REASON",
    "AUTONOMOUS_CANDIDATE_CONTEXT_FIELDS",
    "SELF_REPAIR_SPEND_ACTIONS",
    "MONITOR_DUE_ITEM_LIMIT",
)


def test_quota_reexports_policy_constants_unchanged() -> None:
    for name in REEXPORTED_NAMES:
        status_value = getattr(quota, name)
        read_model_value = getattr(policy_constants, name)
        assert status_value == read_model_value
        assert type(status_value) is type(read_model_value)


def test_quota_policy_values_are_stable() -> None:
    assert quota.DEFAULT_COMPUTE_QUOTA == 1.0
    assert quota.DEFAULT_WINDOW_HOURS == 24
    assert quota.DEFAULT_SLOT_MINUTES == 1
    assert "focus_wait" in quota.FOCUS_WAIT_LIFECYCLE_MARKERS
    assert quota.MONITOR_DUE_ITEM_LIMIT == 1
