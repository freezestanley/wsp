# WebGen Live Watch Supervisor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把直播监听从“短 worker + 文件变化触发”升级成“常驻 supervisor + 明确 degraded/manual_pull 语义 + backlog 补播”，修复 worker 退出后漏播的问题。

**Architecture:** 新增 `runtime/live-watch-supervisor.py` 作为唯一常驻监听器，统一接管 watch state、session 文件采样、history 增量拉取、自动回推和 backlog 落盘；`runtime/ensure-live-watch.py` 负责 supervisor 健康检查和启动；`runtime/live-webgen-progress.py` 降级为单 cycle helper 与补偿入口；`runtime/live_watch.py` 扩展 degraded/backlog/supervisor 状态字段。

**Tech Stack:** Python 3、现有 runtime watch state、OpenClaw session 存储、`unittest`

---

### Task 1: Add failing state-model tests for supervisor and degraded delivery

**Files:**
- Modify: `tests/test_live_watch.py`
- Modify: `runtime/live_watch.py`

**Step 1: Write the failing test**

覆盖以下行为：

- `WatchState` 能持久化：
  - `last_delivered_seq`
  - `pending_broadcast_items`
  - `pending_count`
  - `last_pending_summary`
  - `supervisor_pid`
  - `supervisor_started_at`
  - `supervisor_heartbeat_at`
  - `delivery_degraded_reason`
- 新增 helper 能判断：
  - watch 是否需要 supervisor
  - 当前是否 degraded
  - backlog 是否可取出

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest -v tests.test_live_watch`

Expected: FAIL because the new fields and helpers do not exist yet.

**Step 3: Write minimal implementation**

在 `runtime/live_watch.py` 中：

- 扩展 `WatchState`
- 更新 `load_watch_state()` / `save_watch_state()`
- 增加 backlog / degraded / supervisor helper

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest -v tests.test_live_watch`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live_watch.py tests/test_live_watch.py
git commit -m "refactor: extend live watch state for supervisor delivery"
```

### Task 2: Add failing ensure-watch tests for active vs degraded semantics

**Files:**
- Modify: `tests/test_ensure_live_watch.py`
- Modify: `runtime/ensure-live-watch.py`

**Step 1: Write the failing test**

覆盖以下行为：

- `manual_pull` 不再返回 `active`
- supervisor 不存在时，`ensure` 返回启动 supervisor 的 `start` 或 `resume`
- supervisor 存在但 delivery 不可自动回推时，返回 `degraded`
- 有 backlog 待补发时，不会误报 `idle`

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest -v tests.test_ensure_live_watch`

Expected: FAIL because current `ensure` 仍把 `manual_pull` 视为普通可恢复 watch。

**Step 3: Write minimal implementation**

在 `runtime/ensure-live-watch.py` 中：

- 加入 supervisor 存活检查
- 引入 `degraded` 返回态
- 更新 action resolution
- 生成 supervisor 启动 invocation

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest -v tests.test_ensure_live_watch`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/ensure-live-watch.py tests/test_ensure_live_watch.py
git commit -m "refactor: distinguish degraded live watch delivery"
```

### Task 3: Add failing supervisor cycle tests before writing the daemon

**Files:**
- Create: `tests/test_live_watch_supervisor.py`
- Create: `runtime/live-watch-supervisor.py`

**Step 1: Write the failing test**

覆盖 supervisor 单 watch cycle 的核心行为：

- 目标 session 文件变化时拉 `sessions_history(...)`
- `manual_pull` 时把摘要写入 backlog，不直接标已投递
- `rebroadcast` 成功时推进 `last_delivered_seq`
- session 文件失效时重新解析到新路径
- 没有新增消息时不重复写 backlog

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest -v tests.test_live_watch_supervisor`

Expected: FAIL because the supervisor module does not exist yet.

**Step 3: Write minimal implementation**

在 `runtime/live-watch-supervisor.py` 中先实现可单测的 cycle helper，例如：

- `run_supervisor_cycle(...)`
- `process_watch_once(...)`
- `deliver_or_queue_batch(...)`

先不急着写完整 CLI loop。

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest -v tests.test_live_watch_supervisor`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live-watch-supervisor.py tests/test_live_watch_supervisor.py
git commit -m "test: cover live watch supervisor cycle"
```

### Task 4: Extract shared watch-cycle logic from the short worker

**Files:**
- Modify: `runtime/live-webgen-progress.py`
- Modify: `tests/test_live_webgen_progress.py`
- Modify: `runtime/live-watch-supervisor.py`

**Step 1: Write the failing test**

覆盖以下行为：

- `live-webgen-progress.py` 仍可复用单 cycle helper
- session 文件变化、去抖、history 拉取、路径重解析逻辑仍保持
- 提取后现有 worker 回归不变

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest -v tests.test_live_webgen_progress tests.test_live_watch_supervisor`

Expected: FAIL because shared helper 还未抽出。

**Step 3: Write minimal implementation**

在 `runtime/live-webgen-progress.py` 中：

- 抽出通用单 cycle helper
- 保留现有 CLI
- 让 supervisor 复用这层文件变化检测逻辑

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest -v tests.test_live_webgen_progress tests.test_live_watch_supervisor`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live-webgen-progress.py runtime/live-watch-supervisor.py tests/test_live_webgen_progress.py tests/test_live_watch_supervisor.py
git commit -m "refactor: share file-triggered watch cycle with supervisor"
```

