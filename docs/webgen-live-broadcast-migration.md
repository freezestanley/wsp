# WebGen 委托直播落地与迁移方案

## 这次修了什么

当前 workspace 里,建站委托规则已经要求“要直播”,但之前缺的是**真正能跨回合持续直播的续航机制**:

- 有首条播报要求
- 有 `sessions_history` 轮询要求
- **但没有强制要求在同一回合里建立 wake 链**

结果就是 main 很容易出现这种行为:

1. 把任务委托给 `webgen`
2. 对用户说“已委托,开始直播”
3. 当前回合结束
4. 后面没有任何 wake / 持续检查

这就是“看起来有直播规则,实际上没有直播链路”的根因。

本次已经把这个缺口补上,并补充了一条新的约束:

1. **AGENTS.md 已强化**:建站委托时必须先读 `skills/delegated-live-broadcasting/SKILL.md`
2. **AGENTS.md 已写死续航要求**:首条播报后,同回合必须安排 `cron wake`
3. **AGENTS.md 已明确停止条件**:只有交付 / 明确阻塞 / 取消时才能停播
4. **恢复 runtime 辅助脚本**:方便本地观察、调试、对照 webgen session 增量输出
5. **弃用可见 announce wake**:不再把自然语言 cron 提示词直接注入当前对话

> 额外修正：旧方案把 `sessionTarget:"current" + agentTurn + delivery.mode:"announce"` 当作回到当前对话的办法，但这会把 `[cron:...]` 和整段内部调度文本泄露到用户对话。新的目标协议改成 **hidden/internal wake + 结构化状态 + wake 回合主动拉取 `sessions_history`**。在当前“外层 runtime 不可改”的约束下,workspace 内 fallback 的用户可见文本只显示 `当前进度`。

> 当前 workspace 还额外接入了一条 **silent context nudge 决策路径**：当 watcher 能拿到 context usage ratio 时,可在 wake 周期里内部计算 `ok / warn / compact / force-compact` band,并规划 silent nudge;当拿不到 ratio 时,watcher 行为保持不变。这条路径目前只影响 watcher 内部状态与控制决策,**不会**单独产出用户可见进度消息。

---

## 当前推荐架构

### 一、规则层

- `AGENTS.md`
  - 负责“什么时候必须委托 webgen”
  - 负责“什么时候必须开直播”
  - 负责“首条播报之后必须建立 wake 链”
- `skills/delegated-live-broadcasting/SKILL.md`
  - 负责直播流程的标准做法
  - 强调默认优先使用 `cron wake` 续航,不能只口头承诺轮询

### 二、执行层

- `sessions_send(...)`
  - 负责把原始用户需求发给 `webgen`
- `sessions_history(...)`
  - 负责读取被委托 session 的真实新增动作
- `cron.add(...)`
  - 负责在 20–40 秒后继续触发当前对话绑定的 hidden/internal wake
  - 形成跨回合的直播链
- `runtime/live_watch.py`
  - 负责本地 watch 状态持久化
  - 负责增量摘要、内部调度文本过滤,以及 silent context nudge 相关状态
- `runtime/live_wake_token.py`
  - 负责生成/解析最小泄露 wake token

### 三、调试层

- `runtime/live-webgen-progress.py`
  - 面向人类调试的直播摘要器
  - 可自动把 `toolResult` / `assistant` 进展转成中文摘要
  - 若提供 context usage ratio,可额外做 silent context nudge 决策;若不提供,行为与原先一致
- `runtime/watch-session-history.py`
  - 面向底层排查的原始 history 观察器

---

## Context Stopgap 边界

这层 stopgap 只负责**减少 transcript 增长**,不负责改变项目恢复语义。明确边界如下:

- 不改 `slug -> sessionKey` 绑定
- 不改 deterministic resume 流程
- 不改 single active project session 语义
- 不引入 session rollover / 临时换绑来“绕过”高上下文

workspace 层当前建议的阈值策略:

- `<120k`：`ok`
- `>=120k`：`warn`
- `>=140k`：`compact`
- `>=160k`：`hard-stop`

含义:

- 到 `warn` 以后,Discovery 就不该再继续整段 dump 文件内容
- 到 `compact` 以前,上游 runtime 应该已经触发压缩
- 到 `hard-stop` 时,上游 runtime 应拒绝继续增长超长 transcript,但仍保持原有 project/session identity 不变

补充说明:

