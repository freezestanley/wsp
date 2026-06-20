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
2. **AGENTS.md 已写死续航要求**:首条播报后,同回合必须建立可恢复的 `watch state + worker` 续航链
3. **AGENTS.md 已明确停止条件**:只有交付 / 明确阻塞 / 取消时才能停播
4. **恢复 runtime 辅助脚本**:方便本地观察、调试、对照 webgen session 增量输出
5. **弃用可见 announce wake**:不再把自然语言 cron 提示词直接注入当前对话

> 额外修正：旧方案把 `sessionTarget:"current" + agentTurn + delivery.mode:"announce"` 当作回到当前对话的办法，但这会把 `[cron:...]` 和整段内部调度文本泄露到用户对话。新的目标协议改成 **hidden/internal wake + 结构化状态 + wake 回合主动拉取 `sessions_history`**。在当前“外层 runtime 不可改”的约束下,workspace 内 fallback 的用户可见文本只显示 `当前进度`。

> 迁移补充：`hidden/internal wake` 现在应被视为**增强能力**,不是可移植前提。对无法修改 runtime 的其他 OpenClaw 实例,workspace 侧默认走 **`originSessionKey + rebroadcast`**：记录原会话 `sessionKey`，由 watcher 在拿到新增摘要后主动 `sessions_send` 回该会话。只有在 hidden wake 和 rebroadcast 都不可用时，才退化到 `manual_pull`。

> 实现补充：`rebroadcast` 不是无条件可用。当前 watcher 会先读取 gateway 配置判断 HTTP `/tools/invoke` 是否显式开放了 `sessions_send`；若 `gateway.tools.allow` 没有放开它，就会按默认安全策略判定为不可用并继续降级。`originSessionKey` 则支持通过显式参数或环境变量 `OPENCLAW_ORIGIN_SESSION_KEY` 注入。

> 当前 workspace 还额外接入了一条 **silent context nudge 决策路径**：当 watcher 能拿到 context usage ratio 时,可在 wake 周期里内部计算 `ok / warn / compact / force-compact` band,并规划 silent nudge;当拿不到 ratio 时,watcher 行为保持不变。这条路径目前只影响 watcher 内部状态与控制决策,**不会**单独产出用户可见进度消息。

## 已确认的两条错误路径

- 错误路径一：`sessionTarget:"main"` + `payload.kind:"systemEvent"` 把 wake 建进 dashboard/background session
  - 结果不是“回到当前用户对话继续播报”，而是把后续轮询跑进独立的 cron/background session。
  - 用户侧体感就是 webgen 明明在继续干活，但当前对话没有自动播报，只能手动追问。
  - 现在规则层必须把这条路径视为硬错误，不允许拿它充当当前对话续播方案。
- 错误路径二：wake 回合命中 `Cron tool is restricted to the current cron job.` 后又错误地再次 `cron.add`
  - 这说明当前回合处于 cron 受限态，只能操作当前 job，不能继续新建新的 cron job。
  - 正确策略是优先复用当前 job；若 runtime 支持则 `cron.update` 当前 job；若当前回合确实做不到，则在下一次普通用户回合第一时间补链。
  - 不能口头说“之后再继续监听”然后结束，因为那不等于直播链已经恢复。

---

## 当前推荐架构

### 一、规则层

- `AGENTS.md`
  - 负责“什么时候必须委托 webgen”
  - 负责“什么时候必须开直播”
  - 负责“首条播报之后必须建立 wake 链”
- `skills/delegated-live-broadcasting/SKILL.md`
  - 负责直播流程的标准做法
  - 强调默认优先使用 `prepare / ensure / short worker` 续航,不能只口头承诺轮询

### 二、执行层

- `sessions_send(...)`
  - 负责把原始用户需求发给 `webgen`
  - 在 `rebroadcast` 模式下负责把新增摘要主动回推到 `originSessionKey`
- `sessions_history(...)`
  - 负责读取被委托 session 的真实新增动作
