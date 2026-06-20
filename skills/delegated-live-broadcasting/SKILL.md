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

1. **首条直播后必须建立可恢复的续航机制**
   - 发送委托消息并向用户播报“已委托 + 当前阶段”后，不能直接结束而不安排下一次检查。
   - 当前主路径不再是“继续生成下一条 cron”，而是：
     - 持久化 `watch state`
     - 在普通用户回合通过 `prepare -> ensure -> short worker` 恢复或接管
   - 只有当前回合本身会继续挂起等待时，才可不走这条恢复链。

2. **默认优先使用 state-driven worker，而不是 cron wake**
   - 若调用侧还没拿到最终 `targetSessionKey`，优先：
     1. `python3 runtime/prepare-webgen-live-watch.py --message "<用户原话>" --slug <new-slug> --json`
     2. 它会先跑现有 deterministic resume 预检
     3. 再把最终 `targetSessionKey` 交给 watch 生命周期
   - 若调用侧已经拿到最终 `targetSessionKey`，优先：
     1. `python3 runtime/ensure-live-watch.py --session-key <目标sessionKey> --json`
     2. 根据返回的 `status: start | resume | active | idle` 决定是否拉起 worker
   - `start / resume` 一律直接执行返回的 `invocation.command + invocation.env`
   - `active` 说明已有 worker 持有有效 lease，禁止重复拉第二条 watcher
   - `idle` 说明当前 watch 已终态或暂无恢复动作
   - worker 主路径依赖：
     - `sessions_history(sessionKey=...)`
     - `sessions_send(sessionKey=...)`
     - `watch state`
   - worker 是**短生命周期**的：拿 lease、轮询一段时间、回推新增摘要、空闲退出；下一次普通用户回合还能重新接管
   - `sessions_send` 不能想当然默认可用；若 watcher 是经 HTTP gateway 调工具,应先根据 `gateway.tools.allow/deny` 判断它是否被显式放开。
   - 只有在 hidden wake 和 `rebroadcast` 都不可用时，才允许退化到 **`manual_pull`**，并且不能对用户承诺“自动直播”。
   - 禁止使用 `sessionTarget:"main"` + `payload.kind:"systemEvent"` 来尝试回到当前用户对话继续直播。
   - 若旧 cron 兼容路径命中 `Cron tool is restricted to the current cron job.`，不得再次 `cron.add` 新 job；只能把它视为旧路径受限，并在下一次普通用户回合切回 `prepare / ensure` 主路径。

3. **允许静默 context nudge,但它不是用户进度播报**
   - 如果 watcher 当前能拿到 context usage ratio,可在 wake 回合内部计算 `ok / warn / compact / force-compact` band,并在 band 升级时规划一条 silent context nudge,提醒 webgen 先检查 context、必要时 `/compact` 后继续当前任务。
   - 如果拿不到 context usage ratio,watcher 行为保持原样,不要因为缺少该指标而改变现有直播逻辑。
   - silent context nudge 是内部控制面动作,**不能**单独形成用户可见的“当前进度”或其他直播文本;只有真实新增 history 才值得播报。
   - 当前 workspace 只实现了 watcher 内部决策/状态演进;真正的 hidden `sessions_send` 投递和 `[cron:...]` / `Current time` / `Reference UTC` 抑制仍依赖上游 runtime。

4. **绝不把“我会开始直播”当成已启动直播链路**
   - 只有在已经完成等待或 wake 安排后，才能视为“直播已启动”。
   - 如果只是发送委托并回复用户“我会直播”，但没有建立后续检查机制，这属于流程错误。

5. **直播停止条件**
   - 仅当被委托 session 明确满足以下任一条件时，才停止继续接管：
     - 明确交付
     - 明确阻塞且需要用户决策
     - 任务被取消

6. **补救规则**
   - 如果用户指出“直播没起效”“你漏播了”，必须立即：
     1. 拉取目标 session history
     2. 补播最近关键步骤
     3. 明确说明漏播原因
   4. 立刻恢复 `prepare / ensure / worker` 链

