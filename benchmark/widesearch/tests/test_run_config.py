from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_runner() -> object:
    path = Path(__file__).resolve().parents[1] / "run_widesearch_case.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("run_widesearch_case", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_app_server_command_disables_multi_agent_for_responses_compat() -> None:
    mod = _load_runner()
    command = mod._app_server_command(codex_bin="codex", enable_web_search=True)
    assert "features.multi_agent=false" in command
    assert "tools.web_search=true" in command
    assert command[0] == "codex"


def test_app_server_command_can_disable_web_search() -> None:
    mod = _load_runner()
    command = mod._app_server_command(codex_bin="codex", enable_web_search=False)
    assert "tools.web_search=false" in command
    assert "tools.web_search=true" not in command
