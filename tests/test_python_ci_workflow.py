from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "python-tests.yml"
).read_text(encoding="utf-8")


@pytest.mark.parametrize("checks", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("shards", ["success", "failure", "cancelled", "skipped"])
def test_required_pytest_check_rejects_incomplete_upstream_jobs(
    checks: str, shards: str,
) -> None:
    # Execute the actual gate, including the runner's fail-fast shell behavior.
    gate = WORKFLOW.split("name: Require every upstream check", 1)[1]
    script = gate.split("run: |", 1)[1].split("      - uses:", 1)[0]
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        env={**os.environ, "CHECKS_RESULT": checks, "SHARDS_RESULT": shards},
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) == (checks == shards == "success")
    assert "if: always()\n    needs: [checks, test-shard]" in WORKFLOW


def test_two_shards_execute_each_test_once_and_merge_portable_coverage(
    tmp_path: Path,
) -> None:
    # Real pytest-split + xdist + coverage, in two distinct checkout roots.
    # Each shard alone misses a function; their union must cover the whole file.
    shard_step = WORKFLOW.split("name: Run test shard", 1)[1]
    template = shard_step.split("run: >-", 1)[1].split("      - name:", 1)[0]
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("COVERAGE", "COV_CORE", "PYTEST"))
    }
    seen: list[set[str]] = []
    for shard in (1, 2):
        root = tmp_path / f"checkout-{shard}"
        root.mkdir()
        (root / "ci_subject.py").write_text(
            "def first():\n    return 1\n\ndef second():\n    return 2\n",
            encoding="utf-8",
        )
        (root / "test_subject.py").write_text(
            "from ci_subject import first, second\n"
            "def test_first():\n    assert first() == 1\n"
            "def test_second():\n    assert second() == 2\n",
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            '[tool.coverage.run]\nsource = ["ci_subject"]\nrelative_files = true\n',
            encoding="utf-8",
        )
        args = shlex.split(template.replace("${{ matrix.shard }}", str(shard)))
        args[0] = sys.executable
        args[args.index("--cov=loopx")] = "--cov=ci_subject"
        result = subprocess.run(
            [*args, "--junitxml=results.xml"], cwd=root, env=env,
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        cases = ET.parse(root / "results.xml").findall(".//testcase")
        seen.append({case.attrib["name"] for case in cases})
        partial = subprocess.run(
            [sys.executable, "-m", "coverage", "report", "--fail-under=100"],
            cwd=root, env=env, capture_output=True, check=False,
        )
        assert partial.returncode == 2
        destination = tmp_path / "coverage-shards" / f"python-coverage-{shard}"
        destination.mkdir(parents=True)
        (root / ".coverage").rename(destination / ".coverage")

    assert seen[0] and seen[1] and seen[0].isdisjoint(seen[1])
    assert seen[0] | seen[1] == {"test_first", "test_second"}
    # Reuse the real aggregate shell commands, with a 100% synthetic oracle.
    step = WORKFLOW.split("name: Combine complete coverage", 1)[1]
    script = step.split("run: |", 1)[1].split("      - uses:", 1)[0]
    script = script.replace("python -m", f"{shlex.quote(sys.executable)} -m")
    script = script.replace("--fail-under=19.6", "--fail-under=100")
    root = tmp_path / "checkout-1"
    (tmp_path / "coverage-shards").rename(root / "coverage-shards")
    for shard in (1, 2):
        data = root / "coverage-shards" / f"python-coverage-{shard}" / ".coverage"
        held = data.with_name("held")
        data.rename(held)
        missing = subprocess.run(
            ["bash", "-e", "-c", script], cwd=root, env=env,
            capture_output=True, check=False,
        )
        assert missing.returncode != 0
        assert not (root / "coverage.xml").exists()
        held.rename(data)
    result = subprocess.run(
        ["bash", "-e", "-c", script], cwd=root, env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert ET.parse(root / "coverage.xml").getroot().attrib["line-rate"] == "1"
    # The combine consumed the inputs: replay with absent artifacts must fail.
    missing = subprocess.run(
        ["bash", "-e", "-c", script], cwd=root, env=env,
        capture_output=True, check=False,
    )
    assert missing.returncode != 0
    assert re.search(r"shard: \[1, 2\]", WORKFLOW)
    assert "include-hidden-files: true" in WORKFLOW
    assert "--cov-fail-under" not in template
