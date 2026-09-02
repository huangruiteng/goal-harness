#!/usr/bin/env python3
"""把 marathon-full 的五模式结果聚合成单一 data.json，供可视化网页与总结 md 使用。

复用 _compare.py / _partial.py 里已经踩过坑的口径，别在这里重造轮子：
  · 模式名归一化 norm()               —— ssh-goal-1537631 → ssh-goal
  · 只认 job 级 result.json（有 stats）
  · 属主必须是当前用户（排除上一轮 root 属主的遗留目录）
  · partial 半成品（phase=initialized/starting）不算成绩
  · cost 以 result.json 的 cost_usd 为准（不是 0；上个可视化把它算丢了）

用法：
    _aggregate.py <out_dir> [data.json]
    _aggregate.py marathon-full viz/data.json
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import sys

ARMS = ("plain", "goal", "ssh-goal", "codex-cli", "heartbeat")
# 模式的角色标注，写进 data.json 供前端解释
ARM_ROLE = {
    "plain": "baseline①：裸 codex，objective = 'Finish the task.'，无 goal、无 LoopX",
    "goal": "baseline②：codex 原生 goal（codex 自带的 goal 功能，注入干净 goal，非 LoopX）",
    "ssh-goal": "LoopX 模式①：codex 原生 goal + LoopX 渲染的 goal body/skills，经 ssh 驱动",
    "codex-cli": "LoopX 模式②：容器内跑 loopx CLI 现渲 goal body（带 claim/lease/peer 样板）",
    "heartbeat": "LoopX 模式③：心跳驱动的续跑/解锁 + LoopX goal body/skills",
}


def norm(a: str) -> str:
    return re.sub(r"-\d{3,}$", "", a)


def testrate(d: dict):
    """测试通过率——比 partial_score 更稳的连续口径（口径同 _partial.py）。"""
    pt = d.get("pytest")
    if isinstance(pt, dict) and pt:
        p = sum((g or {}).get("passed") or 0 for g in pt.values() if isinstance(g, dict))
        t = sum((g or {}).get("total") or 0 for g in pt.values() if isinstance(g, dict))
        if t:
            return p / t
    p, t, f = d.get("passed"), d.get("total"), d.get("failed")
    if isinstance(p, (int, float)) and isinstance(t, (int, float)) and t:
        return p / t
    if isinstance(p, (int, float)) and isinstance(f, (int, float)) and (p + f):
        return p / (p + f)
    gp, gt = d.get("gates_passed"), d.get("gates_total")
    if isinstance(gp, (int, float)) and isinstance(gt, (int, float)) and gt:
        return gp / gt
    return None


def collect(root: pathlib.Path) -> dict:
    out: dict = {}
    if not root.is_dir():
        return out
    for r in root.glob("*/*/*/*/result.json"):
        rel = r.relative_to(root).parts
        task, armdir = rel[0], rel[1]
        if task.startswith("."):
            continue
        arm = norm(armdir)
        if arm not in ARMS:
            continue
        try:
            if (root / rel[0] / rel[1]).stat().st_uid != os.getuid():
                continue
        except OSError:
            continue
        try:
            d = json.loads(r.read_text())
        except Exception:
            continue
        s = d.get("stats", {})
        if not s or int(s.get("n_completed_trials") or 0) < 1:
            continue
        rw = [float(k)
              for ev in (s.get("evals") or {}).values()
              for k, t in ((ev.get("reward_stats") or {}).get("reward") or {}).items()
              for _ in t]
        rec = {
            "task": task,
            "arm": arm,
            "reward": rw[0] if rw else None,
            "cost": s.get("cost_usd") or 0.0,
            "tok_in": s.get("n_input_tokens") or 0,
            "tok_out": s.get("n_output_tokens") or 0,
            "tok_cache": s.get("n_cache_tokens") or 0,
            "errors": int(s.get("n_errored_trials") or 0),
            "partial": None,
            "testrate": None,
            "build_failed": False,
            "passed": None,
            "failed": None,
            "status": None,
            "cont": None,
            "unblock": None,
            "err_events": None,
            "min": None,
            "run_dir": str(r.parent.relative_to(root)),
        }
        try:
            t0 = datetime.datetime.fromisoformat(d["started_at"])
            t1 = datetime.datetime.fromisoformat(d["finished_at"])
            rec["min"] = round((t1 - t0).total_seconds() / 60, 1)
        except Exception:
            pass
        for m in r.parent.glob("*/verifier/metrics.json"):
            try:
                mm = json.loads(m.read_text())
            except Exception:
                continue
            ph = str(mm.get("phase") or "")
            if ph in ("initialized", "starting"):
                continue
            rec["partial"] = mm.get("partial_score")
            rec["testrate"] = testrate(mm)
            rec["build_failed"] = ph == "build_failed"
            rec["passed"], rec["failed"] = mm.get("passed"), mm.get("failed")
        for f in r.parent.glob("*/agent/goal_receipt.json"):
            try:
                g = json.loads(f.read_text())
            except Exception:
                continue
            rec["status"] = g.get("post_goal_status")
            rec["cont"] = g.get("goal_continuation_turn_completed_count")
            rec["unblock"] = g.get("_unblock_count")
            rec["err_events"] = g.get("error_event_count")
        out[(task, arm)] = rec
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "marathon-full")
    outp = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "viz/data.json")
    cur = collect(root)
    if not cur:
        print("没有结果", file=sys.stderr)
        return 1

    tasks = sorted({t for t, _ in cur})
    full = [t for t in tasks if sum(1 for a in ARMS if (t, a) in cur) == 5]

    cells = {}
    for (task, arm), rec in cur.items():
        cells.setdefault(task, {})[arm] = rec

    # 模式级汇总（只用五模式齐的任务，口径同 _compare.py）
    arm_summary = {}
    for a in ARMS:
        rs = [cur[(t, a)] for t in full if (t, a) in cur]
        # reward / partial / testrate 的均值剔除构建失败的 case：构建失败会让 partial
        # 被门禁直接归零，那是环境/门禁问题不是能力信号，掺进均值会冤枉该模式。
        # 其余统计（花费、自收工、续跑、解锁）仍按全量。构建失败数单列。
        scored = [x for x in rs if not x["build_failed"]]
        arm_summary[a] = {
            "role": ARM_ROLE[a],
            "n": len(rs),
            "n_scored": len(scored),
            "reward": mean([x["reward"] for x in scored]),
            "partial": mean([x["partial"] for x in scored]),
            "testrate": mean([x["testrate"] for x in scored]),
            "cost": round(sum(x["cost"] for x in rs), 2),
            "tok_in": sum(x["tok_in"] for x in rs),
            "tok_out": sum(x["tok_out"] for x in rs),
            "build_failed": sum(1 for x in rs if x["build_failed"]),
            "self_complete": sum(1 for x in rs if x.get("status") == "complete"),
            "cont_total": sum((x.get("cont") or 0) for x in rs),
            "unblock_total": sum((x.get("unblock") or 0) for x in rs),
            "wall_min": round(sum((x.get("min") or 0) for x in rs), 1),
        }

    data = {
        "generated_at": None,          # 由外部盖时间戳；脚本内不取系统时钟
        "bench": os.environ.get("WEN_BENCH", "swe-marathon"),
        "arms": list(ARMS),
        "arm_role": ARM_ROLE,
        "tasks_all": tasks,
        "tasks_full": full,
        "n_trials": len(cur),
        "arm_summary": arm_summary,
        "cells": {t: {a: cells[t].get(a) for a in ARMS if a in cells[t]} for t in tasks},
    }
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"写出 {outp}：{len(tasks)} 任务，{len(full)} 五模式齐，{len(cur)} trial")
    for a in ARMS:
        s = arm_summary[a]
        print(f"  {a:10} reward={s['reward']!s:>6} partial={s['partial']!s:>7} "
              f"cost=${s['cost']:<7} 自收工={s['self_complete']}/{s['n']} "
              f"续跑={s['cont_total']} 解锁={s['unblock_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
