---
name: "webgen"
description: "将建站类内容原样委托给 webgen agent，main 只做转发与进度播报，禁止 main 自行实现页面或做其他事。"
---

# webgen

## 作用

把用户的内容**原样委托给 `webgen` agent**。main 只做**转发 + 调度 + 进度播报**，**禁止** main 自己写页面代码、自己实现需求或做委托之外的其他事。

## 触发

用户调用 `/webgen` 或要求"交给 webgen / 委托 webgen / 让 webgen 做"时。

## 核心规则

1. **纯转发**：把用户原始输入**逐字、完整、准确**转发给 webgen，禁止改写、润色、删减、补写、改述或重构。
   - 可在原文之外**追加**调度说明（sessionKey、监听要求等），但必须明确标注为"附加说明（非用户原话）"，不得与用户原文混写。
   - 用户输入再短再模糊，也先逐字转发原话，再追加调度说明。
2. **禁止越界**：main 不得自行实现页面、写单文件 demo、或做委托之外的任何事，除非用户明确说"这个你自己做"。
3. **老项目先做确定性 resume 预检**：
   - 如果用户明确是在修改旧项目，且消息里确定性出现 `projects/<slug>`、明确 `slug`（如 `slug: gshock-site` / `slug=gshock-site` / 直接出现已存在的精确 slug），或**唯一可映射**到现有项目的精确项目名，main 必须先做 resume 预检。
   - 预检入口：`python3 runtime/webgen_resume_resolver.py --stdin`
   - 命中后直接使用返回的 `sessionKey` 和 `mode=resume:<slug>` 委托，**不要**先发到 `agentId="webgen"`。
   - 若结果是 `no-deterministic-project-match`，再回到正常澄清 / 新项目路由；若结果是 `ambiguous-deterministic-project-match`，先向用户确认到底是哪个旧项目。
   - 这一步只做确定性复用，不做模糊猜测。
   - 若调用侧想走统一桥接入口，可直接用 `python3 runtime/prepare-webgen-live-watch.py --message "<用户原话>" --json`；它内部仍然先做这一步 resume 预检，不改变规则。
4. **用独立 sessionKey 落地**：
   - 澄清/Discovery（只问不写）：可用 `sessions_send(agentId="webgen", ...)`。
   - 老项目且预检命中时：直接用 resolver 返回的 `sessionKey` 委托并监听。
   - 一旦确认落地新项目：必须用 `sessions_send(sessionKey="agent:webgen:proj-<slug>", message=完整任务包)`，`<slug>` 为项目英文短名。
   - 本轮 context stopgap **不允许**为了降上下文而改动 `slug -> sessionKey` 绑定、single active project session 语义、或 resume 的确定性路由；不要引入 session rollover / 临时换绑。
   - 不要用 `agentId="webgen"` 落地实现，会撞 webgen 的单项目锁导致 ping-pong 死结。
5. **委托后立即监听**：
   - 首条播报"已委托 + 当前阶段 + 承载任务的 sessionKey"。
   - 若此时还未显式拿到最终 `targetSessionKey`，优先走 `python3 runtime/prepare-webgen-live-watch.py --message "<用户原话>" --slug <new-slug> --json`，让它统一完成“项目检索/复用判断 + ensure-watch”。
   - **统一入口**：无论是首次拉起 watcher，还是 cron 受限后的普通用户回合补链，都优先调用 `python3 runtime/ensure-live-watch.py --session-key <目标sessionKey> --json`。
   - 若返回 `status: "start"` 或 `status: "resume"`：直接执行返回的 `invocation.command + invocation.env`，不要自己手拼 `--state-file / --watch-id / --delivery-strategy`。
   - 若返回 `status: "active"`：说明当前 watch 已处于活跃态，普通用户回合不要重复拉起第二条 watcher。
   - 若返回 `status: "idle"`：说明当前 watch 已终态或暂无可恢复动作，可按当前任务状态决定是否静默。
   - 同一回合内建立续航：优先使用 hidden/internal wake；若目标实例不支持 hidden wake,则必须记录 `originSessionKey` 并切到 `rebroadcast`，由 watcher 后续把新增摘要 `sessions_send` 回原会话。payload 仅含结构化字段（watchId/targetSessionKey/lastSeenSeq/phase），**禁止**把自然语言调度提示词通过 announce 投进对话框。
   - `sessions_send` 经 HTTP gateway 默认可能被禁用；portable 模式下应先检查 `gateway.tools.allow/deny`，不要把 `rebroadcast` 当成无条件可用。
   - 禁止使用 `sessionTarget:"main"` + `payload.kind:"systemEvent"` 冒充“回到当前对话继续播报”。
   - 若当前 wake 回合命中 `Cron tool is restricted to the current cron job.`，不得再次新建 `cron.add`；优先沿用当前 job，若 runtime 支持则 `cron.update` 当前 job；若当前回合做不到，就在下一次普通用户回合立即补链，不得把失败伪装成已续播。
   - 每次 wake 拉 `sessions_history(目标sessionKey, includeTools=true)`，只播**新增**步骤，翻译成 1–3 条中文人话。
   - 若当前策略是 `rebroadcast`,则这些中文摘要必须显式发回 `originSessionKey`,不要依赖“当前会话”隐式路由。
   - 未交付/未阻塞则继续安排下一次 wake；交付或明确阻塞时停止并删除 cron。
6. **澄清转达**：webgen 反问澄清 → 原样转给用户 → 用户答复 → 回传 webgen。
7. **交付汇总**：webgen 交付后，用 main 自己口吻汇总改了哪些文件、位置、如何预览、剩余风险。
8. **Discovery 阶段控制 transcript 增长**：
   - 禁止把整份 `DISCOVERY.md`、`PROJECT.md`、大体积 mock 数据、整页源码一次性 dump 进 transcript。
   - 优先用 `rg -n` 先定位字段，再用 `sed -n '<start>,<end>p'` 只读窄窗口。
   - 对 `DISCOVERY.md` 只保留结构化摘要：`Design Read`、`DESIGN_VARIANCE`、`MOTION_INTENSITY`、`VISUAL_DENSITY`、`Device Adaptation`。
   - `read` / `exec` 返回过大时，必须先摘要后再继续推理，避免把超长原文继续堆进对话历史。

## 前提

- `tools.agentToAgent.enabled=true` 且 `tools.sessions.visibility=all`，否则跨 agent 委托被拒。
- 详细监听协议见 `delegated-live-broadcasting` skill。

## 禁止事项

- 禁止 main 改写用户原始输入。
- 禁止 main 自行实现页面或做委托之外的事。
- 禁止只委托不建监听续航。
- 禁止把内部调度提示词（`[cron:...]`、`last_broadcast_seq=...` 等）泄露到用户对话。
- 禁止使用 `sessionTarget:"main"` + `payload.kind:"systemEvent"` 冒充“回到当前对话继续播报”。
- 禁止把 runtime patch 当成外部实例可用性的前提；迁移时默认先按 `rebroadcast` 能力设计。
