#!/usr/bin/env python3
"""把五模式聚合（viz/data.json）里的观察，投影成 LoopX 官方的
`benchmark_case_insight_projection_v0` 记录（见 upstream #3878 / RFC #3812）。

契约要点（对齐 loopx/capabilities/benchmark_toolkit/study_projection.py）：
  · 每条 insight 是某次 terminal run 的 child：带 case_id + run_id + terminal outcome_status
  · privacy_classification = public_safe；producer_redaction_attested = True
  · 只放**精简/脱敏**结论：causal_summary / implication / next_probe 各 ≤600 字符
  · evidence_refs 只放句柄（run_dir 之类），**不含** raw 轨迹/工具输出
  · outcome_status ∈ {completed, runner_invalid, cancelled}（终态）
  · expectedness ∈ {expected, unexpected, mixed, unknown}；confidence ∈ {low, medium, high}

本脚本只**产出**记录，不上传；真正 attach 需要 experiment-board 上对应的 run row
（见 README 血缘：board run 属后续 follow-up）。用法：
    case_insights.py viz/data.json case_insights.json
"""
from __future__ import annotations

import json
import re
import sys

from _common import safe_path

SCHEMA = "benchmark_case_insight_projection_v0"
BENCHMARK_ID = "swe-marathon"
STUDY_ID = "codex-loopx-access-modes"
TERMINAL = {"completed", "runner_invalid", "cancelled"}
_COMPLETE = "complete"


def _clip(s: str, limit: int = 600) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _run_id(run_dir: str, task: str, arm: str) -> str:
    """从 run_dir 派生稳定、public-safe 的 run 句柄。

    刻意**不含** stamp：run_dir 里带的是具体运行时间戳（过细的私有细节），
    evidence 句柄只保留 case+arm 这一层，避免把运行时刻也列入公开产物。
    """
    raw = f"{task}__{arm}"
    return re.sub(r"[^A-Za-z0-9._-]", "-", raw).strip("-._")


def _outcome_status(cell: dict) -> str:
    """把我们的 goal-receipt 状态映射到契约的终态。

    complete → completed；构建失败/blocked/其它 → runner_invalid（该次运行未产出
    可countable的能力结果，属运行侧失败，不是模型能力定论）。
    """
    if cell.get("status") == "complete" and not cell.get("build_failed"):
        return "completed"
    return "runner_invalid"


def _build_failed_insight(task: str, arm: str) -> tuple:
    return ("build_failed_gate_zeroed",
            (f"{arm} 在 {task} 构建阶段失败，partial_score 被门禁归零；"
             f"属运行/环境侧失败，非模型能力定论。"),
            "该格作为观测计入 matched 分母并单列标注，不单臂剔除。",
            "重复运行以区分偶发构建失败与稳定失配；必要时对齐镜像/依赖。",
            "unexpected", "medium")


def _idle_churn_insight(task: str, arm: str, unblock: int, cont: int) -> tuple:
    return ("unattended_continuation_idle_churn",
            (f"{arm} 在 {task} 多轮续跑退化为空转：unblock={unblock}、cont={cont}、"
             f"终态未 {_COMPLETE}；与其 guard 缺 --begin-turn、按人值守 TUI 设计而被"
             f"适配到无人运行有关（假设）。"),
            "codex-cli 的表现更可能受 harness 与无人运行方式匹配度影响，而非模型能力弱。",
            "补 --begin-turn / 对齐回合边界后重跑；比较有效工作 Turn 与重复 blocked。",
            "unexpected", "medium")


def _stable_continuation_insight(task: str, arm: str, cont: int,
                                 reward, partial) -> tuple:
    return ("none_observed",
            (f"{arm} 在 {task} 由外部 driver 持有 Turn 边界、每轮重读 worktree，"
             f"经 {cont} 轮续跑稳定收敛（reward={reward}, partial={partial}）。"),
            "external automation 驱动的续跑在无人长程下更稳（本轮观测，非因果定论）。",
            "在更多任务与重复运行上验证该趋势是否持续。",
            "expected", "low")


def _insight_for(task: str, arm: str, cell: dict) -> dict | None:
    """只为**有明确洞见**的 case 生成记录（否则返回 None）。"""
    partial = cell.get("partial")
    reward = cell.get("reward")
    build_failed = bool(cell.get("build_failed"))
    unblock = cell.get("unblock") or 0
    cont = cell.get("cont") or 0
    status = cell.get("status")

    if build_failed:
        (fc, causal, impl, probe, exp, conf) = _build_failed_insight(task, arm)
    elif arm == "codex-cli" and status != _COMPLETE and unblock >= 5:
        (fc, causal, impl, probe, exp, conf) = _idle_churn_insight(task, arm, unblock, cont)
    elif (arm == "heartbeat" and status == _COMPLETE and cont > 0
          and (reward == 1 or (partial or 0) >= 0.99)):
        (fc, causal, impl, probe, exp, conf) = _stable_continuation_insight(
            task, arm, cont, reward, partial)
    else:
        return None

    rid = _run_id(cell.get("run_dir", ""), task, arm)
    return {
        "schema_version": SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "study_id": STUDY_ID,
        "case_id": task,
        "run_id": rid,
        "outcome_status": _outcome_status(cell),
        "failure_class": fc,
        "causal_summary": _clip(causal),
        "expectedness": exp,
        "implication": _clip(impl),
        "next_probe": _clip(probe),
        "confidence": conf,
        # 只放 case+arm 句柄（无 stamp / 无 raw）；具体 run 目录属私有证据。
        "evidence_refs": [f"run:{rid}"],
        "privacy_classification": "public_safe",
        "producer_redaction_attested": True,
    }


def build(data: dict) -> list[dict]:
    out = []
    for task, cols in data.get("cells", {}).items():
        for arm, cell in cols.items():
            if not isinstance(cell, dict):
                continue
            rec = _insight_for(task, arm, cell)
            if rec:
                out.append(rec)
    out.sort(key=lambda r: (r["case_id"], r["run_id"]))
    return out


def main() -> int:
    src = safe_path(sys.argv[1] if len(sys.argv) > 1 else "viz/data.json")
    outp = safe_path(sys.argv[2] if len(sys.argv) > 2 else "case_insights.json")
    data = json.loads(src.read_text())
    records = build(data)
    payload = {
        "note": ("public-safe case-insight projections for the codex×LoopX SWE-Marathon "
                 "study; conforms to benchmark_case_insight_projection_v0 (upstream #3878 / "
                 "RFC #3812). Attaching to an experiment-board run is a follow-up."),
        "schema_version": SCHEMA,
        "count": len(records),
        "records": records,
    }
    outp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"写出 {outp}：{len(records)} 条 case-insight")
    for r in records:
        print(f"  {r['case_id']:26} {r['failure_class']:34} "
              f"exp={r['expectedness']:10} conf={r['confidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
