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

## Hosted Responses API 兼容（重要）

本地 `codex app-server` 默认会发送 `multi_agent_v1` 动态工具命名空间；部分
hosted Responses 端点会拒绝 `namespace` 工具类型（`unknown tool type:
namespace`）。runner 已默认带 `-c features.multi_agent=false` 保持工具面最小且
provider-neutral，同时保留 goal 工具。部分端点还会拒绝 web_search 的
`external_web_access` 字段，可用 `--disable-web-search` 关闭原生 web_search
工具（agent 改用 shell 联网，配合真沙盒网络策略）。

## 真沙盒（pier/colima）跑法

`benchmark/widesearch/pier/` 提供可复用的 pier 任务模板（task.toml、agent
image、verifier image、verifier test.sh、job.yaml）。要点：

- **workspace/jobs_dir 必须放 `$HOME` 下**：colima 不 bind-mount macOS 的
  `/tmp`，verifier 目录挂到 `/logs/verifier` 会静默失败，导致 reward 永远回
  不到宿主。
- **verifier 镜像需 `WORKDIR /app`**：pier 用 `docker compose cp` 把答案放
  进 verifier 容器，`/app` 必须存在。
- **verifier 的 reward.json 必须纯数值**：pier 的 `VerifierResult` 只收
  `dict[str, float | int]`，字符串 detail 字段会触发校验错误。提交前可用：

  ```bash
  loopx benchmark verify-verifier-reward /path/to/reward.json --require-valid
  ```

  或用 Python API `verify_verifier_reward_json`。
- **gold 只给 verifier**：evaluator 在 separate verifier 环境运行，agent 镜像
  里不含 gold。
- **agent 镜像 `/bin/sh` 需是 bash**：pier 用 `set -o pipefail` 执行 agent
  setup，Debian 默认 dash 不支持（`ln -sf /usr/bin/bash /bin/sh`）。

## 测试

```bash
uv run --python 3.12 --with dateparser==1.2.2 pytest benchmark/widesearch/tests
```

覆盖：fresh/stale answer 检测、evaluator 链路（gold 自检）、objective 两臂差异。
