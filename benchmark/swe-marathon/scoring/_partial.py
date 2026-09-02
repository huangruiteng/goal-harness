#!/usr/bin/env python3
"""连续分（partial credit）对照表。

    _partial.py <out_dir>

harbor 的 reward 是二值的：多数任务要求全部测试通过才给 1。我们把预算压到任务声明值的
15–37%，绝大多数做不完，二值表会是一片 0。但任务本身算了连续分，写在
/logs/verifier/metrics.json（partial_score / pass_rate / pytest / gates_*）。所以最终
报表以连续分为主、二值 reward 为辅。

口径（score/testrate/norm/ARMS）走 scripts/_common。本模块由 bench profile 的
BENCH_HAS_PARTIAL 控制，为 0 时整体跳过并说明原因，不做静默兜底。
"""

from __future__ import annotations

import json
import os
import sys

from _common import ARMS, norm, safe_path, score, testrate

if os.environ.get("BENCH_HAS_PARTIAL", "1") != "1":
    bench = os.environ.get("WEN_BENCH", "?")
    print(f"  （跳过：bench={bench} 的任务不写 /logs/verifier/metrics.json，"
          f"没有连续分约定。分数以二值 reward 为准。）")
    raise SystemExit(0)


def usable(m, d: dict) -> bool:
    """排除还没跑完的 trial 留下的半成品 metrics。"""
    if "phase" in d and str(d.get("phase") or "").lower() in ("initialized", "starting", ""):
        return False
    job = m.parent.parent.parent            # <task>/<mode>/<stamp>/<mode>
    for r in job.glob("result.json"):
        try:
            s = json.loads(r.read_text()).get("stats", {})
        except Exception:
            continue
        if int(s.get("n_completed_trials") or 0) >= 1:
            return True
    return False


def collect_partial(out) -> dict:
    """扫 metrics.json，返回 {(task, mode): (partial_score, testrate)}。"""
    cell: dict = {}
    skipped = 0
    for m in sorted(out.glob("*/*/*/*/*/verifier/metrics.json")):
        rel = m.relative_to(out).parts
        task, arm = rel[0], norm(rel[1])
        if (out / rel[0] / rel[1]).stat().st_uid != os.getuid():
            continue
        try:
            d = json.loads(m.read_text())
        except Exception:
            continue
        if not usable(m, d):
            skipped += 1
            continue
        s, tr = score(d), testrate(d)
        if s is not None or tr is not None:
            cell[(task, arm)] = (s, tr)
    if skipped:
        print(f"  （跳过 {skipped} 份未完成 trial 的半成品 metrics）")
    return cell


def _fmt(v) -> str:
    if v is None:
        return "—"
    ps, tr = v
    a1 = f"{ps:.3f}" if ps is not None else "?"
    a2 = f"{tr:.3f}" if tr is not None else "?"
    return f"{a1}/{a2}"


def _print_rows(cell: dict) -> None:
    print("  每格 = partial_score / 测试通过率")
    print(f"  {'任务':26}" + "".join(f"{a:>13}" for a in ARMS))
    for t in sorted({t for t, _ in cell}):
        line = f"  {t[:26]:26}" + "".join(f"{_fmt(cell.get((t, a))):>13}" for a in ARMS)
        print(line)


def _col_means(cell: dict, tasks=None):
    """每个模式的 (partial 均值, testrate 均值, n)。tasks 限定任务集。"""
    for a in ARMS:
        items = [(k, v) for k, v in cell.items() if k[1] == a and (tasks is None or k[0] in tasks)]
        vs = [v[0] for _, v in items if v[0] is not None]
        ts = [v[1] for _, v in items if v[1] is not None]
        m1 = f"{sum(vs) / len(vs):.3f}" if vs else "—"
        m2 = f"{sum(ts) / len(ts):.3f}" if ts else "—"
        yield a, m1, m2, len(items), len(vs), len(ts)


def _print_means(cell: dict) -> None:
    print(f"  {'模式均值':26}", end="")
    for _, m1, m2, *_ in _col_means(cell):
        print(f"{m1 + '/' + m2:>13}", end="")
    print()
    print(f"  {'(n)':26}", end="")
    for _, _m1, _m2, n, *_ in _col_means(cell):
        print(f"{f'(n={n})':>13}", end="")
    print()


def _print_paired(cell: dict) -> None:
    common = [t for t in {t for t, _ in cell}
              if sum(1 for a in ARMS if (t, a) in cell) >= 2]
    if not common:
        return
    print(f"  —— 仅用两模式以上都跑过的 {len(common)} 个任务配对比较 ——")
    for a, m1, m2, _n, nv, nt in _col_means(cell, set(common)):
        if nv or nt:
            print(f"    {a:10} partial={m1} 测试通过率={m2}  (n={nv}/{nt})")


def main() -> int:
    out = safe_path(sys.argv[1] if len(sys.argv) > 1 else "marathon-full")
    cell = collect_partial(out)
    if not cell:
        print("  还没有可用的 metrics.json")
        return 0
    _print_rows(cell)
    _print_means(cell)
    _print_paired(cell)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
