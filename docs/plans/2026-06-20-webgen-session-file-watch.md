# Session File Watch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将直播 worker 的触发机制从固定时间轮询 `sessions_history(...)` 改为“session 文件变化触发 + history 标准读取”，同时保留现有 watch state 恢复链。

**Architecture:** 新增一个 `runtime/session_file_watch.py` 负责 `sessionKey -> sessionFile` 解析、文件状态采样和变更判断；`runtime/live-webgen-progress.py` 改为优先等待 session 文件变化，再在去抖后调用 `sessions_history(...)`。`runtime/live_watch.py` 扩展最小状态字段，`runtime/ensure-live-watch.py` 仅补足 worker invocation 参数，不改变主状态机。

**Tech Stack:** Python 3、现有 runtime watch state、OpenClaw session 存储、`unittest`

---

### Task 1: Add failing tests for session file resolution and sampling

**Files:**
- Create: `tests/test_session_file_watch.py`
- Create: `runtime/session_file_watch.py`

**Step 1: Write the failing tests**

覆盖以下行为：

- `resolve_session_file_path()` 能从 `sessions.json` 的 `sessionFile` 字段解析路径
- 没有 `sessionFile` 时，能从 `sessionId` 推导 `<session-id>.jsonl`
- session key 不存在时返回 `None`
- `sample_session_file()` 在文件存在/不存在时返回稳定结构
- `detect_session_file_change()` 能识别 `mtime / size / inode / exists` 变化

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_session_file_watch.py -v`

Expected: FAIL because `runtime/session_file_watch.py` does not exist yet.

**Step 3: Write minimal implementation**

在 `runtime/session_file_watch.py` 中实现：

- `SessionFileSample` 数据结构
- `resolve_session_file_path(...)`
- `sample_session_file(...)`
- `detect_session_file_change(...)`

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_session_file_watch.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_session_file_watch.py runtime/session_file_watch.py
git commit -m "test: cover session file watch resolution"
```

### Task 2: Extend watch state for session file metadata

**Files:**
- Modify: `runtime/live_watch.py`
- Modify: `tests/test_live_watch.py`

**Step 1: Write the failing test**

在 `tests/test_live_watch.py` 中增加 round-trip 断言：

- `WatchState` 能保存并恢复
  - `session_file_path`
  - `session_file_mtime`
  - `session_file_size`
  - `session_file_inode`
  - `last_session_event_at`
  - `last_history_pull_at`

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_watch.py -v`

Expected: FAIL because the new fields are not part of `WatchState` persistence yet.

**Step 3: Write minimal implementation**

在 `runtime/live_watch.py` 中：

- 扩展 `WatchState`
- 更新 `load_watch_state()` 默认值
- 更新 `save_watch_state()` round-trip

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_live_watch.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live_watch.py tests/test_live_watch.py
git commit -m "refactor: persist session file watch state"
```

### Task 3: Add failing worker tests for file-triggered polling

**Files:**
- Modify: `tests/test_live_webgen_progress.py`
- Modify: `runtime/live-webgen-progress.py`

**Step 1: Write the failing tests**

在 `tests/test_live_webgen_progress.py` 中增加可单测 helper 的断言，建议拆出小函数，覆盖：

- 文件未变化时，不触发 history 拉取
- 文件变化后，worker 判断需要拉取 history
- 去抖窗口内的多次变化只触发一次
- 无法定位文件时，worker 进入 fallback polling

如果现有 `main()` 过大，先为以下 helper 写测试：

- `resolve_or_refresh_session_file(...)`
- `should_pull_history_from_file_event(...)`
- `should_run_fallback_history_pull(...)`

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_webgen_progress.py -v`

Expected: FAIL because file-event helpers do not exist yet.

**Step 3: Write minimal implementation**

在 `runtime/live-webgen-progress.py` 中新增：

- session 文件解析接入
- 文件采样状态刷新
- 基于文件变化的 history pull 判定
- fallback polling 判定

先让 helper 可测，不急着一次性重写整个 worker 循环。

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_live_webgen_progress.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live-webgen-progress.py tests/test_live_webgen_progress.py
git commit -m "test: add file-triggered worker polling helpers"
```