7. **错误路径硬禁令**
   - 禁止使用 `sessionTarget:"main"` + `payload.kind:"systemEvent"` 来尝试回到当前用户对话继续直播。
   - 若 wake 回合命中 `Cron tool is restricted to the current cron job.`，这不是“继续新建 cron”的信号，而是“只能操作当前 cron job”的限制提示。

## 推荐执行模板

### 委托当回合
1. `sessions_send(sessionKey=..., message=完整任务包)`
2. 向用户发送首条：已委托 + 当前阶段
3. 记录 `originSessionKey`
4. 若还未拿到最终 `targetSessionKey`，调 `prepare-webgen-live-watch.py`
5. 若已拿到最终 `targetSessionKey`，调 `ensure-live-watch.py`
6. 若返回 `start / resume`，直接执行其 `invocation`
7. 若返回 `active`，当前回合不重复拉第二条 worker
8. 结束当前回合

### worker 周期
1. 抢占或续约 lease
2. `sessions_history(sessionKey=目标session, includeTools=true, limit=适中)`
3. 若当前有 context usage ratio，可先在内部计算 compaction band，并决定是否规划 silent context nudge；若没有 ratio，跳过这一步，其他行为不变
4. 读取并提炼自上次播报后的新增动作
5. 若有新增，则播报 1–3 条关键进展；若无新增，静默即可。仅 silent nudge 本身不能触发任何用户可见输出
6. 若当前策略是 `rebroadcast`，把这些关键进展合并后 `sessions_send(sessionKey=originSessionKey, message=摘要)` 回推到原会话
7. 更新 `lastSeenSeq / lastBroadcastSeq / finalDelivered`
8. 若未结束且短窗口内仍有活跃进展，继续轮询；若长时间空闲，则主动退出，让下一次普通用户回合重新接管

## 播报约束

- 只播新增，不重复已播内容
- 可补充播报关键委托/控制面事件，但优先级低于真实执行新增
- 不贴大段原始日志
- 用简短中文翻译工具动作与结果
- 没有新增时静默，不发“暂无更新”
- 但首条“已委托 + 阶段”不可省略
- **内部 wake 文本绝不能回显给用户**; 用户只能看到 worker / 普通用户回合重新生成的进展摘要
- **silent context nudge 不属于可播报进度**; 它只能在内部推动 webgen 自检/压缩,不能单独显示给用户
- fallback 可见文本若被外层 runtime 回显,也必须只显示 `当前进度`,不能携带 token 与整段调度说明
- `REPLY_SKIP`、`inter-session routing echo`、`Nothing to broadcast`、`Staying silent` 这类内部跳过/回声文本必须静默过滤,不能显示给用户

## 禁止事项

- 禁止只委托不续航
- 禁止把一次性 `sessions_history` 查询误当作轮询机制
- 禁止 tight loop 高频轮询
- 禁止在任务未交付前擅自结束直播链而不给出阻塞说明
- 禁止把 `【继续监听任务】...`、`[cron:...]`、`last_broadcast_seq=...` 这类内部提示词透传到用户对话
- 禁止把旧 `cron/rechain` 兼容路径继续当作默认主路径

## 成功标准

- 用户从委托开始到交付/阻塞之间，始终能收到基于真实新增 history 的阶段性播报
- 不再出现“webgen 已有大量输出，但 main 没有继续播”的情况
- 不再出现 `[cron:...]` 或其他调度提示词泄露到用户对话的情况
- 在无 runtime patch 的实例上，默认仍可通过 `originSessionKey + rebroadcast` 收到自动播报
- deterministic resume 与既有 `sessionKey` 身份保持稳定,不会因为 context 风险而切新 session
- 普通用户回合可以仅通过 `prepare-webgen-live-watch.py` 或 `ensure-live-watch.py` 恢复主链路
