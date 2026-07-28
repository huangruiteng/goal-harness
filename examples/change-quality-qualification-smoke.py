#!/usr/bin/env python3
"""Smoke-test default-off policy, exact receipts, and strict stale-diff rejection."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.change_quality.receipt import (  # noqa: E402
    CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
    build_change_quality_prepare_packet,
    record_change_quality_receipt,
    verify_change_quality_receipt,
)
from loopx.configure_goal import configure_goal  # noqa: E402


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-change-quality-") as temporary:
        root = Path(temporary)
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init")
        git(repo, "config", "user.email", "quality-smoke@example.invalid")
        git(repo, "config", "user.name", "Quality Smoke")
        (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
        git(repo, "add", "app.py")
        git(repo, "commit", "-m", "fixture")
        runtime = root / "runtime"
        registry = root / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "common_runtime_root": str(runtime),
                    "goals": [
                        {
                            "id": "quality-smoke",
                            "repo": str(repo),
                            "control_plane": {},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        disabled = build_change_quality_prepare_packet(
            registry_path=registry,
            goal_id="quality-smoke",
            repo_path=repo,
            base_ref="HEAD",
        )
        assert disabled["status"] == "disabled", disabled

        configure_goal(
            registry_path=registry,
            goal_id="quality-smoke",
            change_quality_enabled=True,
            change_quality_safe_fix=True,
            change_quality_strict_receipt=True,
            execute=True,
        )
        (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
        prepared = build_change_quality_prepare_packet(
            registry_path=registry,
            goal_id="quality-smoke",
            repo_path=repo,
            base_ref="HEAD",
        )
        result = root / "result.json"
        result.write_text(
            json.dumps(
                {
                    "schema_version": CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
                    "scope_fingerprint": prepared["scope"]["scope_fingerprint"],
                    "reviewed_final_scope": True,
                    "reuse": {
                        "outcome": "retained",
                        "summary": "The fixture already uses its direct owner.",
                        "evidence_refs": ["path:app.py"],
                    },
                    "simplification": {
                        "outcome": "retained",
                        "summary": "The direct assignment is already minimal.",
                        "evidence_refs": ["path:app.py"],
                        "safe_fix_applied": False,
                    },
                    "risks": [],
                    "validation": [
                        {
                            "validator": "fixture-smoke",
                            "status": "passed",
                            "scope": "exact receipt lifecycle",
                            "required": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        recorded = record_change_quality_receipt(
            registry_path=registry,
            runtime_root=runtime,
            goal_id="quality-smoke",
            repo_path=repo,
            result_path=result,
            base_ref="HEAD",
            execute=True,
        )
        assert recorded["ok"] is True, recorded
        valid = verify_change_quality_receipt(
            registry_path=registry,
            runtime_root=runtime,
            goal_id="quality-smoke",
            repo_path=repo,
            base_ref="HEAD",
        )
        assert valid["status"] == "valid", valid

        (repo / "app.py").write_text("value = 3\n", encoding="utf-8")
        stale = verify_change_quality_receipt(
            registry_path=registry,
            runtime_root=runtime,
            goal_id="quality-smoke",
            repo_path=repo,
            base_ref="HEAD",
        )
        assert stale["ok"] is False, stale
        assert stale["status"] == "stale_receipt", stale

    print(
        json.dumps(
            {
                "schema_version": "change_quality_qualification_smoke_v0",
                "ok": True,
                "default_off": True,
                "exact_receipt_verified": True,
                "stale_diff_rejected": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