### Task 5: Implement the supervisor process and watch-state scan loop

**Files:**
- Create: `runtime/live-watch-supervisor.py`
- Modify: `runtime/live_watch.py`
- Modify: `tests/test_live_watch_supervisor.py`

**Step 1: Write the failing test**

覆盖以下行为：

- supervisor 能扫描 state 目录并只接管 `pending / active / degraded`
- `done / blocked` 不继续轮询
- heartbeat 会被写回 state
- 单实例 lease 能防止重复 supervisor 同时工作

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest -v tests.test_live_watch_supervisor`

Expected: FAIL because scan loop / lease 逻辑未完成。

**Step 3: Write minimal implementation**

在 `runtime/live-watch-supervisor.py` 中实现：

- state 扫描
- supervisor lease
- heartbeat 更新
- per-watch dispatch
- CLI loop，例如 `--once` / `--interval-seconds`

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest -v tests.test_live_watch_supervisor`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live-watch-supervisor.py runtime/live_watch.py tests/test_live_watch_supervisor.py
git commit -m "feat: add persistent live watch supervisor"
```

### Task 6: Rewire ensure-watch to bootstrap the supervisor instead of short-lived streaming

**Files:**
- Modify: `runtime/ensure-live-watch.py`
- Modify: `runtime/live_watch.py`
- Modify: `tests/test_ensure_live_watch.py`

**Step 1: Write the failing test**

覆盖：

- `ensure` 在 watch 存在但 supervisor 不活跃时，返回启动 supervisor 的 invocation
- `ensure` 不重复启动第二个 supervisor
- 有 backlog 未送达时返回 `resume` 或 `degraded`，而不是 `idle`

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest -v tests.test_ensure_live_watch`

Expected: FAIL because ensure 还在围绕 short worker 设计。

**Step 3: Write minimal implementation**

在 `runtime/ensure-live-watch.py` 中：

- 改用 supervisor 启动命令
- 保留现有 watch bootstrap 语义
- 把短 worker 留作 fallback / debug path

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest -v tests.test_ensure_live_watch`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/ensure-live-watch.py runtime/live_watch.py tests/test_ensure_live_watch.py
git commit -m "refactor: bootstrap persistent live watch supervisor"
```

### Task 7: Add backlog replay tests for normal user turns

**Files:**
- Modify: `tests/test_live_watch.py`
- Modify: `runtime/live_watch.py`
- Modify: `tests/test_webgen_live_broadcast_contract.py`

**Step 1: Write the failing test**

覆盖：

- `manual_pull` 下 backlog 会累积
- 下次普通用户回合会先补播 backlog
- 补播后推进 `last_delivered_seq` 并清空 pending items
- 合同测试中不再把 `manual_pull` 当自动直播

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest -v tests.test_live_watch tests.test_webgen_live_broadcast_contract`

Expected: FAIL because backlog replay contract 还未定义。

**Step 3: Write minimal implementation**

在 `runtime/live_watch.py` 中实现 backlog take/ack helper，并更新 contract 说明与断言。

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest -v tests.test_live_watch tests.test_webgen_live_broadcast_contract`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live_watch.py tests/test_live_watch.py tests/test_webgen_live_broadcast_contract.py
git commit -m "refactor: preserve and replay degraded live watch backlog"
```

### Task 8: Run full watcher verification

**Files:**
- Verify: `runtime/live_watch.py`
- Verify: `runtime/ensure-live-watch.py`
- Verify: `runtime/live-webgen-progress.py`
- Verify: `runtime/live-watch-supervisor.py`
- Verify: `tests/test_live_watch.py`
- Verify: `tests/test_ensure_live_watch.py`
- Verify: `tests/test_live_webgen_progress.py`
- Verify: `tests/test_live_watch_supervisor.py`
- Verify: `tests/test_webgen_live_broadcast_contract.py`

**Step 1: Run targeted tests**

Run: `python3 -m unittest -v tests.test_live_watch tests.test_ensure_live_watch tests.test_live_webgen_progress tests.test_live_watch_supervisor tests.test_webgen_live_broadcast_contract`

Expected: PASS

**Step 2: Run end-to-end ensure smoke**

Run: `python3 runtime/ensure-live-watch.py --session-key agent:webgen:proj-demo --json`

Expected: JSON 中能明确区分 `start / resume / active / degraded / idle`。

**Step 3: Run supervisor smoke**

Run: `python3 runtime/live-watch-supervisor.py --once --json`

Expected: 命令能扫描 state 并输出稳定 JSON，不抛 traceback。

**Step 4: Run fallback worker smoke**

Run: `python3 runtime/live-webgen-progress.py agent:webgen:proj-demo --once --jsonl --state-file /tmp/live-watch-state.json`

Expected: 仍可作为单次调试入口正常退出。

**Step 5: Commit**

```bash
git add runtime/live_watch.py runtime/ensure-live-watch.py runtime/live-webgen-progress.py runtime/live-watch-supervisor.py tests/test_live_watch.py tests/test_ensure_live_watch.py tests/test_live_webgen_progress.py tests/test_live_watch_supervisor.py tests/test_webgen_live_broadcast_contract.py
git commit -m "feat: persist live watch supervision across idle worker exits"
```
