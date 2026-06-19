# WebGen Session File Watch Design

## 背景

当前直播主链路已经从 cron 迁到 `watch state + ensure-live-watch + short worker`，但 worker 仍通过固定间隔调用 `sessions_history(...)` 轮询目标 session。

这带来两个问题：

- 实时性受轮询间隔限制，短间隔会增加无效请求
- worker 明明知道底层 session 已经落盘到本地文件，却没有利用文件变化作为更准确的触发信号

## 目标

在**不推翻现有状态驱动架构**的前提下，把 worker 的触发源从“时间轮询”改成“session 文件变化触发”，同时保留当前恢复链路：

- 保留 `ensure-live-watch.py` 的 `start / resume / active / idle`
- 保留 `WatchState`、`lease`、`lastSeenSeq / lastBroadcastSeq`
- 保留最终以 `sessions_history(...)` 作为标准消息读取源
- 允许 worker 短生命周期退出，并在后续通过 `ensure` 恢复

## 非目标

- 不把直播主路径改成常驻 daemon
- 不把 `.jsonl` 直接作为业务消息解析源
- 不改 deterministic resume、`slug -> sessionKey` 绑定和现有委托语义
- 不移除现有 `interval` 参数；它在新方案里降级为文件探测与 fallback 的节流参数

## 核心决策

### 1. `.jsonl` 只做触发器，不做语义源

目标 session 的底层文件实际位于：

- `~/.openclaw/agents/<agent>/sessions/<session-id>.jsonl`

该文件会随着 session 消息持续追加。新方案只把它当作“有新动作发生”的信号源。一旦检测到变化，worker 仍调用：

- `sessions_history(sessionKey=..., includeTools=true, limit=N)`

来拿标准化消息，再沿用现有摘要逻辑。

这样做的原因：

- `.jsonl` 属于底层存储，格式更容易变化
- `sessions_history(...)` 已经承载了现有摘要、去重、终态判断语义
- 这次重构只改监听机制，不同时改动消息解释层

### 2. 保留短生命周期 worker，不引入长期常驻进程

worker 仍然是可重入、可恢复的短进程：

1. 通过 `ensure-live-watch.py` 获得启动或恢复决策
2. 抢占 lease 并读取 watch state
3. 定位目标 session 文件
4. 等待文件变化
5. 变化后去抖，再拉取 `sessions_history(...)`
6. 回推新增摘要并更新 watch state
7. 空闲一段时间后退出

这样可以继续满足：

- 进程被杀后仍可恢复
- 页面刷新 / main 重启后仍可接管
- 不需要宿主环境额外维护常驻守护进程

### 3. 引入“文件变化驱动 + 低频 fallback”

第一版不依赖额外第三方库，使用一个轻量的文件状态探测器：

- `mtime`
- `size`
- `inode`
- `exists`

worker 循环改为：

1. 采样当前 session 文件状态
2. 如果与上次记录不同，则记为一次文件事件
3. 对文件事件进行短暂去抖
4. 去抖后调用 `sessions_history(...)`
5. 若文件不存在或无法稳定定位，则回退到低频 `sessions_history(...)` 轮询

这个方案本质上是“文件事件优先，时间轮询兜底”。

## 组件设计

### `runtime/session_file_watch.py`（新增）

职责：

- 根据 `targetSessionKey` 推导目标 agent
- 读取 `~/.openclaw/agents/<agent>/sessions/sessions.json`
- 解析 `sessionFile` 或 `sessionId`
- 返回实际监听的 `.jsonl` 路径
- 提供文件状态采样与变更判断 helper

建议接口：

- `resolve_session_file_path(session_key: str, root: Path | None = None) -> Path | None`
- `sample_session_file(path: Path | None) -> SessionFileSample`
- `detect_session_file_change(previous, current) -> bool`
- `should_relocate_session_file(previous_path, current_path) -> bool`

建议数据结构：

- `SessionFileSample`
  - `path`
  - `exists`
  - `mtime`
  - `size`
  - `inode`
  - `sampled_at`

### `runtime/live_watch.py`

扩展 `WatchState`，新增最小必要状态：

- `session_file_path`
- `session_file_mtime`
- `session_file_size`
- `session_file_inode`
- `last_session_event_at`
- `last_history_pull_at`

