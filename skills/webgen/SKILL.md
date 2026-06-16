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
3. **用独立 sessionKey 落地**：
   - 澄清/Discovery（只问不写）：可用 `sessions_send(agentId="webgen", ...)`。
   - 一旦确认落地新项目：必须用 `sessions_send(sessionKey="agent:webgen:proj-<slug>", message=完整任务包)`，`<slug>` 为项目英文短名。
   - 不要用 `agentId="webgen"` 落地实现，会撞 webgen 的单项目锁导致 ping-pong 死结。
4. **委托后立即监听**：
   - 首条播报"已委托 + 当前阶段 + 承载任务的 sessionKey"。
   - 同一回合内建立续航：用 `cron.add` 安排 20–40 秒后的 hidden/internal wake，payload 仅含结构化字段（watchId/targetSessionKey/lastSeenSeq/phase），**禁止**把自然语言调度提示词通过 announce 投进对话框。
   - 每次 wake 拉 `sessions_history(目标sessionKey, includeTools=true)`，只播**新增**步骤，翻译成 1–3 条中文人话。
   - 未交付/未阻塞则继续安排下一次 wake；交付或明确阻塞时停止并删除 cron。
5. **澄清转达**：webgen 反问澄清 → 原样转给用户 → 用户答复 → 回传 webgen。
6. **交付汇总**：webgen 交付后，用 main 自己口吻汇总改了哪些文件、位置、如何预览、剩余风险。

## 前提

- `tools.agentToAgent.enabled=true` 且 `tools.sessions.visibility=all`，否则跨 agent 委托被拒。
- 详细监听协议见 `delegated-live-broadcasting` skill。

## 禁止事项

- 禁止 main 改写用户原始输入。
- 禁止 main 自行实现页面或做委托之外的事。
- 禁止只委托不建监听续航。
- 禁止把内部调度提示词（`[cron:...]`、`last_broadcast_seq=...` 等）泄露到用户对话。
