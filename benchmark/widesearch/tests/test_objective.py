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


def test_objective_differences() -> None:
    mod = _load_runner()
    base = mod._objective("c1", Path("/ws"), "instruction text", treatment=False)
    treat = mod._objective("c1", Path("/ws"), "instruction text", treatment=True)
    assert "loopx" not in base.lower()
    assert "loopx" in treat.lower()
    assert "/ws/final_answer.md" in base
    assert "/ws/final_answer.md" in treat
