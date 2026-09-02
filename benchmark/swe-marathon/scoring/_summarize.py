#!/usr/bin/env python3
"""把 marathon-full 下的结果汇总成逐模式表格。

递归找所有 job 级 result.json，按文件自身 mtime 给每个 (任务, 模式) 取最新一份，
再按模式累加完成/错误/reward。归一化与 ARMS 走 scripts/_common。

【别退回去的坑】
  · 不能按目录 mtime 取"最新 stamp 目录"——目录 mtime 会随子写入变化，排序不稳。
  · glob 要够深：<task>/<mode>/<stamp>/<mode>/<trial>/result.json。
  · 只认有 stats 的 job 级 result.json（trial 级没有 stats）。
  · phase=initialized/starting 的半成品不算。
  · "一个 trial 都没起来"的格（completed=0/errored=0/pending=1）要单独报，
    否则两边都加 0，表里完全看不见它——沉默的失败比响亮的失败危险。
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict

from _common import ARMS, norm, safe_path


def _latest_job_results(out: pathlib.Path) -> dict:
    """{(task, mode): result.json 路径}，每格取 mtime 最新的 job 级文件。"""
    latest: dict = {}
    for res in out.glob("*/*/**/result.json"):
        parts = res.relative_to(out).parts
        if len(parts) < 2 or parts[0].startswith("."):
            continue
        try:
            if not json.loads(res.read_text()).get("stats"):
                continue                     # trial 级没有 stats
        except Exception:
            continue
        key = (parts[0], norm(parts[1]))
        m = res.stat().st_mtime
        if key not in latest or m > latest[key][0]:
            latest[key] = (m, res)
    return {k: v[1] for k, v in latest.items()}


def _aggregate(results: dict):
    agg = defaultdict(lambda: {"n": 0, "err": 0, "reward": []})
    failures, never_started = [], []
    for (task, arm), res in sorted(results.items()):
        try:
            st = json.loads(res.read_text()).get("stats", {})
        except Exception:
            continue
        a = agg[arm]
        n_ok = int(st.get("n_completed_trials") or 0)
        err = int(st.get("n_errored_trials") or 0)
        if n_ok == 0 and err == 0 and int(st.get("n_pending_trials") or 0) > 0:
            never_started.append((task, arm))
        a["n"] += n_ok
        a["err"] += err
        if err:
            failures.append((task, arm))
        for ev in (st.get("evals") or {}).values():
            for k, tasks in ((ev.get("reward_stats") or {}).get("reward") or {}).items():
                try:
                    a["reward"] += [float(k)] * len(tasks)
                except ValueError:
                    pass
    return agg, failures, never_started


def _print(agg: dict, failures: list, never_started: list) -> None:
    print(f"  {'模式':12} {'完成':>4} {'错误':>4} {'平均reward':>10}")
    for arm in ARMS:
        a = agg.get(arm)
        if not a:
            continue
        r = sum(a["reward"]) / len(a["reward"]) if a["reward"] else None
        print(f"  {arm:12} {a['n']:>4} {a['err']:>4} "
              f"{(f'{r:.3f}' if r is not None else '—'):>10}")
    if failures:
        print(f"  有错误的 (任务,模式)：{', '.join(f'{t}/{a}' for t, a in failures[:6])}")
    if never_started:
        tasks = sorted({t for t, _ in never_started})
        print(f"  ⚠ 一个 trial 都没起来的格 {len(never_started)} 个"
              f"（环境构造阶段就失败，完成/错误两边都不计）：{', '.join(tasks[:6])}")


def main() -> None:
    out = safe_path(sys.argv[1] if len(sys.argv) > 1 else "marathon-full")
    results = _latest_job_results(out)
    if not results:
        print("  还没有任何 result.json")
        return
    agg, failures, never_started = _aggregate(results)
    _print(agg, failures, never_started)


if __name__ == "__main__":
    main()
