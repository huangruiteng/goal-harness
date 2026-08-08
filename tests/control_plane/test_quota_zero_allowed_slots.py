from __future__ import annotations

import pytest

from loopx.quota import goal_quota_config, quota_status


GOAL_ID = "zero-allowed-slots-fixture"


def _goal(**quota: object) -> dict[str, object]:
    return {
        "id": GOAL_ID,
        "quota": {
            "compute": 1.0,
            "window_hours": 24,
            "slot_minutes": 1,
            **quota,
        },
    }


@pytest.mark.parametrize("spent_slots", [0, 1, 99])
def test_zero_allowed_slots_throttles_instead_of_running_unbounded(
    spent_slots: int,
) -> None:
    """`allowed_slots: 0` is the strictest cap, not an absence of one.

    `docs/quota-allocation.md` documents `allowed_slots` as an explicit override
    for "a deliberately stricter experimental cap", and states that
    `spent_slots >= allowed_slots` must project `throttled`. Treating 0 as
    unlimited inverts the operator's intent on the safety mechanism itself.
    """

    payload = quota_status(
        _goal(allowed_slots=0, spent_slots=spent_slots), waiting_on="codex"
    )

    assert payload["allowed_slots"] == 0, payload
    assert payload["state"] == "throttled", payload
    assert "0" in payload["reason"], payload


@pytest.mark.parametrize(
    ("allowed_slots", "spent_slots", "expected"),
    [
        (1, 0, "eligible"),
        (1, 1, "throttled"),
        (10, 9, "eligible"),
        (10, 10, "throttled"),
        (10, 11, "throttled"),
    ],
)
def test_nonzero_allowed_slots_boundary_is_unchanged(
    allowed_slots: int, spent_slots: int, expected: str
) -> None:
    payload = quota_status(
        _goal(allowed_slots=allowed_slots, spent_slots=spent_slots),
        waiting_on="codex",
    )

    assert payload["state"] == expected, payload


def test_zero_compute_still_reports_paused_not_throttled() -> None:
    """`compute: 0` is the pause control and keeps precedence over the cap."""

    payload = quota_status(
        _goal(compute=0, allowed_slots=0, spent_slots=5), waiting_on="codex"
    )

    assert payload["state"] == "paused", payload


def test_window_derived_default_stays_eligible_for_normal_config() -> None:
    """The documented default must not collapse to a throttling cap."""

    config = goal_quota_config(_goal(compute=0.01))

    assert config["allowed_slots"] == 14, config
    assert (
        quota_status(_goal(compute=0.01, spent_slots=0), waiting_on="codex")["state"]
        == "eligible"
    )
