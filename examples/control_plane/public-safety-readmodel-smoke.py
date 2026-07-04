#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loopx import status as status_module  # noqa: E402
from loopx.control_plane.runtime import public_safety as public_safety_read_model  # noqa: E402


def _direct_text(value: object, *, limit: int = 220) -> str | None:
    return public_safety_read_model.public_safe_compact_text(
        value,
        limit=limit,
        normalize_text=status_module.normalize_todo_text,
        local_path_surface_pattern=status_module.LOCAL_PATH_SURFACE_PATTERN,
        secret_like_surface_pattern=status_module.SECRET_LIKE_SURFACE_PATTERN,
    )


def assert_public_safe_text_parity() -> None:
    assert status_module.public_safe_compact_text("  keep\nthis  value ") == "keep this value"
    assert status_module.public_safe_compact_text("  keep\nthis  value ") == _direct_text(
        "  keep\nthis  value "
    )
    assert status_module.public_safe_compact_text("") is None
    assert status_module.public_safe_compact_text("") == _direct_text("")

    local_path = "/" + "tmp" + "/loopx-public-boundary-probe.json"
    secret_like_text = "tok" + "en" + "=" + ("x" * 12)
    assert status_module.public_safe_compact_text(local_path) is None
    assert status_module.public_safe_compact_text(local_path) == _direct_text(local_path)
    assert status_module.public_safe_compact_text(secret_like_text) is None
    assert status_module.public_safe_compact_text(secret_like_text) == _direct_text(secret_like_text)


def assert_public_safe_list_parity() -> None:
    local_path = "/" + "tmp" + "/loopx-public-boundary-probe.json"
    values = ["first", local_path, "second", "third"]
    expected = ["first", "second"]
    assert status_module.public_safe_compact_list(values, limit=2) == expected
    assert public_safety_read_model.public_safe_compact_list(
        values,
        limit=2,
        compact_text=_direct_text,
    ) == expected
    assert status_module.public_safe_compact_list("single", limit=4) == ["single"]


def main() -> None:
    assert_public_safe_text_parity()
    assert_public_safe_list_parity()


if __name__ == "__main__":
    main()