- 现在 watcher 侧已经能在拿到 ratio 时内部算出 `warn / compact / force-compact`
- 但这只是“是否需要 silent nudge”的 stopgap 决策,不是 runtime 已经完成 hidden 压缩投递
- deterministic resume、`slug -> sessionKey` 绑定、当前项目 session identity 在这条 stopgap 下都不变

为配合这套 stopgap,Discovery 侧应优先:

- `rg -n` 定位所需字段
- `sed -n` 读取窄窗口
- 对 `DISCOVERY.md` 只抽取结构化字段,不要整份回显
- 对 `read` / `exec` 的超长结果只保留头尾片段

---

## main 侧标准流程

### 委托当回合

1. 识别到建站需求
2. 读取 `skills/delegated-live-broadcasting/SKILL.md`
3. 用独立 `sessionKey` 把用户原文委托给 `webgen`
4. 立即向用户发首条直播:
   - 已委托给哪个 session
   - 当前阶段(Discovery / 实现 / 验证)
5. 立刻创建一次 `cron wake`
   - 默认绑定当前对话
   - `payload.kind` 应为 runtime 支持的 hidden/internal wake 类型
   - payload 只放结构化字段,例如 `watchId / targetSessionKey / lastSeenSeq / phase`
6. 若 wake 周期能取得 context usage ratio,可内部追加 silent context nudge 决策;若没有该 ratio,则不改变既有直播流程

### wake 回合

1. 读取目标 session 的 `sessions_history(..., includeTools=true)`
2. 若本轮有 context usage ratio,先内部计算 compaction band,并决定是否规划 silent context nudge；若没有,跳过该步骤
3. 只提炼上次之后的新增动作
4. 翻译成 1–3 条中文直播；必要时可合并一条关键委托/控制面同步事件
5. 判断状态:
   - 已交付 → 停播并汇总
   - 明确阻塞 → 停播并向用户转达
   - 长时间无新增 → 按阈值发一条低噪音进度心跳（默认至少间隔 60 秒）
   - 未结束 → 再安排下一次 wake

注意:

- silent context nudge 本身不是“可播报进度”; 即使本轮只发生了内部 nudge,也不应因此输出用户可见消息
- 当前 workspace 仍未完成真正的 hidden `sessions_send` 投递,也还不能单靠 workspace 消掉 `[cron:...]` / `Current time` / `Reference UTC` 系统包裹

---

## 建议的 hidden wake 载荷

不要再把恢复直播所需的最小上下文写成自然语言 prompt。推荐直接传结构化 payload:

```json
{
  "kind": "internalWake",
  "watchId": "watch-webgen-<slug>",
  "data": {
    "targetSessionKey": "agent:webgen:proj-<slug>",
    "lastSeenSeq": 1234,
    "phase": "implementing"
  }
}
```

wake 回合拿到该 payload 后,再由 main 主动:

1. 调 `sessions_history(...)`
2. 对比 `lastSeenSeq`
3. 生成人话摘要
4. 决定是否继续安排下一次 wake

如果上游 runtime 还不能隐藏 wake 载荷,workspace 内允许的唯一 fallback 可见文本是:

```text
当前进度
```

要求:

1. 可见文本只能是这 4 个字,不能附带 token 与自然语言说明
2. 本地摘要层必须把这类文本识别为内部 wake 文本并过滤
3. 旧格式 `当前进度为：__oc_live__...` 仍保留兼容识别,但不再新生成
4. `REPLY_SKIP`、`inter-session routing echo`、`Nothing to broadcast`、`Staying silent` 这类内部跳过/回声文本也必须静默过滤

---

## 为什么参考目录里的方案有效

参考目录 `/Users/za-stanlexu/Desktop/openclaw/.openclaw` 的关键价值不在于“有个本地 watcher 脚本”,而在于两件事:

1. **把直播抽成单独 skill**
   - `skills/delegated-live-broadcasting/SKILL.md`
   - 明确写了“首条播报后必须建立续航机制”

2. **把 main 的直播职责写成硬规则**
   - 不是“建议轮询”
   - 而是“没建 wake 链就不算直播已启动”

3. **把续播绑定到当前会话,但不把内部 prompt 绑定进 transcript**
   - `sessionTarget:"main" + systemEvent` 会进入独立 cron session
   - `sessionTarget:"current" + agentTurn + announce` 会把内部 cron 文本编进当前对话
   - 只有 **hidden/internal wake** 才同时满足“继续回到当前对话”和“不泄露内部提示词”

本次迁移保留的就是这两个核心。

---

## 本次落地的文件

### 已修改

