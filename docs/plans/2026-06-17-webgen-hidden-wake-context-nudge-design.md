# WebGen Hidden Wake + Silent Context Nudge Design

**Date:** 2026-06-17

## Goal

让 `main -> webgen` 的跨回合轮询与 context 自保机制对用户尽量无感：

- 用户看不到 `[cron:...]`
- 用户看不到 `Current time ...`
- 用户看不到 `Reference UTC ...`
- 用户看不到“请检查 context / 请 compact”这类控制面提醒
- 用户只在**真的有新增进展**时才收到自然语言摘要

同时保持以下不变：

- `slug -> sessionKey` 绑定不变
- deterministic resume 不变
- single active project session 语义不变
- 不引入 session rollover / 临时换绑

---

## Problem

当前 workspace 层已经把 wake 正文压缩到最小，并尽量过滤内部调度文本，但仍有两个缺口：

1. wake 事件本身仍可能被 runtime 渲染成可见系统文本
2. 轮询过程中若要提醒 `webgen` 做 context 自检 / `compact`，目前没有“用户无感”的控制面通道

因此，要实现“用户只看真实进展，不看轮询痕迹”，必须同时改：

- `workspace`：定义 silent nudge 与 watch 状态协议
- `runtime`：支持 hidden wake / hidden control delivery / system wrapper 抑制

---

## Design Principles

1. **进展可见，调度不可见**
   - 用户只能看到业务进展摘要
   - 调度、唤醒、时间戳、context 提醒全部隐藏

2. **只在需要时输出**
   - 没有新增进展时，wake 回合对用户零输出
   - 只有真正新增的实现 / 验证 / 阻塞信息才可见

3. **context 干预要幂等**
   - 不允许每次轮询都提醒一次
   - 必须有 band 升级触发与冷却时间

4. **不改变项目恢复语义**
   - 不因 context 高而切换到新 session
   - 不因 `compact` 改变既有 resume 路由

---

## Target Architecture

### 1. Hidden Wake

`cron wake` 不再向当前对话写入可见文本，而是只注入结构化 payload：

```json
{
  "kind": "internalWake",
  "watchId": "watch-webgen-admin-dashboard",
  "data": {
    "targetSessionKey": "agent:webgen:proj-admin-dashboard",
    "lastSeenSeq": 1234,
    "phase": "implementing",
    "lastContextBand": "warn"
  }
}
```

hidden wake 触发后：

1. runtime 恢复当前对话上下文
2. 执行一次内部 wake 回合
3. 内部调用 `sessions_history(...)`
4. 如有需要，内部调用 `sessions_send(...)` 发 silent nudge
5. 若无用户应见的新摘要，则该回合不生成任何可见 assistant 消息

### 2. Silent Context Nudge

当轮询层检测到 `webgen` 当前 session context 进入高风险带时，`main` 不对用户播报，而是发一条隐藏控制消息到目标 `sessionKey`。

控制消息语义：

- 先检查当前 context 使用率
- 若超过阈值则先执行 `compact`
- `compact` 完后继续当前任务
- 不改 `slug -> sessionKey`
- 不新建 session
- 不切换项目 session

### 3. Visible-on-Progress Rule

wake 回合只有以下情况才允许输出用户可见消息：

- 有新的构建 / 运行 / 验证进展
- `webgen` 明确交付
- `webgen` 明确阻塞且需要用户输入
- `webgen` 发出用户必须回答的澄清问题

其余全部静默：

- 无新增步骤
- 仅执行内部轮询
- 仅发送 silent nudge
- 仅更新时间 / cursor / watch state

---

## Context Band Policy

建议策略：

- `<80%`：`ok`
- `>=80%`：`warn`
- `>=85%`：`compact`
- `>=92%`：`force-compact`

含义：

- `warn`
  - 提醒 session 自检 transcript 增长风险
- `compact`
  - 应优先执行 `compact` 再继续
- `force-compact`
  - 在继续执行前必须先压缩，否则大输出工具调用应暂缓

说明：

- 上述 band 是**控制策略**，不是用户可见状态
- band 变化只用于内部决策与节流

---

## Runtime Changes Required

### 1. Hidden wake delivery

新增或等价支持：

- `delivery.mode: "hidden"`
- 或 `systemEvent.visibility: "internal"`

要求：

- hidden wake 不生成用户可见气泡
- hidden wake 仍能恢复当前会话并运行一轮 agent turn

### 2. System wrapper suppression

对 hidden wake 禁止渲染：

- `[cron:...]`
- `Current time: ...`
- `Reference UTC: ...`

这一步是“彻底用户无感”的关键。只改 workspace 做不到。

### 3. Hidden inter-session control delivery

