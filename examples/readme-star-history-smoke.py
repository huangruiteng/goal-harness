#!/usr/bin/env python3
"""Validate the deterministic README star-history generation path."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render-star-history.py"
IMAGE_URL = "https://huangruiteng.github.io/loopx/site-assets/star-history.svg"


def _render(fixture: object, output: Path) -> str:
    fixture_path = output.with_suffix(".json")
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            "huangruiteng/loopx",
            "--input-json",
            str(fixture_path),
            "--as-of",
            "2026-08-06",
            "--output",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output.read_text(encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-star-history-") as tmp:
        temp = Path(tmp)
        svg = _render(
            [
                [
                    {"starred_at": "2026-05-01T00:00:00Z"},
                    {"starred_at": "2026-05-01T12:00:00Z"},
                ],
                [
                    {"starred_at": "2026-07-15T08:30:00Z"},
                    {"starred_at": "2026-08-01T09:45:00Z"},
                ],
            ],
            temp / "history.svg",
        )
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")
        assert "huangruiteng/loopx · 4 stars · updated 2026-08-06" in svg
        assert "<script" not in svg.lower()
        assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "")
        assert "https://" not in svg

        empty_svg = _render([], temp / "empty.svg")
        assert "huangruiteng/loopx · 0 stars · updated 2026-08-06" in empty_svg

    for readme in (ROOT / "README.md", ROOT / "README.zh-CN.md"):
        text = readme.read_text(encoding="utf-8")
        assert text.count(IMAGE_URL) == 1, readme
        assert "https://github.com/huangruiteng/loopx/stargazers" in text, readme

    print("readme star history smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