- `AGENTS.md`
  - 增加“先读 delegated-live-broadcasting skill”
  - 增加“首条播报后同回合必须建 wake 链”
  - 增加“未交付/未阻塞就继续安排 wake”
  - 改为 hidden wake 载荷模板

### 已恢复

- `runtime/live-webgen-progress.py`
- `runtime/live_watch.py`
- `runtime/watch-session-history.py`

### 新增

- `docs/webgen-live-broadcast-migration.md`（本文件）

---

## 迁移到别的 OpenClaw 实例时,最少拷哪些文件

### 必拷

1. `AGENTS.md` 中这段“建站委托 + 直播 + wake 链”规则
2. `skills/delegated-live-broadcasting/SKILL.md`

### 建议一起拷

3. `runtime/live-webgen-progress.py`
4. `runtime/watch-session-history.py`
5. 本文件 `docs/webgen-live-broadcast-migration.md`

---

## 迁移步骤

### 方案 A：只迁规则（最小集）

适用于目标实例只需要 agent 自己会直播,不需要本地调试脚本,且 runtime 已支持 hidden/internal wake。

1. 合并 `AGENTS.md` 的 webgen 委托直播段落
2. 复制 `skills/delegated-live-broadcasting/SKILL.md`
3. 确认目标实例允许跨 agent / 跨 session 调度
4. 冒烟测试:让 main 收一个“做个登录页”类请求,确认它会:
   - 委托
   - 立即播报
   - 后续继续播报而不是只播一次
   - 且续播发生在**当前用户对话**,不是独立 cron session
   - 且用户看不到 `[cron:...]` 或 `【继续监听任务】...`
   - 若外层 runtime 仍会回显 wake 文本,也只能看到 `当前进度`,不能看到自然语言调度说明

### 方案 B：规则 + 调试工具一起迁（推荐）

1. 完成方案 A
2. 复制 `runtime/live-webgen-progress.py`
3. 复制 `runtime/watch-session-history.py`
4. 用下面命令做对照调试:

```bash
python3 runtime/live-webgen-progress.py agent:webgen:proj-<slug> --interval 5 --state-file /tmp/live-watch-state.json --watch-id watch-webgen-<slug>
```

或看原始 history:

```bash
python3 runtime/watch-session-history.py agent:webgen:proj-<slug> --interval 5
```

---

## 验收标准

目标实例在收到建站需求后,必须满足以下全部条件:

1. **当回合就播第一条**
2. **第一条之后已经安排好下一次 wake**
3. **只播新增真实 history,不伪直播**
4. **任务没结束就会继续 wake**
5. **直到交付/阻塞才停播**
6. **用户对话里不出现内部 cron / wake 提示词**
7. **若外层 runtime 不可改,最多只出现“当前进度”,不会出现 token 与整段调度说明**

如果只做到“委托 + 第一条消息”,或 wake 后只在独立 cron session 里自转、没有回到当前用户对话,或用户仍能看到 `[cron:...]` / 自然语言 wake prompt,仍然算未迁移完成。

---

## 额外建议

后面如果你想把这套机制再收敛一层,我建议下一步做的是:

1. 再补一个**专门给 wake 回合使用的固定提醒模板**
2. 把 `sessions_history(afterSeq=...)` 做成正式增量接口
3. 如果后续发现 agent 偶尔还会忘记继续 wake,再把这套逻辑沉淀成更强的 skill / workshop proposal

这样就不只是“有说明”,而是更接近“半结构化协议”。

---

## 仍需上游 runtime 配合的点

当前 workspace 已经补了本地 watch 状态与摘要过滤,但下面三项仍需要 OpenClaw runtime 本身支持,否则无法彻底闭环:

1. **hidden/internal wake 投递**
   - wake 事件需要注入结构化状态,而不是把自然语言 prompt 回显到 transcript

2. **transcript 过滤**
   - internal wake 事件不能出现在用户可见对话中

3. **hidden `sessions_send` 控制投递**
   - silent context nudge 需要真正的内部控制通道,而不是用户可见消息

4. **增量 history**
   - `sessions_history` 最好支持 `afterSeq` 或 cursor
   - 否则只能在本地靠 `lastSeenSeq + limit` 尽量规避重播,仍存在窗口过小导致漏播的风险

在这三项完成前,workspace 当前方案的最好效果是:

- 把泄露从“大段自然语言 cron 指令”收敛成“当前进度”
- 把真实播报完全交给本地摘要层二次生成
- 在有 context usage ratio 时,watcher 只做 silent context nudge 的内部决策与状态演进,不会单独对用户出声
