---
name: "delegated-live-broadcasting"
description: "委托建站后自动建立 wake 轮询链并持续直播新增进展"
---

# delegated-live-broadcasting

## 适用场景

- main 将网页/建站类任务委托给 `webgen` 或其他可见 session
- 用户明确要求“直播”“逐步播报”“实时同步进展”
- 任务不会在当前主回合内立刻结束，需要跨回合持续跟进

## 核心规则

1. **首条直播后必须建立续航机制**
   - 发送委托消息并向用户播报“已委托 + 当前阶段”后，不能直接结束而不安排下一次检查。
   - 必须在同一回合内建立以下二选一机制：
     - 短时挂起等待：适合当前回合持续运行的场景；或
     - `cron wake` 链：适合 webchat/普通对话中跨回合持续直播的场景。

2. **默认优先使用 wake 链，而不是口头承诺轮询**
   - 若直播需要跨回合持续进行，默认创建一次 `cron wake`，在 20–40 秒后唤醒当前 main session。
   - 之后每次 wake 回合都：
     1. 读取目标 session 的最新 `sessions_history`
     2. 对比上次已播报的位置，只提炼新增步骤
     3. 用 1–3 条中文人话播报关键新增动作
     4. 若任务未完成/未阻塞，继续创建下一次 wake
   - **wake 载荷必须是隐藏的结构化状态**,而不是会出现在对话框里的自然语言调度提示词。
   - 允许的最小字段: `watchId`、`targetSessionKey`、`lastSeenSeq`、`phase`。
   - 如果 runtime 尚未支持 hidden/internal wake,不要回退到 `delivery.mode:"announce"` 直投当前对话; 可见文本只允许显示 `当前进度` 这 4 个字。
   - 禁止使用 `sessionTarget:"main"` + `payload.kind:"systemEvent"` 来尝试回到当前用户对话继续直播。
   - 若 wake 回合命中 `Cron tool is restricted to the current cron job.`，不得再次 `cron.add` 新 job；优先续用当前 job，若支持则 `cron.update` 当前 job；若当前回合确实做不到，只能在下一次普通用户回合立刻补链，不能口头承诺后结束。

3. **允许静默 context nudge,但它不是用户进度播报**
   - 如果 watcher 当前能拿到 context usage ratio,可在 wake 回合内部计算 `ok / warn / compact / force-compact` band,并在 band 升级时规划一条 silent context nudge,提醒 webgen 先检查 context、必要时 `/compact` 后继续当前任务。
   - 如果拿不到 context usage ratio,watcher 行为保持原样,不要因为缺少该指标而改变现有直播逻辑。
   - silent context nudge 是内部控制面动作,**不能**单独形成用户可见的“当前进度”或其他直播文本;只有真实新增 history 才值得播报。
   - 当前 workspace 只实现了 watcher 内部决策/状态演进;真正的 hidden `sessions_send` 投递和 `[cron:...]` / `Current time` / `Reference UTC` 抑制仍依赖上游 runtime。

4. **绝不把“我会开始直播”当成已启动直播链路**
   - 只有在已经完成等待或 wake 安排后，才能视为“直播已启动”。
   - 如果只是发送委托并回复用户“我会直播”，但没有建立后续检查机制，这属于流程错误。

5. **直播停止条件**
   - 仅当被委托 session 明确满足以下任一条件时，才停止继续安排 wake：
     - 明确交付
     - 明确阻塞且需要用户决策
     - 任务被取消

6. **补救规则**
   - 如果用户指出“直播没起效”“你漏播了”，必须立即：
     1. 拉取目标 session history
     2. 补播最近关键步骤
     3. 明确说明漏播原因
   4. 立刻恢复 wake 链

7. **错误路径硬禁令**
   - 禁止使用 `sessionTarget:"main"` + `payload.kind:"systemEvent"` 来尝试回到当前用户对话继续直播。
   - 若 wake 回合命中 `Cron tool is restricted to the current cron job.`，这不是“继续新建 cron”的信号，而是“只能操作当前 cron job”的限制提示。

## 推荐执行模板

### 委托当回合
1. `sessions_send(sessionKey=..., message=完整任务包)`
2. 向用户发送首条：已委托 + 当前阶段
3. `cron.add` 创建一次 20–40 秒后的 wake，payload 为**隐藏的结构化 watch 状态**；如果做不到，就退化成短 token，而不是自然语言提示词
4. 结束当前回合

### wake 回合
1. `sessions_history(sessionKey=目标session, includeTools=true, limit=适中)`
2. 若当前有 context usage ratio，可先在内部计算 compaction band，并决定是否规划 silent context nudge；若没有 ratio，跳过这一步，其他行为不变
3. 读取并提炼自上次播报后的新增动作
4. 若有新增，则播报 1–3 条关键进展；若无新增，静默即可。仅 silent nudge 本身不能触发任何用户可见输出
5. 判断是否已交付/阻塞
6. 若未结束，则再次 `cron.add` 或 `cron.update` 安排下一次 wake
7. 若连续多次 wake 都无新增，且距离上次心跳已超过阈值，可补一条低噪音“当前进度为…”心跳确认；默认最小间隔 60 秒

## 播报约束

- 只播新增，不重复已播内容
- 可补充播报关键委托/控制面事件，但优先级低于真实执行新增
- 不贴大段原始日志
- 用简短中文翻译工具动作与结果
- 没有新增时静默，不发“暂无更新”
- 但首条“已委托 + 阶段”不可省略
- **内部 wake 文本绝不能回显给用户**; 用户只能看到 wake 回合重新生成的进展摘要
- **silent context nudge 不属于可播报进度**; 它只能在内部推动 webgen 自检/压缩,不能单独显示给用户
- fallback 可见文本若被外层 runtime 回显,也必须只显示 `当前进度`,不能携带 token 与整段调度说明
- `REPLY_SKIP`、`inter-session routing echo`、`Nothing to broadcast`、`Staying silent` 这类内部跳过/回声文本必须静默过滤,不能显示给用户

## 禁止事项

- 禁止只委托不续航
- 禁止把一次性 `sessions_history` 查询误当作轮询机制
- 禁止 tight loop 高频轮询
- 禁止在任务未交付前擅自结束直播链而不给出阻塞说明
- 禁止把 `【继续监听任务】...`、`[cron:...]`、`last_broadcast_seq=...` 这类内部提示词透传到用户对话

## 成功标准

- 用户从委托开始到交付/阻塞之间，始终能收到基于真实新增 history 的阶段性播报
- 不再出现“webgen 已有大量输出，但 main 没有继续播”的情况
- 不再出现 `[cron:...]` 或其他调度提示词泄露到用户对话的情况
- deterministic resume 与既有 `sessionKey` 身份保持稳定,不会因为 context 风险而切新 session
