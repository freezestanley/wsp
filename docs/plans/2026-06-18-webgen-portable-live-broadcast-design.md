# WebGen Portable Live Broadcast Design

**Problem**

当前直播方案把“继续在当前会话里播报”过度绑定到 runtime 的 hidden wake / main-session cron 路由能力。迁移到其他无 runtime 修改权限的 OpenClaw 实例后，这条链路不稳定，常见结果是 `webgen` 有新进展，但当前用户对话收不到自动播报。

**Goal**

把“当前会话内直播 webgen 消息”改成可迁移能力：优先利用 runtime 的隐藏 wake；若目标实例没有该能力，则退化为显式记录来源会话并把摘要主动回推给该会话；若连回推都不可用，则明确退化成手动拉取进度。

## 能力分层

### A 档：`hidden_wake`

- 适用条件：runtime 支持 hidden/internal wake，且 wake 能绑定当前对话
- 行为：继续使用结构化 wake 载荷，用户只看到真实进展摘要
- 优点：体验最佳，无额外可见控制消息
- 风险：依赖 runtime 能力，不可迁移

### B 档：`rebroadcast`

- 适用条件：可显式获得 `originSessionKey`，且 gateway 支持 `sessions_send(sessionKey=...)`
- 行为：
  - 在委托开始时记录 `originSessionKey`
  - watcher 在自己的承载 session/脚本里轮询 `webgen` 的 `sessions_history`
  - 将新增摘要合并后 `sessions_send` 回 `originSessionKey`
- 优点：不要求修改目标实例 runtime，只依赖现有 sessions 工具
- 风险：控制面消息仍可能可见；需要避免把内部 token/调度文本回推给用户

### C 档：`manual_pull`

- 适用条件：既没有 hidden wake，也无法稳定回推到原会话
- 行为：不承诺自动直播，只保留“当前进度”提示和手动查询能力
- 优点：最稳，不依赖额外路由能力
- 风险：体验最差，需要用户主动追问

## 设计决策

### 1. 显式记录来源会话

`WatchState` 需要新增：

- `origin_session_key`
- `delivery_strategy`

这样 watcher 不再依赖“当前会话”这种 runtime 隐式概念，而是总能知道进度应该回到哪里。

### 2. 把能力判断变成纯函数

新增一个小型能力模型，输入：

- 是否支持 hidden wake
- 是否支持 `sessions_send`
- 是否存在 `originSessionKey`

输出最终策略：

- `hidden_wake`
- `rebroadcast`
- `manual_pull`

这样安装包、主 workspace、其他 OpenClaw 实例都能复用同一套降级逻辑。

### 3. portable 模式下优先“回推摘要”，不是“修 current session”

因为“把 cron 直接打回当前对话”本质是 runtime 功能，workspace 侧不应该伪装成自己能修好它。可迁移方案应该改成：

- 让 watcher 在任意可运行的位置继续工作
- 再把人话摘要显式发回 `originSessionKey`

这解决的是“用户当前对话能收到进展”，而不是“cron 自己理解当前会话”。

## 实现范围

本次只做 workspace 内可落地部分：

1. `runtime/live_watch.py`
   - 持久化 `origin_session_key` / `delivery_strategy`
   - 增加策略选择函数

2. `runtime/live-webgen-progress.py`
   - 增加 `sessions_send` gateway 调用
   - 支持 `rebroadcast` 模式把摘要推回原会话
   - 支持显式参数 `--origin-session-key` 与 `--delivery-strategy`

3. 测试
   - 策略选择
   - 状态持久化
   - portable 回推行为

4. 协议文档
   - `AGENTS.md`
   - `skills/delegated-live-broadcasting/SKILL.md`
   - `skills/webgen/SKILL.md`
   - `docs/webgen-live-broadcast-migration.md`

## 非目标

- 不修改上游 OpenClaw runtime
- 不宣称 hidden wake 已经在所有实例可用
- 不在本次实现中引入新的后台守护进程管理机制

## 成功标准

- 没有 runtime patch 的实例上，直播逻辑能自动退化到 `rebroadcast`
- watcher 能把新增进展摘要回推到记录的 `originSessionKey`
- 仍然严格过滤 `[cron:...]`、wake token、`REPLY_SKIP` 等内部文本
- 文档明确区分增强能力与可迁移基础能力
