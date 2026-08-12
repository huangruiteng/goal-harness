from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_opencode2_goal_worker_contract() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the OpenCode 2 goal worker contract")
    test_file = Path(__file__).with_name("opencode2_goal_worker.test.mjs")
    subprocess.run([node, "--test", str(test_file)], check=True)
