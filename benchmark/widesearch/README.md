# WideSearch on LoopX (local practice)

Local WideSearch（公开 web 表格填充 benchmark，200 题）practice：同一模型、同一
任务、同一官方 verifier 下对比 baseline（native Codex Goal）与 treatment
（LoopX-guided control），用于论证 LoopX 能力。不是官方 leaderboard 结果。

## 方法

- 数据：公开 HuggingFace `WideSearch` 数据集（200 题），公共 `instruction.md`
  + `task.json`（evaluation 契约）；private `gold.csv` 仅 evaluator 阶段使用。
- Agent：本地 `codex app-server`（native /goal），web search 用 ARK Responses
  原生 `tools.web_search`（无需额外 MCP key）。
  - baseline objective：直接完成指令；
  - treatment objective：先用 LoopX skill `/loopx` 在任务工作区启动 goal，
    走 LoopX 控制面（todos/state writeback）完成任务。
- Verifier：官方 `widesearch_evaluator.py`（SR / 行级 / 项级 F1 + LLM judge，
  judge 复用 ARK 模型）。

## 答案隔离边界（重要）

本地路径是**过程性隔离**，不是沙盒强隔离：
- 每次 run 用独立 fresh workspace，run 前清空，杜绝旧答案误用；
- answer 必须存在、非空、mtime 晚于 run 开始（否则判定失败）；
- evaluator 在 agent 结束后独立后置执行，只读 sealed answer + gold；
- 但 agent（codex）拥有宿主全盘读权限（`workspace-write` 不挡读；macOS
  `sandbox-exec` 会破坏 codex 运行时，已实测证伪），因此**不能假定 agent 读不到
  gold**。任何结论都限定为内部能力论证，发布权威结果需真沙盒
  （pier/colima docker 或云端 sealed-dual 强隔离）。

## 运行

```bash
# 数据准备：raw jsonl -> case 工作区（数据不提交进仓库，用本地路径）
python benchmark/widesearch/tasks.py prepare --case ws_en_001 \
  --raw <path>/widesearch.jsonl --gold <path>/gold

# baseline / treatment（需 python 3.11+；项目内建议 uv python 3.12）
uv run --python 3.12 --with dateparser==1.2.2 \
  python benchmark/widesearch/run_widesearch_case.py \
  --arm baseline --case ws_en_001 --data-root <data-root>

uv run --python 3.12 --with dateparser==1.2.2 \
  python benchmark/widesearch/run_widesearch_case.py \
  --arm treatment --case ws_en_001 --data-root <data-root>
```

模型凭据：`ARK_OPENAI_BASE_URL` / `ARK_OPENAI_API_KEY` / `ARK_OPENAI_MODEL`
（本地可从 cc-switch `volcengine-ark-deepseek` 读取）。

## 测试

```bash
uv run --python 3.12 --with dateparser==1.2.2 pytest benchmark/widesearch/tests
```

覆盖：fresh/stale answer 检测、evaluator 链路（gold 自检）、objective 两臂差异。
