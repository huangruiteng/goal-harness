#!/usr/bin/env python3
"""Smoke-test LoopX slash-command prompt/skill installation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loopx.cli", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def statuses_for(payload: dict, path: Path) -> list[str]:
    return [
        str(item["status"])
        for item in payload["installed"]
        if item.get("path") == str(path)
    ]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-slash-install-smoke-") as tmp:
        root = Path(tmp)
        codex_home = root / ".codex"
        claude_home = root / ".claude"

        dry = json.loads(
            run_cli(
                "--format",
                "json",
                "slash-commands",
                "--dry-run",
                "--codex-home",
                str(codex_home),
                "--claude-home",
                str(claude_home),
            ).stdout
        )
        assert dry["schema_version"] == "loopx_slash_command_install_v0", dry
        assert dry["execute"] is False, dry
        assert dry["summary"]["status_counts"]["would_create"] >= 20, dry
        assert not (codex_home / "prompts").exists(), dry
        assert not (claude_home / "skills").exists(), dry

        payload = json.loads(
            run_cli(
                "--format",
                "json",
                "slash-commands",
                "--install",
                "--codex-home",
                str(codex_home),
                "--claude-home",
                str(claude_home),
            ).stdout
        )
        assert payload["execute"] is True, payload
        assert payload["summary"]["codex_prompt_dir"] == str(codex_home / "prompts"), payload
        assert payload["summary"]["codex_skill_dir"] == str(codex_home / "skills"), payload
        assert payload["summary"]["claude_skill_dir"] == str(claude_home / "skills"), payload
        assert payload["summary"]["status_counts"]["created"] >= 20, payload
        assert "skipped_user_file" not in payload["summary"]["status_counts"], payload

        codex_prompt = codex_home / "prompts" / "loopx.md"
        codex_prompt_text = codex_prompt.read_text(encoding="utf-8")
        assert "loopx-managed-slash-command:v1 command=/loopx surface=codex-prompts" in codex_prompt_text
        assert "bootstrap-command-pack --project . --goal-text" in codex_prompt_text
        assert "argument-hint: \"[goal text]\"" in codex_prompt_text

        codex_skill = codex_home / "skills" / "loopx" / "SKILL.md"
        codex_skill_text = codex_skill.read_text(encoding="utf-8")
        assert "name: \"loopx\"" in codex_skill_text
        assert "surface=codex-skills" in codex_skill_text
        assert "LoopX `/loopx`" in codex_skill_text

        pr_review_prompt = codex_home / "prompts" / "loopx-pr-review.md"
        pr_review_text = pr_review_prompt.read_text(encoding="utf-8")
        assert "agent_response_contract" in pr_review_text
        assert "Do not reconstruct the PR queue manually" in pr_review_text

        claude_skill = claude_home / "skills" / "loopx-global-summary" / "SKILL.md"
        claude_skill_text = claude_skill.read_text(encoding="utf-8")
        assert "name: \"loopx-global-summary\"" in claude_skill_text
        assert "surface=claude-skills" in claude_skill_text
        assert "global-summary" in claude_skill_text

        rerun = json.loads(
            run_cli(
                "--format",
                "json",
                "slash-commands",
                "--install",
                "--codex-home",
                str(codex_home),
                "--claude-home",
                str(claude_home),
            ).stdout
        )
        assert rerun["summary"]["status_counts"]["unchanged"] >= 20, rerun

        user_owned = codex_home / "prompts" / "loopx-global-risks.md"
        user_owned.write_text("# user-owned command\n", encoding="utf-8")
        legacy_owned = codex_home / "prompts" / "loopx-global-todos.md"
        legacy_owned.write_text(
            "# old loopx command\n\nloopx goal-mode setup (NOT Claude Code's built-in /goal)\n",
            encoding="utf-8",
        )
        capability_skill = codex_home / "skills" / "loopx-pr-review" / "SKILL.md"
        capability_skill.write_text(
            "# LoopX PR Review\n\nRun `loopx pr-review` first.\n",
            encoding="utf-8",
        )
        mixed = json.loads(
            run_cli(
                "--format",
                "json",
                "slash-commands",
                "--install",
                "--codex-home",
                str(codex_home),
                "--claude-home",
                str(claude_home),
            ).stdout
        )
        assert statuses_for(mixed, user_owned) == ["skipped_user_file"], mixed
        assert user_owned.read_text(encoding="utf-8") == "# user-owned command\n"
        assert statuses_for(mixed, legacy_owned) == ["upgraded_legacy_managed"], mixed
        assert "loopx-managed-slash-command:v1 command=/loopx-global-todos" in legacy_owned.read_text(
            encoding="utf-8"
        )
        assert statuses_for(mixed, capability_skill) == ["preserved_existing_loopx_skill"], mixed
        assert capability_skill.read_text(encoding="utf-8") == (
            "# LoopX PR Review\n\nRun `loopx pr-review` first.\n"
        )

        markdown = run_cli(
            "slash-commands",
            "--install",
            "--codex-home",
            str(codex_home),
            "--claude-home",
            str(claude_home),
        ).stdout
        assert "# LoopX Slash Command Install" in markdown, markdown
        assert "codex prompts:" in markdown, markdown
        assert "codex skills:" in markdown, markdown
        assert "claude skills:" in markdown, markdown
        assert "Skipped user-owned files:" in markdown, markdown

        codex_only = json.loads(
            run_cli(
                "--format",
                "json",
                "slash-commands",
                "--install",
                "--surface",
                "codex-cli",
                "--codex-home",
                str(root / "codex-only"),
                "--claude-home",
                str(root / "claude-unused"),
            ).stdout
        )
        assert codex_only["effective_surfaces"] == ["codex"], codex_only
        assert codex_only["summary"]["claude_skill_dir"] is None, codex_only

    print("slash-command-install-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
