# Connector Registry（统一公共连接器注册表）

把 LoopX 消费方（含 finance）会用到的各类 **public connector** 统一管理起来：
哪些**已支持**、哪些**待支持/被卡**，它们属于哪一层（L0-L5，对齐 finance
research 的 docs/16 信源蓝图），以及伴随真实使用**演化出的价值优先级**。

## 分层（docs/16）

- L0 基础设施：行情、联网搜索、浏览器抓取、记忆、通知
- L1 官方披露：巨潮公告、交易所问询/监管
- L2 资金流：龙虎榜、两融、沪深港通
- L3 财务：同花顺财务
- L4 舆情/另类：财联社、雪球、百度指数、公众号
- L5 付费/专业：Wind/iFinD、Tushare

## 命令

```bash
loopx connector list --format json      # 全量清单：状态/分层/价值/使用/优先级
loopx connector rank --format json      # 价值优先级排序
loopx connector register <id> --status supported --value-tier P0 ...
loopx connector use <id> --ms 1234      # 记录一次真实调用（成功/耗时）
```

默认状态文件：`$LOOPX_RUNTIME_ROOT/connector-registry.json`（可用 `--path` 覆盖）。

## 价值优先级演化

每个 connector 记使用次数、成功/失败、累计耗时；优先级分数 =
价值档位基准（P0=10/P1=6/P2=3）− 待支持/受阻惩罚 + 0.2×成功 − 0.5×失败。
每次 `connector use` 都会重算分数，`rank` 输出最新排序——这就是"伴随使用
演化出 connector 价值优先级排序"的机制。

## 与 finance 的对接

- finance 脚本按 connector id 标注数据源（`sina-daily`/`ths-financial`/
  `ark-web-search`/`ego-browser`…），每次真实调用后 `loopx connector use <id>`。
- 待支持队列（巨潮公告、龙虎榜、两融、港通）对应 finance 的 P0/P1 建设路线；
  受阻项（财联社/雪球条款、付费源预算）在 registry 里标 `blocked` + `blocker`。
