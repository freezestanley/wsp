# WebGen State-Driven Live Broadcast Design

**Problem**

当前直播链路的主驱动力仍然是 `cron wake`。虽然 workspace 已经补了 `rebroadcast`、`needs_rechain` 和普通用户回合补链，但系统行为本质上仍然依赖：

- `cron` 是否能继续创建/更新下一跳
- `wake` 是否能稳定回到目标对话
- runtime 是否支持 hidden/internal wake

这导致三个长期问题：

1. `Cron tool is restricted to the current cron job.` 会直接打断主链路
2. 迁移到不能修改 runtime 的其他 OpenClaw 实例时，能力差异很大
3. 工程结构上“首次启动”“续链”“补链”是三套近似但不完全相同的决策路径

**Goal**

把 delegated `webgen` 直播从“cron 驱动”改成“状态驱动”，让恢复和续航都依赖持久化 watch state，而不是依赖 cron 子回合继续生成下一条 cron。系统应满足：

- main 进程重启、页面刷新、watcher 异常退出后可以恢复
- 允许短暂中断，但不能丢关键步骤和最终结果
- 不再把 cron 作为主路径前提
- 继续兼容现有 `sessions_history` 摘要逻辑和 `sessions_send` 回推能力

## 兼容约束

### 项目存在检索与 resume 预检保持不变

这次重构只处理“直播如何续航和恢复”，**不处理**“该接哪个项目 session”。

以下能力必须原样保留：

- `runtime/webgen_resume_resolver.py` 的确定性 resume 预检
- `projects/<slug>`、明确 `slug`、唯一精确项目名的命中规则
- `agent:webgen:proj-<slug>` 的项目 session 身份语义
- 命中旧项目后直接复用既有 `sessionKey` 的约束

新的直播状态机必须把这些能力当作前置条件：

1. 先照旧完成项目检索 / resume 预检
2. 拿到最终 `targetSessionKey`
3. 再进入 `watch state + ensure-watch + short worker`

也就是说，**项目定位**和**直播续航**是两层职责，不能在本次重构中耦合。

## 当前方案 vs 新方案

### 当前方案

链路：

`main -> watcher -> cron wake -> sessions_history -> 播报 -> cron wake`

特征：

- 优点：若 runtime 稳定，持续自动播报能力强
- 优点：用户长时间不说话时，理论上也能继续自己醒来
- 缺点：高度依赖 cron/wake/runtime 行为
- 缺点：`needs_rechain` 只是补救路径，不是主路径
- 缺点：迁移时容易被 runtime 能力不一致拖垮

### 新方案

链路：

`main -> watch state -> ensure-watch -> short worker -> sessions_history -> rebroadcast -> state update`

特征：

- 优点：主路径不依赖 cron
- 优点：恢复入口统一为普通用户回合的 `ensure-watch`
- 优点：更适合迁移到无 runtime patch 的实例
- 缺点：短 worker 退出后，到下一次普通用户回合之间存在静默窗口
- 约束：保证“可恢复”和“不丢关键结果”，不承诺“无外部触发的永久在线”

## 设计决策

### 1. 把“定时器”降级为实现细节，把“状态”升为事实源

系统不再依赖某个 `setTimeout`、cron job 或 wake payload 是否还活着。真正需要持久化的是 watch 的业务状态：

- 当前目标 session 是谁
- 已看到哪一条 history
- 已播到哪一条
- 当前是否有 worker 正在接管
- 最终结果是否已送达 origin session

只要这些状态存在，任何一个新拉起的 worker 都能继续工作。

### 2. main 不再承担长期轮询，只承担“ensure”

main 在 delegated 建站场景中的角色改成：

1. 委托 `webgen`
2. 初始化/更新 watch state
3. 在每次普通用户回合开头执行一次 `ensure-watch`

`ensure-watch` 是唯一入口：

- 没有 state -> `start`
- 有 state 且无人接管 -> `start`
- 有 state 且 lease 过期 -> `resume`
- 有 state 且已有活跃 worker -> `active`
- 已终态 -> `idle`

这样“首次启动”和“恢复”不再是两套逻辑。

### 3. worker 改成短生命周期、可重入

worker 不再负责创建下一条 cron，也不追求永久常驻。它的生命周期是：