作用：

- worker 重启后不用重新从空状态等待
- 文件 rotate / reset / 替换时可识别
- 避免同一轮写入反复触发 history 拉取

### `runtime/live-webgen-progress.py`

这是主改动点。

当前行为：

- 每轮 `sleep(interval)` 后直接拉 `sessions_history(...)`

改为：

1. 启动时解析 `targetSessionKey -> session_file_path`
2. 若可定位文件，则进入“采样文件变化”循环
3. 仅在检测到变化时触发 `sessions_history(...)`
4. 若无法定位文件或定位失败次数过多，则退回低频轮询
5. 保留终态补发、rebroadcast、context nudge、lease heartbeat

### `runtime/ensure-live-watch.py`

主状态机不需要重写，只做两类补充：

- 启动 invocation 时允许向 worker 传递新的去抖 / fallback 参数
- `resume` 场景下不重置 session 文件相关状态

## Worker 状态机

### 启动

1. 读取 watch state
2. claim lease
3. 定位目标 session 文件
4. 把定位结果写回 watch state

### 正常循环

1. 采样当前文件状态
2. 若文件有变化：
   - 记录 `last_session_event_at`
   - 等待去抖窗口，例如 `300-800ms`
   - 再次采样确认稳定
   - 调用 `sessions_history(...)`
3. 若无变化：
   - 不拉 history
   - 增加空闲计数
4. 若空闲到阈值：
   - worker 主动退出

### 终态

若 `sessions_history(...)` 判断任务已完成/阻塞：

- 先生成最终摘要
- 若投递成功，置 `final_delivered=true`
- 更新 `status / phase`
- 释放 worker 生命周期，让下一次 `ensure` 返回 `idle`

## 异常与边界

### 1. `sessions.json` 没有 `sessionFile`

处理：

- 尝试退回 `sessionId -> <session-id>.jsonl`
- 若仍失败，进入低频 history fallback

### 2. session 文件暂时不存在

可能原因：

- session 尚未真正落盘
- 文件被 reset / rotate
- 元数据与文件状态短暂不同步

处理：

- 不立刻报错
- 记录一次缺失状态
- 低频重试定位
- 同时保留低频 `sessions_history(...)` 兜底

### 3. 文件变了，但 history 没新增

原因可能是：

- 写入的是非消息元数据
- 写入后被压缩、折叠或重排

处理：

- 更新文件采样状态
- 不播报
- 不推进 `lastBroadcastSeq`

### 4. 文件被 rotate / reset

判定信号：

- `inode` 变化
- `size` 明显回退
- 路径变更

处理：

- 重新定位 session 文件
- 更新文件状态缓存
- **不**回退 `lastSeenSeq`

### 5. worker 在文件等待期间崩溃

影响可接受，因为：

- state 已落盘
- lease 过期后 `ensure-live-watch.py` 会返回 `resume`
- 新 worker 可以继续接管

## 参数建议

新增 worker 参数建议：

- `--debounce-ms`：默认 `500`
- `--idle-exit-seconds` 或继续沿用 `idle_exit_polls`
- `--file-probe-interval-ms`：默认 `800-1500`
- `--fallback-history-interval-seconds`：默认 `15-30`
- `--session-file`：可选，若已预解析则直接传入

第一版也可以只加：

- `--debounce-ms`
- `--fallback-history-interval-seconds`

其余使用现有 `interval` 复用。

## 测试策略

需要覆盖：

- `targetSessionKey -> session_file_path` 解析
- `sessionFile` / `sessionId` 两种元数据路径
- 文件变化判定：mtime、size、inode、exists
- 去抖后只触发一次 history 拉取
- 文件变化但无 history 新消息时不重播
- 文件 reset / rotate 后不丢 `lastSeenSeq`
- 无法定位文件时回退到低频 polling
- 终态补发逻辑不受影响

## 成功标准

- worker 不再每轮都调用 `sessions_history(...)`
- session 文件未变化时，history 调用次数显著下降
- session 文件变化后，新增步骤能更快被播报
- worker 挂掉后，仍能通过 `ensure-live-watch.py` 恢复
- `final_delivered`、`rebroadcast`、`manual_pull` 语义保持不变

