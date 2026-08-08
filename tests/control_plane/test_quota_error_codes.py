from __future__ import annotations

import json

import pytest

from loopx.control_plane.quota.error_codes import quota_error_code


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ValueError("bad argument"), "quota_invalid_arguments"),
        (OSError("state unavailable"), "quota_state_io_failed"),
        (PermissionError("state denied"), "quota_state_permission_denied"),
        (KeyError("missing"), "quota_state_missing_field"),
        (TypeError("bad shape"), "quota_state_shape_error"),
        (
            json.JSONDecodeError("invalid json", "doc", 0),
            "quota_state_invalid_json",
        ),
        (RuntimeError("unexpected"), "quota_unexpected_collection_error"),
    ],
)
def test_quota_error_code_maps_typed_exceptions(
    exc: BaseException,
    expected: str,
) -> None:
    assert quota_error_code(exc) == expected
