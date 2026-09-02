#!/usr/bin/env python3
"""把 marathon-full 下的结果汇总成逐臂表格。

【踩过的坑，别改回去】
原来的做法是：先按目录 mtime 排序取"最新的 <stamp> 目录"，再在其下找 result.json。
两处都错——

  1. 目录的 mtime 会随子目录写入不断变化，排序不稳定；
  2. 实际层级是 <task>/<arm>/<stamp>/<arm>/<trial>/result.json，
     而当时用的 glob("*/*") 只够到两层，根本扫不到。

后果是**已完成和已失败的 trial 全被漏掉**，进度恒显示「0 完成 0 错误」。
这比 trial 本身失败更危险：整轮监控都会误判成一切正常。实际当时
biofabric-rust-rewrite/codex-cli 已经以 errors=1 收尾了。

现在直接递归找所有 result.json，按文件自身的 mtime 给每个 (任务, 臂) 取最新一份。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import defaultdict

ARMS = ("plain", "goal", "ssh-goal", "codex-cli", "heartbeat")


def norm_arm(name: str) -> str:
    """臂名归一化：ssh-goal-1537631 → ssh-goal。

    marathon_run.sh 在原目录不可写时会回退成 `<arm>-<pid>`。不归一化的话，
    这些结果的 key 不在 ARMS 白名单里，下面的打印循环直接跳过它们——
    **结果存在但表格里看不见**，和之前 glob 太浅漏掉全部结果是同一类事故。
    """
    return re.sub(r"-\d{3,}$", "", name)


def main() -> int:
    out = pathlib.Path(sys.argv[1])
    latest: dict[tuple[str, str], tuple[float, pathlib.Path]] = {}
    for res in out.glob("*/*/**/result.json"):
        parts = res.relative_to(out).parts
        if len(parts) < 2:
            continue
        # 【跳过点目录】被有意排除的任务挪进 .excluded-gpu/ 归档，不能再当成结果扫。
        # 不跳的话，它下面每个任务目录会被当成"臂"，而那些格子恰好是
        # completed=0/errored=0/pending=1，正好触发上面"一个 trial 都没起来"的告警——
        # 于是**已经处理掉的问题会永远报警**，把真出问题时的同一条告警淹掉。
        if parts[0].startswith("."):
            continue
        # 【只认 job 级】这个 glob 同时会匹配到 trial 级的 result.json
        # （<task>/<arm>/<stamp>/<arm>/<trial>/result.json），而 trial 级是
        # TrialResult 结构、**没有 stats 字段**。下面按 mtime 取最新，一旦某个
        # trial 级文件比 job 级新，这一格的 stats 就是空 → 完成数/错误数静默记 0，
        # 看着像"这条臂什么都没跑出来"。实测目前 harbor 总是最后写 job 级文件，
        # 所以还没踩到，但那是时序巧合、不是保证。这里显式按 stats 在不在过滤。
        try:
            if not json.loads(res.read_text()).get("stats"):
                continue
        except Exception:
            continue
        key = (parts[0], norm_arm(parts[1]))          # (任务, 臂)
        m = res.stat().st_mtime
        if key not in latest or m > latest[key][0]:
            latest[key] = (m, res)

    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "err": 0, "reward": []})
    failures: list[tuple[str, str]] = []
    # 【别删】"一个 trial 都没起来"的格子。签名是
    #   n_completed=0, n_errored=0, n_pending=1
    # 也就是 harbor 在**构造环境阶段**就抛了，还没轮到 trial。这种格子在下面的
    # 累加里两边都加 0 —— 完成数不涨、错误数也不涨，于是整张表**完全看不见它**，
    # 汇总还照样打印"无错误"。
    # 实际踩到：三个 GPU 任务的 15 个格子全是这样（task.toml 声明 gpus=1，而
    # harbor 的 docker 环境 capabilities.gpus 恒为 False，_validate_gpu_support
    # 直接 RuntimeError）。连着几轮监控都报"全臂 0 错误"，而那 15 格一直是空的。
    # 和 glob 太浅漏掉全部结果是同一类事故：**沉默的失败比响亮的失败危险**。
    never_started: list[tuple[str, str]] = []
    for (task, arm), (_, res) in sorted(latest.items()):
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

    if not agg:
        print("  还没有任何 result.json")
        return 0

    print(f"  {'臂':12} {'完成':>4} {'错误':>4} {'平均reward':>10}")
    for arm in ARMS:
        a = agg.get(arm)
        if not a:
            continue
        r = sum(a["reward"]) / len(a["reward"]) if a["reward"] else None
        print(f"  {arm:12} {a['n']:>4} {a['err']:>4} "
              f"{(f'{r:.3f}' if r is not None else '—'):>10}")

    if failures:
        print(f"  有错误的 (任务,臂)：{', '.join(f'{t}/{a}' for t, a in failures[:6])}")
    if never_started:
        tasks = sorted({t for t, _ in never_started})
        print(f"  ⚠ 一个 trial 都没起来的格 {len(never_started)} 个"
              f"（环境构造阶段就失败，完成/错误两边都不计）："
              f"{', '.join(tasks[:6])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
