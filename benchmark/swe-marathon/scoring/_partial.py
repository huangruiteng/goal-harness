#!/usr/bin/env python3
"""连续分（partial credit）对照表。

    _partial.py <out_dir>

【为什么必须有这个】
harbor 的 `reward` 是**二值**的：SWE-Marathon 多数任务要求全部测试通过才给 1，
否则 0。而我们把 agent 预算压到了任务声明值的 15–37%，绝大多数任务都做不完，
于是二值表会是一片 0 —— 五臂看起来毫无差别，实验白跑。

但任务本身就算了连续分，写在 `/logs/verifier/metrics.json`：
    embedding-eval:  "partial_score is the canonical partial-credit number in [0, 1]"
    rust-java-lsp:   reward = 1.0 if passed == total else 0.0；pass_rate = passed/total
    vliw:            partial_score = (BASELINE - cycles) / (BASELINE - CYCLE_TARGET)

实测差异有多大（biofabric-rust-rewrite，408 个测试）：
    二值 reward   四臂全是 0
    连续分        goal 0.973 / heartbeat 0.973 / ssh-goal 0.971 / plain 0.924
                  （失败数 11 / 11 / 12 / 31）
find-network 更悬殊：goal 0.667、ssh-goal 0.512、plain 0.000。

所以最终报表必须以连续分为主、二值 reward 为辅。

两个坑：
  1. 字段名不统一 —— 有的任务只写 `pass_rate`，没有 `partial_score`（rust-java-lsp）。
  2. 正在重跑的 trial 也会留下 metrics.json，但内容是 `phase: initialized`、
     passed=0、partial_score=0.0。把它当成绩会**凭空造出一个 0 分**，
     而那条臂其实还在跑。必须按 phase / 是否有完成的 result.json 排除。

【这套约定不是 harbor 的，是 SWE-Marathon 任务自己写的】
partial_score / pass_rate / pytest / gates_* / phase=build_failed 全都由任务的
verifier 脚本产出，harbor 只负责那个二值 reward。换 benchmark 时不能假设还在：
Terminal-Bench 4.0 的 66 个任务根本不写 /logs/verifier/metrics.json。
所以本模块由 bench profile 的 BENCH_HAS_PARTIAL 控制，为 0 时**整体跳过并说明
原因**，不做静默兜底 —— 静默兜底会渲染出一整列 0.0，被读成"全都没得分"，
比没有这一列更坏。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys

if os.environ.get("BENCH_HAS_PARTIAL", "1") != "1":
    bench = os.environ.get("WEN_BENCH", "?")
    print(f"  （跳过：bench={bench} 的任务不写 /logs/verifier/metrics.json，"
          f"没有连续分约定。分数以二值 reward 为准。）")
    raise SystemExit(0)

ARMS = ("plain", "goal", "ssh-goal", "codex-cli", "heartbeat")


def norm(a: str) -> str:
    return re.sub(r"-\d{3,}$", "", a)


def score(d: dict) -> float | None:
    """连续分：优先 partial_score，回退 pass_rate。两者都没有就返回 None。"""
    for k in ("partial_score", "pass_rate"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def testrate(d: dict) -> float | None:
    """测试通过率——比 partial_score 更稳的连续口径。

    【为什么需要第二个口径】s3-clone 这类"多阶段 + CUA 评审"的任务，
    `partial_score` 被后一个阶段按 `0.5*unit_tests_score + 0.5*cua_rubric_score`
    改写，而两个子分各自是**二值**的（scoring_mode=binary）。实测 s3-clone/codex-cli
    22 个 gate 过了 16 个、pytest 大部分通过，`partial_score` 仍然是 0.0——
    它那句 stage_note 自己写着"partial_score is gates_passed/gates_total"，
    和实际写入的值互相矛盾。

    所以再算一个纯粹的测试通过率：
      - `pytest` 字段（各分组 passed/total）优先
      - 其次 passed/total 顶层字段
      - 再次 gates_passed/gates_total
    报表里两列并排给出，哪个都不单独下结论。
    """
    pt = d.get("pytest")
    if isinstance(pt, dict) and pt:
        p = sum((g or {}).get("passed") or 0 for g in pt.values() if isinstance(g, dict))
        t = sum((g or {}).get("total") or 0 for g in pt.values() if isinstance(g, dict))
        if t:
            return p / t
    p, t, f = d.get("passed"), d.get("total"), d.get("failed")
    if isinstance(p, (int, float)) and isinstance(t, (int, float)) and t:
        return p / t
    # cargo test 类任务只写 passed/failed，没有 total
    if isinstance(p, (int, float)) and isinstance(f, (int, float)) and (p + f):
        return p / (p + f)
    gp, gt = d.get("gates_passed"), d.get("gates_total")
    if isinstance(gp, (int, float)) and isinstance(gt, (int, float)) and gt:
        return gp / gt
    return None


def usable(m: pathlib.Path, d: dict) -> bool:
    """排除还没跑完的 trial 留下的半成品 metrics。"""
    if str(d.get("phase") or "").lower() in ("initialized", "starting", ""):
        # phase 缺失时不能一概排除（多数任务不写 phase），只在明确是初始态时排除
        if "phase" in d:
            return False
    # 该 job 必须有 completed 的 result.json
    job = m.parent.parent.parent            # <task>/<arm>/<stamp>/<arm>
    for r in job.glob("result.json"):
        try:
            s = json.loads(r.read_text()).get("stats", {})
        except Exception:
            continue
        if int(s.get("n_completed_trials") or 0) >= 1:
            return True
    return False


def main() -> int:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "marathon-full")
    cell: dict[tuple[str, str], float] = {}
    skipped = 0
    for m in sorted(out.glob("*/*/*/*/*/verifier/metrics.json")):
        # 【坑】必须 relative_to(out) 再取 parts。直接用 m.parts[1] 只在 out 是
        # 相对路径时碰巧对；progress.sh 传的是绝对路径，那时 parts[1] 是 "mnt"，
        # 后面 stat() 抛 FileNotFoundError，而调用方 2>/dev/null 把 traceback
        # 吞掉了 —— 整段连续分静默消失，看起来像"还没有数据"。
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

    if not cell:
        print("  还没有可用的 metrics.json")
        return 0

    print("  每格 = partial_score / 测试通过率")
    print(f"  {'任务':26}" + "".join(f"{a:>13}" for a in ARMS))
    for t in sorted({t for t, _ in cell}):
        line = f"  {t[:26]:26}"
        for a in ARMS:
            v = cell.get((t, a))
            if v is None:
                line += f"{'—':>13}"
            else:
                ps, tr = v
                a1 = f"{ps:.3f}" if ps is not None else "?"
                a2 = f"{tr:.3f}" if tr is not None else "?"
                line += f"{a1+'/'+a2:>13}"
        print(line)

    print(f"  {'臂均值':26}", end="")
    for a in ARMS:
        vs = [v[0] for (t, x), v in cell.items() if x == a and v[0] is not None]
        ts = [v[1] for (t, x), v in cell.items() if x == a and v[1] is not None]
        m1 = f"{sum(vs)/len(vs):.3f}" if vs else "—"
        m2 = f"{sum(ts)/len(ts):.3f}" if ts else "—"
        print(f"{m1+'/'+m2:>13}", end="")
    print()
    print(f"  {'(n)':26}", end="")
    for a in ARMS:
        vs = [v for (t, x), v in cell.items() if x == a]
        print(f"{f'(n={len(vs)})':>13}", end="")
    print()

    # 只在**同任务都有数据**的格子上比较，避免任务集偏差
    common = [t for t in {t for t, _ in cell}
              if sum(1 for a in ARMS if (t, a) in cell) >= 2]
    if common:
        print(f"  —— 仅用两臂以上都跑过的 {len(common)} 个任务配对比较 ——")
        for a in ARMS:
            vs = [cell[(t, a)][0] for t in common if (t, a) in cell and cell[(t, a)][0] is not None]
            ts = [cell[(t, a)][1] for t in common if (t, a) in cell and cell[(t, a)][1] is not None]
            if vs or ts:
                m1 = f"{sum(vs)/len(vs):.3f}" if vs else "—"
                m2 = f"{sum(ts)/len(ts):.3f}" if ts else "—"
                print(f"    {a:10} partial={m1} 测试通过率={m2}  (n={len(vs)}/{len(ts)})")
    if skipped:
        print(f"  （跳过 {skipped} 份未完成 trial 的半成品 metrics）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
