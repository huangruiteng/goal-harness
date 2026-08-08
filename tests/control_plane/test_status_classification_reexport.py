from __future__ import annotations

import loopx.control_plane.runtime.status_classifications as classifications
import loopx.status as status


REEXPORTED_NAMES = (
    "CODEX_READY_CLASSIFICATIONS",
    "HANDOFF_READY_CLASSIFICATIONS",
    "DREAMING_ADVISORY_CLASSIFICATIONS",
    "USER_OR_CONTROLLER_CLASSIFICATIONS",
    "BLOCKING_CLASSIFICATIONS",
)


def test_status_reexports_classification_sets_unchanged() -> None:
    for name in REEXPORTED_NAMES:
        status_value = getattr(status, name)
        read_model_value = getattr(classifications, name)
        assert status_value == read_model_value
        assert type(status_value) is type(read_model_value)


def test_status_classification_membership_is_stable() -> None:
    assert "state_refreshed" in status.CODEX_READY_CLASSIFICATIONS
    assert "operator_gate_approved" in status.HANDOFF_READY_CLASSIFICATIONS
    assert "dreaming_refactor_warning" in status.USER_OR_CONTROLLER_CLASSIFICATIONS
    assert "blocked_by_safety" in status.BLOCKING_CLASSIFICATIONS
