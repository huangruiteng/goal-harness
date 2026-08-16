#!/usr/bin/env python3
"""Prove a formal LoopX install and optional real app-server skill readback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.benchmark_toolkit.native_codex_goal import (
    NativeGoalConfig,
    compact_native_goal_receipt,
    probe_native_goal_process,
)
from loopx.capabilities.benchmark_toolkit.native_codex_profile import (
    compact_native_codex_profile_receipt,
    install_native_codex_profile,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument(
        "--require-app-server",
        action="store_true",
        help="Fail instead of recording unavailable when Codex is not on PATH.",
    )
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="Allow an uncommitted checkout for local pre-commit validation.",
    )
    return parser


def _app_server_environment(*, home: Path, codex_home: Path) -> dict[str, str]:
    allowed = {
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TERM",
        "TZ",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.setdefault("PATH", os.defpath)
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home)
    return env


def main() -> int:
    args = _parser().parse_args()
    with tempfile.TemporaryDirectory(prefix="loopx-native-goal-profile-smoke-") as raw:
        profile = install_native_codex_profile(
            REPO_ROOT,
            Path(raw) / "profile",
            require_clean_source=not args.allow_dirty_source,
        )
        profile_receipt = compact_native_codex_profile_receipt(profile)
        codex_bin = shutil.which(args.codex_bin)
        if codex_bin is None:
            if args.require_app_server:
                raise SystemExit("Codex app-server executable is unavailable")
            app_server_receipt: dict[str, object] = {
                "status": "not_available",
                "model_turn_started": False,
            }
        else:
            turn = probe_native_goal_process(
                NativeGoalConfig(
                    cwd=str(REPO_ROOT),
                    objective="Verify the installed native Goal profile without model work.",
                    task_instruction="No model turn may be started.",
                    required_skill_ids=profile.required_skill_ids,
                ),
                codex_bin=codex_bin,
                process_env=_app_server_environment(
                    home=profile.home,
                    codex_home=profile.codex_home,
                ),
                process_cwd=str(REPO_ROOT),
                response_timeout_sec=30,
            )
            compact = compact_native_goal_receipt(turn)
            app_server_receipt = {
                "status": "verified",
                "methods": compact["methods"],
                "goal_status": compact["goal_status"],
                "model_turn_started": compact["turn_id_present"],
                "required_skills_discovered": compact["required_skills_discovered"],
                "required_skill_ids": compact["required_skill_ids"],
                "skill_catalog_count": compact["skill_catalog_count"],
                "skill_error_count": compact["skill_error_count"],
            }
            if app_server_receipt["model_turn_started"] is not False:
                raise SystemExit("profile smoke unexpectedly started a model turn")
            if app_server_receipt["required_skills_discovered"] is not True:
                raise SystemExit("profile smoke did not discover required skills")

    print(
        json.dumps(
            {
                "ok": True,
                "profile": profile_receipt,
                "app_server": app_server_receipt,
                "public_boundary": {
                    "local_paths_recorded": False,
                    "credentials_recorded": False,
                    "task_content_recorded": False,
                    "model_turn_started": False,
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
