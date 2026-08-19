#!/usr/bin/env python3
"""Exercise the Frontstage stargazer fetch helper without live credentials."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FETCH = ROOT / "scripts" / "fetch-github-stargazers.sh"


FAKE_GH = r"""#!/usr/bin/env bash
set -euo pipefail
if [[ "${FAKE_GH_MODE:-success}" == "deny" ]]; then
  echo "gh: Resource not accessible by integration (HTTP 403)" >&2
  exit 1
fi
if [[ "$*" == *"${GH_TOKEN:?}"* ]]; then
  echo "credential was passed as a command argument" >&2
  exit 2
fi
if [[ "$*" == *"--paginate --slurp"* ]]; then
  [[ "$*" == *"Accept: application/vnd.github.star+json"* ]]
  [[ "$*" == *"repos/example/loopx/stargazers?per_page=100"* ]]
  printf '%s\n' '[[{"starred_at":"2026-08-17T01:02:03Z"},{"starred_at":"2026-08-18T04:05:06Z"}]]'
else
  [[ "$*" == *"repos/example/loopx"* ]]
  [[ "$*" == *"--jq .stargazers_count"* ]]
  printf '%s\n' '2'
fi
"""


def run_fetch(root: Path, *, token: str | None, mode: str = "success") -> subprocess.CompletedProcess[str]:
    fake_bin = root / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(FAKE_GH, encoding="utf-8")
    fake_gh.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["RUNNER_TEMP"] = str(root)
    env["LOOPX_STARGAZER_RETRY_DELAY_SECONDS"] = "0"
    env["FAKE_GH_MODE"] = mode
    if token is None:
        env.pop("GH_TOKEN", None)
    else:
        env["GH_TOKEN"] = token
    return subprocess.run(
        [
            str(FETCH),
            "example/loopx",
            str(root / "stargazers.json"),
            str(root / "stargazers-count"),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def main() -> int:
    synthetic_token = "-".join(("test", "only"))
    with tempfile.TemporaryDirectory(prefix="loopx-stargazer-fetch-") as tmp:
        root = Path(tmp)
        success = run_fetch(root, token=synthetic_token)
        assert success.returncode == 0, success.stderr
        rows = json.loads((root / "stargazers.json").read_text(encoding="utf-8"))
        assert rows == [
            {"starred_at": "2026-08-17T01:02:03Z"},
            {"starred_at": "2026-08-18T04:05:06Z"},
        ]
        assert (root / "stargazers-count").read_text(encoding="utf-8") == "2\n"

    with tempfile.TemporaryDirectory(prefix="loopx-stargazer-missing-") as tmp:
        missing = run_fetch(Path(tmp), token=None)
        assert missing.returncode != 0
        assert "Missing star-history credential" in missing.stderr

    with tempfile.TemporaryDirectory(prefix="loopx-stargazer-denied-") as tmp:
        denied = run_fetch(Path(tmp), token=synthetic_token, mode="deny")
        assert denied.returncode != 0
        assert "HTTP 403" in denied.stderr
        assert synthetic_token not in denied.stderr

    print("frontstage-stargazer-fetch-smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