`sessions_send(...)` 需要支持控制面消息不进入用户可见 transcript，至少对 `main -> webgen` 的这类内部治理消息提供 hidden/internal 模式。

否则会出现：

- 虽然用户看不到 wake
- 但 `webgen` transcript 里会被持续堆入重复控制文本

### 4. Silent completion path

hidden wake 执行完后：

- 若无新增可见摘要，回合静默结束
- 若有新增摘要，再由 agent 生成一条正常 assistant 消息

---

## Workspace Changes Required

### 1. Watch state 扩展

建议在 `runtime/live_watch.py` 的 `WatchState` 中新增：

- `last_context_band`
- `last_context_nudge_at`
- `last_context_nudge_seq`
- `awaiting_context_ack`
- `last_silent_wake_at`

用途：

- 记录最近一次 context 风险带
- 防止重复提醒
- 追踪 silent nudge 是否已被处理

### 2. Context nudge 决策器

建议新增 helper，例如：

- `evaluate_context_band(...)`
- `should_send_context_nudge(...)`
- `build_context_nudge_message(...)`

核心规则：

- 只有 band 升级时触发
- 或超过冷却时间且仍未看到 ack 时重发
- 默认冷却 120–300 秒

### 3. Hidden-only control copy

控制消息模板必须短、固定、可机器识别。例如：

```text
[internal-control] Check current context usage. If above compact threshold, compact now and then continue the same task in the same session. Do not change slug/session binding.
```

要求：

- 不混入用户原话
- 不作为用户进展播报
- 不写入可见 wake 文本

### 4. Fallback behavior

若 runtime 还不支持 hidden wake：

- 继续使用当前最小 fallback：`当前进度`
- 但 silent context nudge 仍优先尝试 hidden/internal 交付

---

## State Machine

### Wake cycle

1. wake 触发
2. 读取 watch state
3. 拉 `sessions_history(...)`
4. 提炼新增进展
5. 检查 context band
6. 如需则发送 silent nudge
7. 更新 watch state
8. 若有新增可见进展则输出；否则静默
9. 任务未结束则继续安排下一次 hidden wake

### Context nudge sub-state

- `idle`
- `warned`
- `awaiting-compact`
- `cooled-down`

转换：

- `ok -> warn`：可发一次 silent warn
- `warn -> compact`：发 compact nudge
- `compact -> force-compact`：发强提醒，但仍 hidden
- 观察到 ack / compact 完成后回到 `cooled-down`

---

## Acknowledgement Signals

判断 `webgen` 已处理 nudge 的方式建议从松到严：

1. assistant 文本出现 `compact` / `compressed` / `继续任务`
2. tool / runtime 事件里出现 compact 执行痕迹
3. 后续 context band 下降

只要满足任一条件，即可清理：

- `awaiting_context_ack = false`

---

## Risks

1. **runtime 不支持 hidden wake**
   - 结果：`[cron:...]` 与时间包装仍会泄露

2. **重复 nudge 导致反向增大 transcript**
   - 结果：越提醒越占 context
   - 对策：band 升级触发 + 冷却时间 + ack 检测

3. **没有可靠 context usage 指标**
   - 结果：band 只能靠近似估算
   - 对策：先支持 policy helper，后接 runtime 真指标

4. **`compact` 不是原子事件**
   - 结果：可能在压缩和继续之间再次被 wake 打断
   - 对策：在 watch state 中保留 `awaiting_context_ack`

---

## Non-Goals

- 不实现 session rollover
- 不改变现有 deterministic resume 规则
- 不让用户参与 context 管理
- 不把 context 数值细节作为用户可见进度

---

## Acceptance Criteria

满足以下条件才算达标：

1. 用户在轮询过程中看不到：
   - `[cron:...]`
   - `Current time ...`
   - `Reference UTC ...`
   - context 提醒文本

2. 用户只在有真实新增进展时收到消息

3. `webgen` context 超阈值时会被内部静默提醒并继续任务

4. deterministic resume 与 `sessionKey` 绑定不受影响

5. 没有新增进展时，对话保持静默

---

## Recommended Rollout

### Phase 1: Workspace policy

- 新增 context band helper
- 新增 silent nudge 决策逻辑
- 扩展 watch state
- 更新 AGENTS / skill / docs

### Phase 2: Runtime hidden wake

- 支持 hidden wake payload
- 抑制 `[cron:...]` 与时间包装
- 支持 silent completion

### Phase 3: Runtime hidden control delivery

- 支持 hidden `sessions_send`
- 将 context nudge 彻底从用户 transcript 中剥离

### Phase 4: End-to-end verification

- 验证“无新增时零输出”
- 验证“超阈值时 silent compact”
- 验证 resume / wake / compact 能共存
