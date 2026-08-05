# 实测证据：NoKV shadow provider 端到端验收（v0）

- 配套 RFC：[多端共享 Goal 的在线权威与可插拔状态 Provider (v0)](./shared-goal-authority-state-provider-v0.zh-CN.md)
- 参考实现与探针：[`examples/nokv-shadow-provider/`](../../../examples/nokv-shadow-provider/)
- 实测日期：2026-08-05。NoKV 主干最新提交，**零源码改动**；全部
  数字来自真实栈（etcd + S3 兼容存储 + `nokv serve` + Python SDK），
  不是设计期估算。

## 1. 总裁决

Provider 契约的核心性质（CAS 安全、恰一次 applied、幂等重试、
多 goal 独立演进）在真实栈上**全部成立**。两条重要限定：

1. 适配器必须是"策略层"而非纯映射：RFC §5 的四条纪律缺任何一条，
   typed conflict 语义就会失真或产生双写（见 §3 探针 P2 的
   朴素版 vs 策略版对比）。
2. NoKV 进程崩溃后的服务恢复目前 fail-closed（拒绝在未验证状态上
   重启接管），数据不丢但服务不可自动恢复。shadow 角色可容忍
   （只降低对账覆盖率），晋升为 primary 前该能力必须落地。

## 2. 环境配方

单机（macOS 开发机），全部服务绑 127.0.0.1：

```bash
# S3 兼容存储（127.0.0.1:9000）+ 建桶
aws --endpoint-url http://127.0.0.1:9000 s3 mb s3://nokv-loopx-e2e

# etcd 单节点（127.0.0.1:2379）
etcd --listen-client-urls http://127.0.0.1:2379 \
     --advertise-client-urls http://127.0.0.1:2379

# NoKV：provision 一次，serve 常驻
nokv --root-id <ROOT_ID> --etcd-endpoint http://127.0.0.1:2379 \
     --etcd-key-prefix /nokv/loopx-e2e provision <LOGICAL_SHARD_ID>
nokv --root-id <ROOT_ID> ...（对象存储与绑定参数见示例 README）serve

# Python SDK：pip install <nokv-repo>/crates/nokv-python（maturin）
```

注意事项（实测踩过的坑）：客户端 `RoutingConfig.etcd(...,
key_prefix=...)` 必须与 provision 时的 `--etcd-key-prefix` 一致，
否则报 "root placement does not exist"。

## 3. 探针逐项结果

| 探针 | 内容 | 裁决 |
|---|---|---|
| P1 | 单次 claim_work（CreateOnly，expected_revision=0） | **PASS**：`applied` + authority_revision=1 + lease_id/epoch/expires_at 齐全，156.75ms |
| P2 | 8 端并发、同一 expected_revision，× 20 轮 | **PASS**：恰一个 `applied` 20/20，安全不变量零破。朴素适配器下 7 个输家常拿到底层争用错误而非干净 conflict；按 RFC §5 纪律 3/4 加入分类与有界重试后，20 轮全部严格干净：恰 1 applied、7 conflict、7/7 学到 current_revision、0 anomalies |
| P3 | 历史命令重放（head 已前移 42 版） | **PASS**：`already_applied`（superseded），revision 前后不变，零状态变更 |
| P3b | 最近赢家携原 expected_revision 崩溃重试 | **PASS**：`already_applied`，恢复出原 lease_id（lease_id_stable=true），无双写 |
| P4 | applied 后 kill -9 `nokv serve` | 数据完好：元数据目录完整，WAL（写前日志）同步落盘策略下已确认提交不丢；**但服务恢复 fail-closed**（"successor acquisition ... is unavailable in the local-WAL profile"），无法重启回读做端到端复验。shadow 可容忍，晋升硬门槛 |
| P5 | 100 轮串行 compare_and_put + load | **PASS**（见下表）。发现一处瞬态：发布终结阶段与后台 lifecycle 任务的版本冲突可把单次发布楔住数秒（100 轮中 2 次，秒级自愈，适配器归类为可重试后收敛为 already_applied）。恰一次记账实证：终版 revision = 起点 42 + 100 命令 = 142，无双写无丢失 |
| P6 | 单 root 下 goal-alpha / goal-beta 两前缀交替写 | **PASS**：两边 generation 各自 1→2→3，独立演进（independent=true） |

## 4. 延迟分布（P5，100 轮）

| 动作 | p50 | p95 | p99 | mean | max |
|---|---|---|---|---|---|
| compare_and_put | 85.7ms | 114.3ms | 5612.7ms | 197.9ms | 5612.7ms |
| load | 24.7ms | 32.4ms | 36.4ms | 24.6ms | 36.4ms |

对照 RFC §8 预算：load 远低于只读投影 P95 5 秒；compare_and_put
p50/p95 对每命令一次的影子写成本可忽略；p99 长尾完全由上述 2% 的
瞬态楔住事件贡献（秒级自愈），已列入 NoKV 侧修复项。

## 5. SDK 边界实测发现（适配器为什么必须是策略层）

1. **冲突的结构化字段在 Python 边界丢失**：generation 冲突到达
   Python 侧只剩字符串消息，`current_generation` 等结构化字段被
   丢弃。适配器以"冲突后重新 stat/load 取当前版本"兜底（实测稳定）；
   NoKV 侧已排期类型化冲突异常。
2. **"同一操作 id 携带不同内容"错误 = 已落账证明**：head 文档含
   墙钟字段时重试重建的字节不同，服务端拒绝重放。该错误本身就证明
   原命令已 applied，必须转成 `already_applied`，绝不能换新 id
   重发（会双写）。这直接导出 RFC §5 纪律 2（信封字节确定）。
3. **失败尝试会烧掉确定性操作 id**：适配器用固定规则轮换（首个
   规则值保留给崩溃重放识别）解决。
4. **读路径瞬态竞态**：head 被并发替换为更小 body 的瞬间，按旧
   元数据发起的范围读会被拒绝；SDK 不自动重试此类，适配器 load()
   自带有界重试（实测 10 次内全部收敛）。

## 6. 结论

出厂 NoKV 栈今天即可承载 RFC 定义的 shadow provider 契约；四条
适配器纪律（RFC §5）与上述 SDK 边界发现是同一枚硬币的两面：纪律
不是风格建议，是实测中每一条都触发过的正确性前提。晋升为 primary
的唯一硬阻塞是崩溃后的服务恢复（P4），与 RFC §11 的晋升评估一致。
