# WebGen Session File Watch Design

## 背景

当前直播链路已经具备两层能力：

- 通过 `sessions_history(...)` 拉增量消息
- 通过 session 文件变化决定是否值得去拉 history

但这套能力被挂在 `runtime/live-webgen-progress.py` 这种短生命周期 worker 上。只要 worker 空闲退出，而当前投递策略又是 `manual_pull`，主对话就不会再自动收到新增播报。

这说明问题不在“是否看得到 session 变化”，而在：

- 监听进程不常驻
- `manual_pull` 被误当成直播正常
- 空闲退出后没有真正的后台续航者接管

## 目标

在保留现有 watch state 和 resume 语义的前提下，把直播从“可恢复短 worker”升级成“中央常驻 supervisor + 明确降级态”：

- session 文件变化仍然作为 history 拉取触发器
- 监听职责从短 worker 提升为常驻 supervisor
- `manual_pull` 不再伪装成 active，而是显式 degraded
- 没有自动投递能力时，新增进展进入 backlog，等待下次主回合补播

## 非目标

- 不直接把 `.jsonl` 当业务语义源解析
- 不改 deterministic resume、`slug -> sessionKey` 绑定
- 不依赖 cron 恢复旧路径
- 不要求 runtime 先支持 hidden wake 才能落地

## 结论

推荐方案是：

- 保留 session 文件监听
- 保留 `sessions_history(...)` 作为标准消息读取源
- 新增一个常驻 `live-watch-supervisor`
- 把 `live-webgen-progress.py` 降级为一次性补偿 worker / 调试入口
- 把 `manual_pull` 明确标成 `degraded`

这是当前最小但正确的结构升级。只修文件变化检测，不能解决漏播。

## 核心决策

### 1. 引入常驻 supervisor

新增：

- `runtime/live-watch-supervisor.py`

职责：

- 周期性扫描 `runtime/state/live-watches/*.json`
- 只接管 `pending / active / degraded` 的 watch
- 为每个 watch 持续监听目标 session 文件变化
- 检测到变化后增量拉 `sessions_history(...)`
- 根据投递策略决定立即回推还是进入 backlog

这一步把“监听是否存在”从某个短 worker 是否正好活着，改成独立的、可观察的后台事实。

### 2. `manual_pull` 改成显式 degraded

当前错误在于：

- `deliveryStrategy=manual_pull`
- `status=idle`

仍然容易被误解成“监听逻辑正常，只是暂时安静”。

新语义改为：

- `hidden_wake / rebroadcast` 且 supervisor 正常：`status=active`
- 只有 `manual_pull`：`status=degraded`
- 已完成：`done`
- 等待用户：`blocked`

`degraded` 的含义必须固定为：

- 可以继续采集新增
- 不保证自动播报
- 必须积压 backlog

### 3. session 文件仍只做触发器

保持不变：

- `.jsonl` 文件只用于判断“是否有新动作”
- 真正消息仍通过 `sessions_history(sessionKey=..., includeTools=true, limit=N, afterSeq=...)` 获取

原因：

- `.jsonl` 存储格式不是稳定契约
- 现有摘要、去重、终态判断已经都建立在 history 之上
- 本次要修的是“监听生命周期”和“自动投递语义”

### 4. backlog 成为一等状态

当投递层不可自动回推时，不允许“看到了新增但静默丢掉”。

state 新增：

- `last_delivered_seq`
- `pending_broadcast_items`
- `pending_count`
- `last_pending_summary`

行为：

- supervisor 发现新增，但当前只能 `manual_pull`
- 将摘要写入 backlog
- 下一次普通用户回合先补播 backlog，再继续监听恢复

### 5. supervisor 负责 session 文件重解析

文件 rotate / reset / 路径迁移时：

- 先检测旧路径失效
- 再回读 `sessions.json`
- 刷新 `session_file_path`
- 继续监听新文件

这部分逻辑沿用刚完成的“旧路径失效后重解析”能力，但执行主体从短 worker 升级为常驻 supervisor。

## 组件设计

### `runtime/live-watch-supervisor.py`（新增）

建议职责：

- 启动单实例守护
- claim 全局 supervisor lease
- 周期扫描 watch state
- 对每个 watch 执行：
  - session 文件定位 / 重定位
  - 文件状态采样
  - 文件变化去抖
  - history 增量拉取
  - batch 摘要生成
  - 自动回推或 backlog 落盘

建议状态写入：

- `supervisor_pid`
- `supervisor_started_at`
- `supervisor_heartbeat_at`
- `last_poll_at`

### `runtime/live_watch.py`

扩展 `WatchState`：

- `last_delivered_seq`
- `pending_broadcast_items`
- `pending_count`
- `last_pending_summary`
- `supervisor_pid`
- `supervisor_started_at`
- `supervisor_heartbeat_at`
- `delivery_degraded_reason`

新增 helper：

- `watch_requires_supervisor(...)`
- `watch_is_delivery_degraded(...)`
- `take_pending_broadcast_batch(...)`

### `runtime/ensure-live-watch.py`

职责从“给 short worker 下指令”改成：

- 检查 watch state 是否存在
- 检查 supervisor 是否存活
- 检查当前 watch 是否已经注册
- 返回：
  - `start`
  - `resume`
  - `active`
  - `degraded`
  - `idle`

如果 supervisor 不存在：

- 返回启动 supervisor 的 invocation

如果 strategy 是 `manual_pull`：

- 返回 `degraded`
- 不能再伪装成 `active`

### `runtime/live-webgen-progress.py`

保留但降级定位：

- 一次性补偿 worker
- supervisor 内部复用的单 watch cycle helper
- 手工调试入口

不再承担“后台一直活着监听”的主责任。

## 运行模型

### 正常自动直播

1. main 创建或恢复 watch state
2. `ensure-live-watch.py` 确认 supervisor 存在
3. supervisor 常驻监听目标 session 文件
4. 文件变化后拉 `sessions_history(...)`
5. 若 `rebroadcast / hidden_wake` 可用，立即回推主对话
6. 更新 `last_seen_seq / last_delivered_seq`

### 降级直播

1. main 创建 watch
2. `ensure-live-watch.py` 发现只有 `manual_pull`
3. watch 标成 `degraded`
4. supervisor 仍继续采集新增
5. 新增摘要写入 backlog
6. 下次主会话被唤起时补播 backlog

## 异常与边界

### 1. supervisor 不存在

处理：

- `ensure-live-watch.py` 必须能重启它
- 不能只返回一个“resume short worker”就算恢复完成

### 2. session 文件存在变化，但 history 没新增

处理：

- 更新文件采样状态
- 不回推
- 不推进 `last_delivered_seq`

### 3. rebroadcast 失败

处理：

- 降级为 `degraded`
- 把当前 batch 写入 backlog
- 记录 `delivery_degraded_reason`

### 4. watch 已 done / blocked

处理：

- supervisor 停止对其轮询
- 若仍有待补 final summary，则先补一次再归档

## 验收标准

必须同时满足：

1. webgen session 持续追加记录时，即使主对话无人操作，watch state 也持续前进
2. `rebroadcast / hidden_wake` 下，新增进展能自动播报
3. `manual_pull` 下，状态明确是 `degraded`，且 backlog 不丢
4. session 文件轮转、进程重启后，watch 能自动恢复，不回退 cursor
