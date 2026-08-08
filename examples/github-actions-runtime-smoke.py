#!/usr/bin/env python3
"""Keep public workflows on official Actions with a native Node 24 runtime."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

NODE24_ACTION_MAJORS = {
    "actions/checkout": "v7",
    "actions/setup-node": "v6",
    "actions/setup-python": "v6",
    "actions/upload-artifact": "v7",
}


def declared_major(reference: str) -> str:
    revision = reference.split("@", 1)[1].split("#", 1)[0].strip()
    if revision.startswith("v"):
        return revision.split(".", 1)[0]

    assert re.fullmatch(r"[0-9a-f]{40}", revision), reference
    annotation = re.search(r"#\s*(v\d+)(?:\.|\s|$)", reference)
    assert annotation is not None, (
        f"immutable action pins need a human-readable major annotation: {reference}"
    )
    return annotation.group(1)


def main() -> int:
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml"))
    )

    for action, major in NODE24_ACTION_MAJORS.items():
        references = [
            line.strip()
            for line in workflow_text.splitlines()
            if f"uses: {action}@" in line
        ]
        assert references, f"missing workflow reference for {action}"
        assert all(declared_major(reference) == major for reference in references), references

    print("github-actions-runtime-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