1. 抢占或续约 lease
2. 用 `sessions_history` 拉取 `last_seen_seq` 之后的新消息
3. 提炼为 1-3 条人话摘要
4. 通过 `sessions_send` 回推到 `origin_session_key`
5. 更新 `last_seen_seq / last_broadcast_seq / phase`
6. 在短窗口内继续轮询
7. 若任务结束则标记终态；若长时间空闲则主动退出

这个模型的重点不是“永远活着”，而是“随时可以被下一次 ensure 接管”。

### 4. 用 lease 代替 `needs_rechain` 作为主恢复信号

现有 `needs_rechain` 保留兼容，但新主路径应改成 lease 模型：

- `lease_owner`
- `lease_until`
- `last_worker_heartbeat_at`
- `status`

含义：

- `lease` 有效：已有 worker 接管，main 不重复启动
- `lease` 过期：视为 worker 丢失，下一次普通用户回合可以安全恢复

`needs_rechain` 以后只做旧 cron 路径兼容，不再是主状态机。

### 5. 最终结果单独保证交付

为了满足“允许短暂中断，但不能丢最终结果”，需要把最终交付状态显式持久化：

- `final_delivered`

语义：

- 任务检测到已结束，但最终摘要尚未成功回推时，`status=done` 且 `final_delivered=false`
- 下一次 ensure 或 worker 恢复时，优先补发最终摘要
- 最终摘要成功送达后，才置 `final_delivered=true`

这样即使 worker 在结束边缘崩掉，也不会丢最终播报。

## 状态模型

在现有 `WatchState` 基础上保留：

- `watch_id`
- `target_session_key`
- `origin_session_key`
- `delivery_strategy`
- `last_seen_seq`
- `last_broadcast_seq`
- `phase`
- `last_progress_summary`

新增：

- `status`：`pending | running | done | blocked | canceled`
- `lease_owner`
- `lease_until`
- `last_worker_heartbeat_at`
- `final_delivered`
- `final_summary`

兼容保留：

- `needs_rechain`
- `rechain_reason`

但其职责降级为旧 cron 路径的兼容桥。

## 组件职责

### `runtime/live_watch.py`

职责：

- 定义和持久化扩展后的 `WatchState`
- 提供 lease 判断和状态迁移 helper
- 保留消息摘要提炼、人话播报批处理能力

### `runtime/ensure-live-watch.py`

职责：

- 成为唯一的 watch 决策入口
- 基于 state 决定 `start / resume / active / idle`
- 输出启动 worker 的标准化 invocation

后续它不再只是“rechain 包装器”，而是主入口。

### `runtime/live-webgen-progress.py`

职责：

- 成为短生命周期 worker
- 在短窗口中轮询 `sessions_history`
- 负责 `rebroadcast`
- 负责 lease heartbeat、空闲退出和最终结果补发

### `runtime/rechain-watch.py` / `runtime/rechain-watch-once.py`

职责：

- 短期保留兼容
- 长期降级为旧 cron 模式的辅助工具

## 故障恢复流

### 场景 A：worker 正常运行

- `lease` 有效
- ensure 返回 `active`
- 不启动第二个 worker

### 场景 B：worker 异常退出

- `lease_until` 过期
- 下一次普通用户回合执行 ensure
- ensure 返回 `resume`
- 拉起新 worker

### 场景 C：main 进程/页面重启

- 内存定时器全部丢失
- 但 state 文件仍在
- 下一次普通用户回合执行 ensure
- 若任务未终态，则重新接管

### 场景 D：任务已结束但最终摘要未送达

- `status=done`
- `final_delivered=false`
- ensure 应优先触发一次补发 worker 或直接返回可执行 invocation

## 非目标

- 不改动项目存在检索、resume 预检和 `slug -> sessionKey` 绑定语义
- 本次不实现系统级 daemon
- 本次不追求“用户永远静默时也永久自动播报”
- 本次不修改上游 runtime
- 本次不立即删除全部旧 cron 兼容代码

## 成功标准

- 主路径不再依赖 cron 续链
- 普通用户回合统一先走 `ensure-watch`
- worker 挂掉后可在下一次普通用户回合恢复
- 不丢最终摘要
- 安装到其他无 runtime patch 的 OpenClaw 实例后，仍能工作在 `rebroadcast` 模式