### Task 4: Convert the worker loop to file-triggered history pulls

**Files:**
- Modify: `runtime/live-webgen-progress.py`
- Test: `tests/test_live_webgen_progress.py`

**Step 1: Write the failing test**

新增或扩展 worker 行为测试，覆盖：

- 启动时写入解析出的 `session_file_path`
- 文件变化后拉取 `sessions_history(...)`
- `last_history_pull_at` 与文件采样状态被更新
- 文件变化但无新增消息时不重播
- 终态补发与 `final_delivered` 逻辑保持不变

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_webgen_progress.py -v`

Expected: FAIL because the main worker loop still polls on fixed interval.

**Step 3: Write minimal implementation**

在 `runtime/live-webgen-progress.py` 中：

- 接入 `runtime/session_file_watch.py`
- 用“文件采样 -> 去抖 -> history pull”的循环替换固定轮询
- 保留 lease heartbeat、rebroadcast、manual pull、context nudge
- 当 session 文件不可用时，退回低频 history polling

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_live_webgen_progress.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live-webgen-progress.py tests/test_live_webgen_progress.py
git commit -m "refactor: trigger live worker from session file changes"
```

### Task 5: Thread new worker parameters through ensure-watch bootstrap

**Files:**
- Modify: `runtime/live_watch.py`
- Modify: `runtime/ensure-live-watch.py`
- Modify: `tests/test_ensure_live_watch.py`

**Step 1: Write the failing test**

在 `tests/test_ensure_live_watch.py` 中增加断言：

- worker invocation 支持新的去抖 / fallback 参数
- `resume` 场景不会清空已有 session 文件状态

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ensure_live_watch.py -v`

Expected: FAIL because invocation does not include the new arguments yet.

**Step 3: Write minimal implementation**

在 `runtime/live_watch.py` 的 `build_watch_invocation()` 中补充可选参数，例如：

- `--debounce-ms`
- `--fallback-history-interval-seconds`

在 `runtime/ensure-live-watch.py` 中把它们传给 invocation builder。

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ensure_live_watch.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live_watch.py runtime/ensure-live-watch.py tests/test_ensure_live_watch.py
git commit -m "refactor: thread file-watch worker options through ensure"
```

### Task 6: Run full runtime watcher verification

**Files:**
- Verify: `runtime/session_file_watch.py`
- Verify: `runtime/live_watch.py`
- Verify: `runtime/live-webgen-progress.py`
- Verify: `runtime/ensure-live-watch.py`
- Verify: `tests/test_session_file_watch.py`
- Verify: `tests/test_live_watch.py`
- Verify: `tests/test_live_webgen_progress.py`
- Verify: `tests/test_ensure_live_watch.py`

**Step 1: Run targeted tests**

Run: `python3 -m pytest tests/test_session_file_watch.py tests/test_live_watch.py tests/test_live_webgen_progress.py tests/test_ensure_live_watch.py -v`

Expected: PASS

**Step 2: Run contract regression**

Run: `python3 -m pytest tests/test_webgen_live_broadcast_contract.py -v`

Expected: PASS, confirming the higher-level live broadcast contract still holds.

**Step 3: Run a smoke command for ensure-watch**

Run: `python3 runtime/ensure-live-watch.py --session-key agent:webgen:proj-demo --json`

Expected: Outputs `start|resume|active|idle` JSON without crashing.

**Step 4: Run a worker smoke command**

Run: `python3 runtime/live-webgen-progress.py agent:webgen:proj-demo --once --jsonl --state-file /tmp/live-watch-state.json`

Expected: Command exits cleanly and emits either no rows or a valid JSONL batch without tracebacks.

**Step 5: Commit**

```bash
git add runtime/session_file_watch.py runtime/live_watch.py runtime/live-webgen-progress.py runtime/ensure-live-watch.py tests/test_session_file_watch.py tests/test_live_watch.py tests/test_live_webgen_progress.py tests/test_ensure_live_watch.py
git commit -m "refactor: drive webgen live watch from session file changes"
```
