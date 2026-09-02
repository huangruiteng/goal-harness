#!/usr/bin/env python3
"""五模式对比报表。可同时读两个跑次做跨预算对照。

    _compare.py <out_dir> [archive_dir]

    _compare.py marathon-full                       # 只看当前跑次
    _compare.py marathon-full marathon-89min-xxx    # 和第一轮对照

口径全部走 scripts/_common（模式名归一化、只认 job 级 result.json、属主校验、半成品
metrics 排除）。报表三条原则：
  · reward 是二值的，紧预算下几乎全 0，必须同时给 partial_score
  · 构建失败（Rust 类任务）会让 partial_score 直接归零，单独标注（✗），不混进均值
  · 模式均值只在双方都跑过的任务上算，否则是任务集差异不是能力差异
"""

from __future__ import annotations

import os
import sys

from _common import ARMS, collect, safe_path

# 连续分（partial_score / build_failed）是任务自己写的约定，不是 harbor 的。bench
# profile 说没有时整列不渲染 —— 渲染成一列 0.0 会被读成"全都没得分"，比不显示更坏。
BENCH = os.environ.get("WEN_BENCH", "swe-marathon")
HAS_PARTIAL = os.environ.get("BENCH_HAS_PARTIAL", "1") == "1"


def cell(rec: dict | None) -> str:
    if not rec:
        return "—"
    rw = "?" if rec.get("reward") is None else f"{rec['reward']:.0f}"
    if not HAS_PARTIAL:
        return rw
    ps = rec.get("partial")
    p = "--" if ps is None else f"{ps:.2f}"
    mark = "✗" if rec.get("build_failed") else ""
    return f"{rw}|{p}{mark}"


def _print_grid(cur: dict, tasks: list) -> None:
    if HAS_PARTIAL:
        print("格式 reward|partial（✗ = 构建失败，partial 被门禁归零）")
    else:
        print(f"格式 reward（二值）。bench={BENCH} 没有连续分约定，partial 列不适用")
    print(f"{'任务':26}" + "".join(f"{a:>12}" for a in ARMS) + "  齐")
    for t in tasks:
        n = sum(1 for a in ARMS if (t, a) in cur)
        print(f"{t[:26]:26}" + "".join(f"{cell(cur.get((t, a))):>12}" for a in ARMS)
              + f" {n}/5" + ("★" if n == 5 else ""))


def _print_full_compare(cur: dict, full: list) -> None:
    print(f"\n五模式齐 {len(full)} 个任务: {full}")
    if not full:
        return
    print("\n=== 只用五模式齐的任务比较 ===")
    hdr = f"  {'模式':11}{'reward':>8}"
    if HAS_PARTIAL:
        hdr += f"{'partial':>9}{'构建失败':>9}"
    print(hdr + f"{'花费':>9}{'自己收工':>9}")
    for a in ARMS:
        rs = [cur[(t, a)] for t in full]
        rw = [x["reward"] for x in rs if x.get("reward") is not None]
        cst = sum(x["cost"] for x in rs)
        done = sum(1 for x in rs if x.get("status") == "complete")
        line = f"  {a:11}{(sum(rw) / len(rw) if rw else float('nan')):>8.3f}"
        if HAS_PARTIAL:
            ps = [x["partial"] for x in rs if x.get("partial") is not None]
            bf = sum(1 for x in rs if x.get("build_failed"))
            line += (f"{(sum(ps) / len(ps) if ps else float('nan')):>9.3f}"
                     f"{f'{bf}/{len(rs)}':>9}")
        print(line + f"{'$' + str(round(cst)):>9}{f'{done}/{len(rs)}':>9}")
    if not HAS_PARTIAL:
        print("  注: reward 是二值的，紧预算下多为 0；"
              "解读要看「自己收工」列（撞死线 vs 自己收尾）。")


def _print_loopx_cont(cur: dict) -> None:
    print("\n=== LoopX 三模式的续跑与解锁 ===")
    for a in ("ssh-goal", "codex-cli", "heartbeat"):
        rs = [v for (t, x), v in cur.items() if x == a]
        cont = [v.get("cont") for v in rs if v.get("cont") is not None]
        unb = [v.get("unblock") for v in rs if v.get("unblock") is not None]
        print(f"  {a:11} n={len(rs):>2}  续跑合计 {sum(cont)}（{cont}）  解锁合计 {sum(unb)}")


def _print_cross_run(cur: dict, old: dict) -> None:
    print("\n=== 跨跑次对照（只用两轮都有的格）===")
    common = sorted(set(cur) & set(old))
    print(f"  共同格 {len(common)} 个")
    key = "partial" if HAS_PARTIAL else "reward"   # 没有连续分时用 reward 做差
    for a in ARMS:
        cs = [(cur[k], old[k]) for k in common if k[1] == a]
        cs = [(x, y) for x, y in cs
              if x.get(key) is not None and y.get(key) is not None]
        if not cs:
            continue
        dp = sum(x[key] - y[key] for x, y in cs) / len(cs)
        dc = sum(x["cost"] - y["cost"] for x, y in cs) / len(cs)
        cut = sum(1 for x, _ in cs if x.get("status") != "complete")
        print(f"  {a:11} n={len(cs)}  Δ{key}={dp:+.3f}  Δ花费={dc:+.1f}  "
              f"本轮被砍 {cut}/{len(cs)}")


def main() -> int:
    cur = collect(safe_path(sys.argv[1]))
    old = collect(safe_path(sys.argv[2])) if len(sys.argv) > 2 else {}
    if not cur:
        print("  没有结果")
        return 0
    tasks = sorted({t for t, _ in cur})
    full = [t for t in tasks if sum(1 for a in ARMS if (t, a) in cur) == 5]
    _print_grid(cur, tasks)
    _print_full_compare(cur, full)
    _print_loopx_cont(cur)
    if old:
        _print_cross_run(cur, old)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
