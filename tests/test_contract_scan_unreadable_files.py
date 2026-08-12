from __future__ import annotations

import os
from pathlib import Path

import pytest

from loopx.contract import iter_scan_files, scan_public_boundary


def test_iter_scan_files_skips_dangling_symlink(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "ok.md").write_text("hello\n", encoding="utf-8")
    (package / "dangling.json").symlink_to("../missing-target.json")

    scanned = iter_scan_files(tmp_path)

    assert [path.name for path in scanned] == ["ok.md"]


def test_scan_public_boundary_survives_dangling_symlink(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "ok.md").write_text("hello\n", encoding="utf-8")
    (package / "dangling.json").symlink_to("../missing-target.json")

    payload = scan_public_boundary([tmp_path])

    assert payload["ok"] is True
    assert payload["scanned_files"] == 1
    assert payload["unreadable_files"] == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads mode 000 files")
def test_scan_public_boundary_reports_unreadable_file(tmp_path: Path) -> None:
    (tmp_path / "ok.md").write_text("hello\n", encoding="utf-8")
    locked = tmp_path / "locked.md"
    locked.write_text("hello\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        payload = scan_public_boundary([tmp_path])
    finally:
        locked.chmod(0o644)

    assert payload["ok"] is True
    assert payload["unreadable_files"] == ["locked.md: Permission denied"]