- `runtime/prepare-webgen-live-watch.py`
  - 普通用户回合的高层桥接入口
  - 先做 deterministic resume 预检
  - 再把最终 `targetSessionKey` 交给 `runtime/ensure-live-watch.py`
- `runtime/ensure-live-watch.py`
  - watch 生命周期的唯一决策入口
  - 返回 `start / resume / active / idle`
  - 调用方只需执行返回的 `invocation`
- `runtime/live_watch.py`
  - 负责本地 watch 状态持久化
  - 负责增量摘要、内部调度文本过滤,以及 silent context nudge 相关状态
  - 当前主路径依赖 `lease` 与 `final_delivered`，而不是依赖下一条 cron 能否创建成功
- `cron.add(...)`
  - 不再是主路径前提
  - 只保留给旧 wake/hidden wake 兼容场景
- `runtime/live_wake_token.py`
  - 负责生成/解析最小泄露 wake token

### 三、调试层

- `runtime/live-webgen-progress.py`
  - 面向人类调试的直播摘要器
  - 可自动把 `toolResult` / `assistant` 进展转成中文摘要
  - 支持 `hidden_wake / rebroadcast / manual_pull` 三档投递策略
  - 会自动读取 gateway 配置推断 `sessions_send` 能否经 HTTP 使用
  - 支持从 `OPENCLAW_ORIGIN_SESSION_KEY` 读取来源会话
  - 若外部未显式提供 `watch_id / state_file`，会按目标 session 自动生成稳定的 watch 配置
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
5. 记录 `originSessionKey`
6. 选择能力档位
   - 优先 `hidden_wake`
   - 无 hidden wake 但有 `sessions_send(sessionKey=...)` → `rebroadcast`
   - 两者都没有 → `manual_pull`
7. 普通用户回合优先用 `prepare-webgen-live-watch.py` 或 `ensure-live-watch.py` 启动/接管 watcher
8. 若 worker 周期能取得 context usage ratio,可内部追加 silent context nudge 决策;若没有该 ratio,则不改变既有直播流程

### worker 周期

1. 读取目标 session 的 `sessions_history(..., includeTools=true)`
2. 若本轮有 context usage ratio,先内部计算 compaction band,并决定是否规划 silent context nudge；若没有,跳过该步骤
3. 只提炼上次之后的新增动作
4. 翻译成 1–3 条中文直播；必要时可合并一条关键委托/控制面同步事件
5. 若当前档位是 `rebroadcast`,把这些摘要显式 `sessions_send(sessionKey=originSessionKey, message=摘要)` 回原会话
6. 判断状态:
   - 已交付 → 停播并汇总
   - 明确阻塞 → 停播并向用户转达
   - 长时间无新增 → 按阈值发一条低噪音进度心跳（默认至少间隔 60 秒）
   - 未结束 → 在短窗口内继续轮询，空闲则主动退出
7. 旧 cron 兼容路径若遇到 `Cron tool is restricted to the current cron job.`:
   - 不要再次 `cron.add`
   - 把它视为旧路径受限
   - 下一次普通用户回合切回 `prepare / ensure` 主路径

注意:

- silent context nudge 本身不是“可播报进度”; 即使本轮只发生了内部 nudge,也不应因此输出用户可见消息
- 当前 workspace 仍未完成真正的 hidden `sessions_send` 投递,也还不能单靠 workspace 消掉 `[cron:...]` / `Current time` / `Reference UTC` 系统包裹
- `rebroadcast` 的目标不是“让 cron 理解当前会话”,而是“让用户当前对话收到摘要”;因此它是可迁移基础能力,`hidden_wake` 才是增强体验
- 当前推荐主路径已经改成 `prepare / ensure / short worker`；`cron / rechain` 仅保留兼容职责

### 普通用户回合补链

若上一轮 wake 已把 watch 标成 `needs_rechain`：

1. **优先走统一入口**：

```bash
python3 runtime/ensure-live-watch.py --session-key agent:webgen:proj-<slug> --json
```

