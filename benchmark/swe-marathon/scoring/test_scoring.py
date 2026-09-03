#!/usr/bin/env python3
"""评分口径回归测试。可直接 `python3 test_scoring.py`，也可被 pytest 收集。

锁死两条曾经出问题的口径：
  1. 单个模式在共同任务上 build_failed 时，**不缩小该模式的分母**——构建失败作为
     观测值计入，reward/partial 均值在全部匹配任务上算（matched denominator）。
  2. _common.collect / _aggregate 与 _compare 用同一口径，不产生两套均值。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import _aggregate
import _common


def _write_trial(root: Path, task: str, arm: str, reward: float,
                 partial: float, build_failed: bool) -> None:
    """造 job 级 result.json 与 trial 级 metrics.json，层级对齐 _common.collect。

    job 目录 = <root>/<task>/<arm>/<stamp>/<arm>/result.json（collect 的 glob 深度）；
    metrics 在 job/<trial>/verifier/metrics.json。
    """
    job = root / task / arm / "20260101-000000" / arm
    trial = job / f"{task}__x"
    (trial / "verifier").mkdir(parents=True, exist_ok=True)
    result = {
        "started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:10:00",
        "stats": {
            "n_completed_trials": 1, "n_errored_trials": 0,
            "cost_usd": 1.0, "n_input_tokens": 10, "n_output_tokens": 5, "n_cache_tokens": 0,
            "evals": {"e": {"reward_stats": {"reward": {str(reward): [f"{task}__x"]}}}},
        },
    }
    (job / "result.json").write_text(json.dumps(result))
    metrics = {"phase": "build_failed" if build_failed else "done", "partial_score": partial}
    (trial / "verifier" / "metrics.json").write_text(json.dumps(metrics))


def test_matched_denominator_on_single_arm_build_failure():
    """两任务、五模式；其中一个模式在 task2 上构建失败（partial=0）。

    该模式的 partial 均值应为 (1.0 + 0.0)/2 = 0.5、n=2（未缩成 n=1）。
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "results"
        for arm in _common.ARMS:
            _write_trial(root, "task1", arm, reward=1.0, partial=1.0, build_failed=False)
            bf = (arm == "codex-cli")
            _write_trial(root, "task2", arm, reward=0.0,
                         partial=0.0 if bf else 1.0, build_failed=bf)
        cur = _common.collect(root)
        full = [t for t in {t for t, _ in cur}
                if sum(1 for a in _common.ARMS if (t, a) in cur) == 5]
        assert sorted(full) == ["task1", "task2"]
        rs = [cur[(t, "codex-cli")] for t in full]
        s = _aggregate._mode_summary(rs)
        assert s["n"] == 2, s
        assert abs(s["partial"] - 0.5) < 1e-9, s          # 含构建失败的 0，未剔除
        assert s["build_failed"] == 1, s                  # 单列计数仍在
        # 无构建失败的模式：两任务都 1.0 → 0.5? 不，task2 partial=1.0 → 均值 1.0
        rs_ok = [cur[(t, "plain")] for t in full]
        s_ok = _aggregate._mode_summary(rs_ok)
        assert abs(s_ok["partial"] - 1.0) < 1e-9, s_ok


def test_testrate_and_score_helpers():
    assert _common.score({"partial_score": 0.4}) == 0.4
    assert _common.score({"pass_rate": 0.7}) == 0.7
    assert _common.score({}) is None
    assert abs(_common.testrate({"passed": 3, "total": 4}) - 0.75) < 1e-9
    assert _common.testrate({}) is None


def _run() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL {name}: {e}")
    print("OK" if not fails else f"{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_run())
