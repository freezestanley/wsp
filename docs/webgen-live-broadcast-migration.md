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

本次已经把这个缺口补上:

1. **AGENTS.md 已强化**:建站委托时必须先读 `skills/delegated-live-broadcasting/SKILL.md`
2. **AGENTS.md 已写死续航要求**:首条播报后,同回合必须安排 `cron wake`
3. **AGENTS.md 已明确停止条件**:只有交付 / 明确阻塞 / 取消时才能停播
4. **恢复 runtime 辅助脚本**:方便本地观察、调试、对照 webgen session 增量输出

> 额外修正：续播不再使用 `sessionTarget:"main" + systemEvent`，而是默认改成 `sessionTarget:"current" + agentTurn`，保证后续直播回到当前用户对话，而不是掉进独立 cron session。

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
  - 负责在 20–40 秒后继续触发当前对话绑定的 agent turn
  - 形成跨回合的直播链

### 三、调试层

- `runtime/live-webgen-progress.py`
  - 面向人类调试的直播摘要器
  - 可自动把 `toolResult` / `assistant` 进展转成中文摘要
- `runtime/watch-session-history.py`
  - 面向底层排查的原始 history 观察器

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
   - 默认使用 `sessionTarget:"current"`
   - `payload.kind:"agentTurn"`
   - `delivery.mode:"announce"`

### wake 回合

1. 读取目标 session 的 `sessions_history(..., includeTools=true)`
2. 只提炼上次之后的新增动作
3. 翻译成 1–3 条中文直播
4. 判断状态:
   - 已交付 → 停播并汇总
   - 明确阻塞 → 停播并向用户转达
   - 未结束 → 再安排下一次 wake

---

## 建议的 wake 文本模板

建议用 **current-session 的 `agentTurn` prompt** 直接把恢复直播所需的最小上下文带上:

```text
【继续直播任务】检查 webgen session=agent:webgen:proj-<slug> 的新增进展;
若已有新的 tool/assistant 步骤则向当前用户播报 1–3 条中文摘要;
若未交付且未阻塞,继续安排下一次 20–40 秒后的 current-session wake。
```

如果你想减少重复计算,还可以把上次已播的 seq 一并写进提醒文本:

```text
【继续直播任务】session=agent:webgen:proj-<slug>; last_broadcast_seq=1234。
只播报 seq>1234 的新增关键步骤; 未完成则继续安排下一次 current-session wake。
```

---

## 为什么参考目录里的方案有效

参考目录 `/Users/za-stanlexu/Desktop/openclaw/.openclaw` 的关键价值不在于“有个本地 watcher 脚本”,而在于两件事:

1. **把直播抽成单独 skill**
   - `skills/delegated-live-broadcasting/SKILL.md`
   - 明确写了“首条播报后必须建立续航机制”

2. **把 main 的直播职责写成硬规则**
   - 不是“建议轮询”
   - 而是“没建 wake 链就不算直播已启动”

3. **把续播绑定到当前会话,而不是 main cron session**
   - `sessionTarget:"main" + systemEvent` 会进入独立 cron session
   - `sessionTarget:"current" + agentTurn` 才会继续回到当前对话

本次迁移保留的就是这两个核心。

---

## 本次落地的文件

### 已修改

- `AGENTS.md`
  - 增加“先读 delegated-live-broadcasting skill”
  - 增加“首条播报后同回合必须建 wake 链”
  - 增加“未交付/未阻塞就继续安排 wake”
  - 改为 current-session wake prompt 模板

### 已恢复

- `runtime/live-webgen-progress.py`
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

适用于目标实例只需要 agent 自己会直播,不需要本地调试脚本。

1. 合并 `AGENTS.md` 的 webgen 委托直播段落
2. 复制 `skills/delegated-live-broadcasting/SKILL.md`
3. 确认目标实例允许跨 agent / 跨 session 调度
4. 冒烟测试:让 main 收一个“做个登录页”类请求,确认它会:
   - 委托
   - 立即播报
   - 后续继续播报而不是只播一次
   - 且续播发生在**当前用户对话**,不是独立 cron session

### 方案 B：规则 + 调试工具一起迁（推荐）

1. 完成方案 A
2. 复制 `runtime/live-webgen-progress.py`
3. 复制 `runtime/watch-session-history.py`
4. 用下面命令做对照调试:

```bash
python3 runtime/live-webgen-progress.py agent:webgen:proj-<slug> --interval 5
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

如果只做到“委托 + 第一条消息”,或 wake 后只在独立 cron session 里自转、没有回到当前用户对话,仍然算未迁移完成。

---

## 额外建议

后面如果你想把这套机制再收敛一层,我建议下一步做的是:

1. 再补一个**专门给 wake 回合使用的固定提醒模板**
2. 约定一个更稳定的 `last_broadcast_seq` 写法
3. 如果后续发现 agent 偶尔还会忘记继续 wake,再把这套逻辑沉淀成更强的 skill / workshop proposal

这样就不只是“有说明”,而是更接近“半结构化协议”。