2. 返回约定：
   - `status: "start"`：这是首次拉起 watcher，直接执行返回的 `invocation`
   - `status: "resume"`：当前 watch 处于待补链态，直接执行返回的 `invocation`
   - `status: "active"`：当前 watch 已活跃，不要重复拉起第二条 watcher
   - `status: "idle"`：当前 watch 已终态或暂无恢复动作
3. `start / resume` 的调用方都**不要**自己手工拼 `--state-file / --watch-id / --delivery-strategy`；统一使用返回的 `command + env`

### 普通用户回合统一桥接入口

如果当前调用侧还没先拿到最终 `targetSessionKey`，推荐直接用：

```bash
python3 runtime/prepare-webgen-live-watch.py --message "<用户原话>" --slug <new-slug> --json
```

它会在普通用户回合里统一做两步：

1. 先跑现有 `runtime/webgen_resume_resolver.py` 的确定性复用判断
2. 再把最终 `targetSessionKey` 交给 `runtime/ensure-live-watch.py`

返回约定：

- `status: "ready"`：已得到最终 `targetSessionKey`，并返回 `watch`
- `status: "unresolved"`：当前既没有命中确定性旧项目，也没有提供新项目 `slug`

这个桥接入口不会改变现有项目检索语义，只是把“resume 预检 + ensure-watch”合并成一次普通用户回合可直接调用的控制面动作。

低层 helper 仍然保留，适合调用方只想处理“待补链恢复”这一条窄路径：

1. 读取对应 `state_file + watch_id`
2. 调 `load_rechain_invocation(...)`
3. 若返回非空：
   - 直接使用它给出的 `command + env` 重新启动 watcher
   - 不要重新手工拼 `--state-file / --watch-id / --delivery-strategy`
4. 若返回空：
   - 说明当前 watch 不处于待补链态，不要重复补链

如果调用方不想自己 import Python helper，也可以直接用薄入口脚本：

```bash
python3 runtime/rechain-watch.py --state-file /tmp/openclaw-live-watch/<watch-id>.json --watch-id <watch-id> --ok-if-idle --dry-run --json
```

去掉 `--dry-run` 后会直接执行恢复命令。

如果连 `--ok-if-idle` 也不想每次手写，可以直接用包装脚本：

```bash
python3 runtime/rechain-watch-once.py --state-file /tmp/openclaw-live-watch/<watch-id>.json --watch-id <watch-id> --dry-run --json
```

它会自动补上 `--ok-if-idle`。

返回约定：

- `status: "ready"`：当前确实存在待补链 watcher，并返回 `invocation`
- `status: "idle"`：当前没有待补链 watcher；若使用了 `--ok-if-idle`，脚本返回码仍为 `0`

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

## watcher bootstrap 约定

为减少 main/调用方手工拼接参数,当前 watcher 已支持以下默认约定:

- 未显式传 `watch_id` 时,按目标 session 生成稳定 ID
  - 例：`agent:webgen:proj-demo` → `watch-agent-webgen-proj-demo`
- 未显式传 `state_file` 时,默认写入:
  - `/tmp/openclaw-live-watch/<watch_id>.json`
- 未显式传 `originSessionKey` 参数时,可从环境变量读取:
  - `OPENCLAW_ORIGIN_SESSION_KEY`

这意味着调用方最少只要提供:

- 目标 `sessionKey`
- 原会话 `originSessionKey`（参数或环境变量二选一）

剩余 watch 配置可由脚本自行补齐。

如果调用方是在 Python 侧直接组装 watcher 启动命令，推荐顺序是：

1. `build_watch_bootstrap(...)`
   - 生成稳定的 `watch_id / state_file / delivery_strategy`
2. `build_watch_invocation(...)`
   - 生成 `command + env`
   - 默认把 `originSessionKey` 放进 `OPENCLAW_ORIGIN_SESSION_KEY`
   - 避免调用方自己重复拼 `--state-file`、`--watch-id`、`--delivery-strategy`

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
