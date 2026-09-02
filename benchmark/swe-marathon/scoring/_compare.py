#!/usr/bin/env python3
"""五臂对比报表。可同时读两个跑次做跨预算对照。

    _compare.py <out_dir> [archive_dir]

    _compare.py marathon-full                       # 只看当前跑次
    _compare.py marathon-full marathon-89min-xxx    # 和第一轮对照

【为什么要固定成脚本】
之前每次出对比都临时手写查询，同一个 bug 犯过两次：

  1. **臂名没归一化** —— marathon_run.sh 在臂目录不可写时会回退成 `<arm>-<pid>`
     （比如 ssh-goal-1537631）。临时脚本按目录名精确匹配，那一格就查不到，
     表里显示「—」而实际有数据。_summarize.py / _receipts.py 早就归一化了，
     临时脚本却没有。
  2. **半成品 metrics 当成绩** —— 正在重跑的 trial 也留 metrics.json，
     内容是 phase=initialized、partial=0.0，采信会凭空造出一个 0 分。

【报表的三条原则】
  · reward 是二值的，在紧预算下几乎全 0，必须同时给 partial_score
  · 构建失败（Rust 类任务）会让 partial_score 直接归零，要单独标注，
    不能和「构建通过但测试没全过」混进同一个均值
  · 臂均值只在**双方都跑过的任务**上算，否则是任务集差异不是能力差异
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import sys

ARMS = ("plain", "goal", "ssh-goal", "codex-cli", "heartbeat")

# 连续分（partial_score / build_failed）是 SWE-Marathon 任务自己写的约定，
# 不是 harbor 的。bench profile 说没有时整列不渲染 —— 渲染成一列 0.0 会被
# 读成"全都没得分"，比不显示更坏。
BENCH = os.environ.get("WEN_BENCH", "swe-marathon")
HAS_PARTIAL = os.environ.get("BENCH_HAS_PARTIAL", "1") == "1"


def norm(a: str) -> str:
    """ssh-goal-1537631 → ssh-goal。别删这个函数。"""
    return re.sub(r"-\d{3,}$", "", a)


def collect(root: pathlib.Path) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    if not root.is_dir():
        return out
    for r in root.glob("*/*/*/*/result.json"):
        task, armdir = r.parts[-5], r.parts[-4]
        # 跨跑次时 parts 位置会变，用 relative_to 更稳
        rel = r.relative_to(root).parts
        task, armdir = rel[0], rel[1]
        if task.startswith("."):
            continue          # 有意排除的归档（.excluded-gpu/），不是结果
        arm = norm(armdir)
        try:
            if (root / rel[0] / rel[1]).stat().st_uid != os.getuid():
                continue          # 遗留的 root 属主目录，是上一轮的产物
        except OSError:
            continue
        try:
            d = json.loads(r.read_text())
        except Exception:
            continue
        s = d.get("stats", {})
        if int(s.get("n_completed_trials") or 0) < 1:
            continue
        rw = [float(k)
              for ev in (s.get("evals") or {}).values()
              for k, t in ((ev.get("reward_stats") or {}).get("reward") or {}).items()
              for _ in t]
        rec = {"reward": rw[0] if rw else None,
               "cost": s.get("cost_usd") or 0,
               "errors": int(s.get("n_errored_trials") or 0)}
        try:
            t0 = datetime.datetime.fromisoformat(d["started_at"])
            t1 = datetime.datetime.fromisoformat(d["finished_at"])
            rec["min"] = (t1 - t0).total_seconds() / 60
        except Exception:
            rec["min"] = None
        for m in r.parent.glob("*/verifier/metrics.json"):
            try:
                mm = json.loads(m.read_text())
            except Exception:
                continue
            ph = str(mm.get("phase") or "")
            if ph in ("initialized", "starting"):
                continue          # 半成品，不是成绩
            rec["partial"] = mm.get("partial_score")
            rec["build_failed"] = ph == "build_failed"
            rec["passed"], rec["failed"] = mm.get("passed"), mm.get("failed")
        for f in r.parent.glob("*/agent/goal_receipt.json"):
            try:
                g = json.loads(f.read_text())
            except Exception:
                continue
            rec["status"] = g.get("post_goal_status")
            rec["cont"] = g.get("goal_continuation_turn_completed_count")
            rec["unblock"] = g.get("_unblock_count")     # 带下划线，别写错
            rec["err_events"] = g.get("error_event_count")
        out[(task, arm)] = rec
    return out


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


def main() -> int:
    cur = collect(pathlib.Path(sys.argv[1]))
    old = collect(pathlib.Path(sys.argv[2])) if len(sys.argv) > 2 else {}
    if not cur:
        print("  没有结果")
        return 0

    tasks = sorted({t for t, _ in cur})
    full = [t for t in tasks if sum(1 for a in ARMS if (t, a) in cur) == 5]

    if HAS_PARTIAL:
        print(f"格式 reward|partial（✗ = 构建失败，partial 被门禁归零）")
    else:
        # 不渲染成一列 0.0 —— 那会被读成"全都没得分"。整列不出现，并说明原因。
        print(f"格式 reward（二值）。bench={BENCH} 没有连续分约定，partial 列不适用")
    print(f"{'任务':26}" + "".join(f"{a:>12}" for a in ARMS) + "  齐")
    for t in tasks:
        n = sum(1 for a in ARMS if (t, a) in cur)
        print(f"{t[:26]:26}" + "".join(f"{cell(cur.get((t, a))):>12}" for a in ARMS)
              + f" {n}/5" + ("★" if n == 5 else ""))

    print(f"\n五臂齐 {len(full)} 个任务: {full}")
    if full:
        print(f"\n=== 只用五臂齐的任务比较 ===")
        hdr = f"  {'臂':11}{'reward':>8}"
        if HAS_PARTIAL:
            hdr += f"{'partial':>9}{'构建失败':>9}"
        print(hdr + f"{'花费':>9}{'自己收工':>9}")
        for a in ARMS:
            rs = [cur[(t, a)] for t in full]
            rw = [x["reward"] for x in rs if x.get("reward") is not None]
            cst = sum(x["cost"] for x in rs)
            done = sum(1 for x in rs if x.get("status") == "complete")
            line = f"  {a:11}{(sum(rw)/len(rw) if rw else float('nan')):>8.3f}"
            if HAS_PARTIAL:
                ps = [x["partial"] for x in rs if x.get("partial") is not None]
                bf = sum(1 for x in rs if x.get("build_failed"))
                line += (f"{(sum(ps)/len(ps) if ps else float('nan')):>9.3f}"
                         f"{f'{bf}/{len(rs)}':>9}")
            print(line + f"{'$'+str(round(cst)):>9}{f'{done}/{len(rs)}':>9}")
        if not HAS_PARTIAL:
            # 二值 reward 在紧预算下几乎没有区分度，这一行是唯一还能分辨的信号。
            print("  注: reward 是二值的，紧预算下多为 0；"
                  "解读要看「自己收工」列（撞死线 vs 自己收尾）。")

    # LoopX 三臂的续跑/解锁——报表必须标注
    print(f"\n=== LoopX 三臂的续跑与解锁 ===")
    for a in ("ssh-goal", "codex-cli", "heartbeat"):
        rs = [v for (t, x), v in cur.items() if x == a]
        cont = [v.get("cont") for v in rs if v.get("cont") is not None]
        unb = [v.get("unblock") for v in rs if v.get("unblock") is not None]
        print(f"  {a:11} n={len(rs):>2}  续跑合计 {sum(cont)}（{cont}）  解锁合计 {sum(unb)}")

    if old:
        print(f"\n=== 跨跑次对照（只用两轮都有的格）===")
        common = sorted(set(cur) & set(old))
        print(f"  共同格 {len(common)} 个")
        # 没有连续分时用 reward 做差，指标名跟着变，别让表头骗人。
        key = "partial" if HAS_PARTIAL else "reward"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
