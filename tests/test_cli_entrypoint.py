from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_isolated_script(script: str) -> subprocess.CompletedProcess[str]:
	return subprocess.run(
		[sys.executable, "-c", script],
		cwd=REPO_ROOT,
		env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
		text=True,
		capture_output=True,
		check=False,
	)


def test_version_flag_skips_full_cli_import() -> None:
	script = """
import contextlib
import io
import sys

from loopx.entrypoint import main

output = io.StringIO()
with contextlib.redirect_stdout(output):
    exit_code = main(["--version"])

assert exit_code == 0
assert output.getvalue().startswith("loopx ")
assert "loopx.cli" not in sys.modules
"""
	completed = run_isolated_script(script)

	assert completed.returncode == 0, completed.stderr


def test_other_arguments_delegate_to_full_cli() -> None:
	script = """
from loopx.entrypoint import main

raise SystemExit(main(["--format", "json", "version"]))
"""
	completed = run_isolated_script(script)

	assert completed.returncode == 0, completed.stderr
	payload = json.loads(completed.stdout)
	assert payload["schema_version"] == "loopx_version_v0"


def test_console_script_uses_lightweight_entrypoint() -> None:
	project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

	assert project["project"]["scripts"]["loopx"] == "loopx.entrypoint:main"
