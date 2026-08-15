#!/usr/bin/env python3
"""Smoke-test the content-ops layout template and acceptance contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.content_ops.layout import check_layout_packet  # noqa: E402


def _run(*args: str, check: bool = True) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "loopx.cli", "--format", "json", *args],
        cwd=REPO_ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(result.stdout)


def _measurement(*, sparse_page: str | None = None) -> dict[str, Any]:
    pages = []
    for index in range(1, 6):
        page_id = f"p{index:02d}"
        bottom = 1364 if page_id != sparse_page else 700
        pages.append(
            {
                "page_id": page_id,
                "asset_ref": f"images/{page_id}.jpg",
                "canvas": {"width": 1440, "height": 1920},
                "meaningful_content_bounds": {"top": 154, "bottom": bottom},
                "checks": {
                    "overflow": False,
                    "collision": False,
                    "single_character_line": False,
                },
            }
        )
    return {
        "schema_version": "content_ops_layout_measurement_v0",
        "plan_id": "layout:dsh-plugin-scaling:light-serif-longform",
        "template_id": "light-serif-longform",
        "pages": pages,
    }


def main() -> int:
    catalog = _run("content-ops", "template-list")
    assert catalog["ok"] is True, catalog
    assert catalog["template_count"] == 4, catalog
    assert {
        "light-serif-longform",
        "monochrome-editorial",
        "product-brief",
        "control-plane-hybrid",
    } == {template["template_id"] for template in catalog["templates"]}

    template = _run(
        "content-ops",
        "template-show",
        "--template-id",
        "light-serif-longform",
    )
    assert template["template"]["canvas"] == {"width": 1440, "height": 1920}
    assert template["template"]["density"]["default_min"] == 0.66

    missing_template = _run(
        "content-ops",
        "template-show",
        "--template-id",
        "missing-template",
        check=False,
    )
    assert missing_template["ok"] is False, missing_template
    assert "unknown content-ops layout template" in missing_template["error"]

    plan_packet = _run(
        "content-ops",
        "layout-plan",
        "--item-id",
        "dsh-plugin-scaling",
        "--template-id",
        "light-serif-longform",
        "--page",
        "p01:cover:dsh",
        "--page",
        "p02:argument:dsh",
        "--page",
        "p03:mechanism:dsh",
        "--page",
        "p04:evidence:dsh",
        "--page",
        "p05:closing:loopx",
        "--required-role",
        "cover",
        "--required-role",
        "argument",
        "--required-role",
        "evidence",
        "--required-role",
        "closing",
        "--closing-role",
        "closing",
        "--generated-at",
        "2026-08-15T12:00:00+08:00",
    )
    assert plan_packet["ok"] is True, plan_packet
    assert plan_packet["plan"]["pages"][-1] == {
        "page_id": "p05",
        "role": "closing",
        "subject_id": "loopx",
    }

    with tempfile.TemporaryDirectory() as tmp:
        plan_path = Path(tmp) / "plan.json"
        measurement_path = Path(tmp) / "measurement.json"
        plan_path.write_text(json.dumps(plan_packet), encoding="utf-8")
        measurement_path.write_text(json.dumps(_measurement()), encoding="utf-8")
        accepted = _run(
            "content-ops",
            "layout-check",
            "--plan-json",
            str(plan_path),
            "--measurement-json",
            str(measurement_path),
        )
    assert accepted["ok"] is True, accepted
    assert accepted["status"] == "pass", accepted
    assert accepted["autopublish_allowed"] is False, accepted

    sparse = _measurement(sparse_page="p02")
    rejected = check_layout_packet(plan_packet, sparse)
    assert rejected["status"] == "revise", rejected
    codes = {failure["code"] for failure in rejected["failures"]}
    assert "content_too_sparse" in codes, rejected

    wrong_plan = _measurement()
    wrong_plan["plan_id"] = "layout:another-item:light-serif-longform"
    mismatched = check_layout_packet(plan_packet, wrong_plan)
    assert mismatched["status"] == "revise", mismatched
    assert "plan_id_mismatch" in {
        failure["code"] for failure in mismatched["failures"]
    }, mismatched

    unsafe = _measurement()
    unsafe["pages"][0]["asset_ref"] = "file:private-page.jpg"
    try:
        check_layout_packet(plan_packet, unsafe)
    except ValueError as exc:
        assert "public-safe relative reference" in str(exc)
    else:
        raise AssertionError("absolute asset_ref was accepted")

    print("content-ops-layout-library-smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
