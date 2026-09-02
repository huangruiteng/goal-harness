#!/usr/bin/env python3
"""从每个 trial 的 codex rollout 抽出可读轨迹，落成 viz/trajectories/<task>__<arm>.json。

轨迹步骤 kind：
  goal     首条 developer/user 里的 goal body（plain vs LoopX 的关键差异就在这）
  msg      assistant/user/developer 文本消息
  reason   推理（多为加密，仅留标记；有 summary 就带上）
  exec     工具调用（code-mode 全走 exec，抽出 cmd）
  output   工具输出（截断）
  event    task_started / task_complete / goal_updated

用法： _extract_traj.py marathon-full viz/trajectories
"""
from __future__ import annotations
import json, os, re, sys, pathlib

ARMS = ("plain", "goal", "ssh-goal", "codex-cli", "heartbeat")
OUT_HEAD, OUT_TAIL = 1000, 240      # 输出保留首尾
CMD_CAP = 1200
GOAL_CAP = 6000


def norm(a): return re.sub(r"-\d{3,}$", "", a)


def clip(s, head, tail=0):
    s = s or ""
    if len(s) <= head + tail + 40:
        return s
    if tail:
        return s[:head] + f"\n…(略 {len(s)-head-tail} 字)…\n" + s[-tail:]
    return s[:head] + f"…(略 {len(s)-head} 字)"


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    for c in content or []:
        if isinstance(c, dict):
            out.append(c.get("text") or c.get("output") or "")
        else:
            out.append(str(c))
    return "".join(out)


def extract_cmd(inp: str) -> str:
    """从 exec 的 JS input 里抽 cmd 字段；抽不出就返回原串截断。"""
    if not isinstance(inp, str):
        return json.dumps(inp, ensure_ascii=False)[:CMD_CAP]
    m = re.search(r'cmd\s*:\s*"((?:[^"\\]|\\.)*)"', inp)
    if not m:
        m = re.search(r'cmd\s*:\s*`([^`]*)`', inp)
    if m:
        try:
            return clip(json.loads('"' + m.group(1) + '"') if '\\' in m.group(1) else m.group(1), CMD_CAP)
        except Exception:
            return clip(m.group(1), CMD_CAP)
    return clip(inp, CMD_CAP)


def parse_rollout(fp: pathlib.Path):
    steps = []
    goal_seen = False
    for line in fp.read_text(errors="replace").splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        t = o.get("type")
        pl = o.get("payload")
        if not isinstance(pl, dict):
            continue
        if t == "response_item":
            st = pl.get("type")
            if st == "message":
                role = pl.get("role", "?")
                body = text_of(pl.get("content"))
                if not body.strip():
                    continue
                # LoopX 的关键自变量：注入的 goal 上下文（plain 模式没有这条）
                if 'codex_internal_context source="goal"' in body or "active thread goal" in body:
                    steps.append({"kind": "goal", "role": role, "text": clip(body, GOAL_CAP)})
                    goal_seen = True
                else:
                    steps.append({"kind": "msg", "role": role, "text": clip(body, 2500)})
            elif st == "reasoning":
                summ = pl.get("summary") or []
                txt = " ".join(text_of([s]) if isinstance(s, dict) else str(s) for s in summ)
                steps.append({"kind": "reason", "text": clip(txt, 800) if txt.strip() else ""})
            elif st in ("custom_tool_call", "function_call"):
                steps.append({"kind": "exec", "name": pl.get("name", "exec"),
                              "text": extract_cmd(pl.get("input", ""))})
            elif st in ("custom_tool_call_output", "function_call_output"):
                steps.append({"kind": "output", "text": clip(text_of(pl.get("output")), OUT_HEAD, OUT_TAIL)})
        elif t == "event_msg":
            et = pl.get("type")
            if et == "task_started":
                steps.append({"kind": "event", "text": "task_started"})
            elif et == "task_complete":
                steps.append({"kind": "event", "text": "task_complete"})
            elif et == "thread_goal_updated":
                steps.append({"kind": "event", "text": "goal_updated（续跑/心跳）"})
    return steps


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "marathon-full")
    outdir = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "viz/trajectories")
    outdir.mkdir(parents=True, exist_ok=True)
    index = {}
    for task_dir in sorted(root.glob("*")):
        if not task_dir.is_dir() or task_dir.name.startswith("."):
            continue
        task = task_dir.name
        for arm_dir in task_dir.glob("*"):
            arm = norm(arm_dir.name)
            if arm not in ARMS:
                continue
            try:
                if arm_dir.stat().st_uid != os.getuid():
                    continue
            except OSError:
                continue
            rolls = sorted(arm_dir.glob("**/agent/sessions/**/rollout-*.jsonl"))
            if not rolls:
                continue
            steps = []
            for r in rolls:              # 多份则按名字顺序拼（续跑）
                steps.extend(parse_rollout(r))
            if not steps:
                continue
            key = f"{task}__{arm}"
            payload = {"task": task, "arm": arm, "n_steps": len(steps), "steps": steps}
            (outdir / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False))
            index.setdefault(task, {})[arm] = len(steps)
    (outdir / "_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    ntot = sum(len(v) for v in index.values())
    print(f"写出 {ntot} 条轨迹到 {outdir}/（{len(index)} 任务）")
    # 抽样看大小
    big = sorted(outdir.glob("*.json"), key=lambda p: p.stat().st_size, reverse=True)[:3]
    for p in big:
        print(f"  最大: {p.name} {p.stat().st_size//1024}KB")


if __name__ == "__main__":
    raise SystemExit(main())
