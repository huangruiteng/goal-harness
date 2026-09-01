from __future__ import annotations

import json
from pathlib import Path

from loopx.canary.premerge import classify_premerge_surfaces
from loopx.contract import scan_public_boundary


def _write_lockfile(path: Path, resolved: str) -> None:
    path.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {},
                    "node_modules/example": {
                        "version": "1.0.0",
                        "resolved": resolved,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_public_boundary_accepts_public_npm_lockfile_source(tmp_path: Path) -> None:
    lockfile = tmp_path / "package-lock.json"
    _write_lockfile(
        lockfile,
        "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
    )

    result = scan_public_boundary([lockfile])

    assert result["ok"] is True
    assert result["hits"] == []


def test_public_boundary_rejects_non_public_lockfile_source(tmp_path: Path) -> None:
    lockfile = tmp_path / "package-lock.json"
    _write_lockfile(lockfile, "https://packages.example.invalid/example-1.0.0.tgz")

    result = scan_public_boundary([lockfile])

    assert result["ok"] is False
    assert result["hits"] == [
        "package-lock.json: non_public_package_registry (node_modules/example)"
    ]


def test_public_boundary_allows_local_lockfile_source(tmp_path: Path) -> None:
    lockfile = tmp_path / "package-lock.json"
    _write_lockfile(lockfile, "file:../tracked-package")

    result = scan_public_boundary([lockfile])

    assert result["ok"] is True


def test_changed_lockfile_selects_premerge_public_boundary(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")

    result = classify_premerge_surfaces(
        ["package-lock.json"],
        repo_root=tmp_path,
    )

    assert result["public_boundary_scan_recommended"] is True
    assert "public_boundary" in result["surfaces"]
