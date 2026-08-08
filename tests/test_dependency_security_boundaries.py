from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUPTOOLS_FLOOR = (83, 0, 0)


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_setuptools_security_floor_is_declared_at_each_dependabot_boundary() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build_requirements = project["build-system"]["requires"]
    root_match = next(
        re.fullmatch(r"setuptools==([0-9]+(?:\.[0-9]+)*)", requirement)
        for requirement in build_requirements
        if requirement.startswith("setuptools")
    )
    assert root_match is not None

    docs_requirements = (ROOT / "docs" / "requirements-docs.txt").read_text(
        encoding="utf-8"
    )
    docs_match = re.search(
        r"^setuptools>=([0-9]+(?:\.[0-9]+)*),<([0-9]+)$",
        docs_requirements,
        flags=re.MULTILINE,
    )
    assert docs_match is not None

    root_version = _version_tuple(root_match.group(1))
    docs_floor = _version_tuple(docs_match.group(1))
    assert root_version >= SETUPTOOLS_FLOOR
    assert docs_floor == root_version
    assert int(docs_match.group(2)) == root_version[0] + 1
