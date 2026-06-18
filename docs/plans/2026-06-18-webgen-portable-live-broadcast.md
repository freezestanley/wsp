# WebGen Portable Live Broadcast Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make delegated `webgen` live broadcast work on OpenClaw instances that cannot patch runtime by persisting an explicit origin session and rebroadcasting progress summaries back to that session when hidden wake is unavailable.

**Architecture:** Extend the existing watch-state/runtime helper layer with a small capability-based delivery strategy selector. Hidden wake remains the preferred path, but the portable default becomes `rebroadcast` when `sessions_send` and an `originSessionKey` are available. The watcher script will either emit locally, rebroadcast to the origin session, or fall back to manual pull mode.

**Tech Stack:** Python 3, unittest, markdown docs

---

### Task 1: Add failing watch-state tests for portable delivery strategy

**Files:**
- Modify: `tests/test_live_watch.py`
- Test: `tests/test_live_watch.py`

**Step 1: Write the failing tests**

Add tests covering:
- `WatchState` round-trips `origin_session_key` and `delivery_strategy`
- delivery strategy resolves to `hidden_wake` when hidden wake is supported
- delivery strategy resolves to `rebroadcast` when hidden wake is unavailable but `sessions_send` and `originSessionKey` are available
- delivery strategy resolves to `manual_pull` otherwise

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_watch.py -q`
Expected: FAIL because the new fields and strategy resolver do not exist yet.

### Task 2: Implement portable delivery strategy in watch state

**Files:**
- Modify: `runtime/live_watch.py`
- Test: `tests/test_live_watch.py`

**Step 1: Write minimal implementation**

Add:
- `origin_session_key` and `delivery_strategy` fields to `WatchState`
- load/save support for both fields
- `resolve_delivery_strategy(...)` helper

**Step 2: Run focused tests**

Run: `python3 -m pytest tests/test_live_watch.py -q`
Expected: PASS

### Task 3: Add failing watcher tests for rebroadcast delivery

**Files:**
- Modify: `tests/test_live_webgen_progress.py`
- Test: `tests/test_live_webgen_progress.py`

**Step 1: Write the failing tests**

Add tests covering:
- batch delivery in `rebroadcast` mode calls `sessions_send` with the joined summary text
- batch delivery in `manual_pull` mode only writes to local stream
- `auto` strategy chooses `rebroadcast` when hidden wake is disabled but origin session is present

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_webgen_progress.py -q`
Expected: FAIL because rebroadcast delivery helpers and strategy resolution are not wired yet.

### Task 4: Implement rebroadcast delivery in watcher tooling

**Files:**
- Modify: `runtime/live-webgen-progress.py`
- Modify: `runtime/live_watch.py`
- Test: `tests/test_live_webgen_progress.py`

**Step 1: Write minimal implementation**

Add:
- `invoke_sessions_send(...)`
- `render_batch_text(...)`
- `deliver_batch(...)`
- CLI args:
  - `--origin-session-key`
  - `--delivery-strategy`
  - `--supports-hidden-wake`
  - `--supports-sessions-send`
- `auto` strategy resolution using the watch-state helper

**Step 2: Run focused tests**

Run: `python3 -m pytest tests/test_live_webgen_progress.py -q`
Expected: PASS

### Task 5: Update protocol docs to describe A/B/C portability

**Files:**
- Modify: `AGENTS.md`
- Modify: `skills/delegated-live-broadcasting/SKILL.md`
- Modify: `skills/webgen/SKILL.md`
- Modify: `docs/webgen-live-broadcast-migration.md`

**Step 1: Update guidance**

Document:
- `hidden_wake` as enhancement path
- `rebroadcast` as portable default
- `manual_pull` as last-resort fallback
- requirement to persist `originSessionKey`

**Step 2: Verify docs stay aligned**

Run: `rg -n "originSessionKey|rebroadcast|manual_pull|hidden_wake" AGENTS.md skills/delegated-live-broadcasting/SKILL.md skills/webgen/SKILL.md docs/webgen-live-broadcast-migration.md`
Expected: matching terminology across all files.

### Task 6: Run integrated verification

**Files:**
- Verify only

**Step 1: Run focused tests**

Run:
- `python3 -m pytest tests/test_live_watch.py -q`
- `python3 -m pytest tests/test_live_webgen_progress.py -q`

Expected: PASS

**Step 2: Commit**

```bash
git add docs/plans/2026-06-18-webgen-portable-live-broadcast-design.md docs/plans/2026-06-18-webgen-portable-live-broadcast.md runtime/live_watch.py runtime/live-webgen-progress.py tests/test_live_watch.py tests/test_live_webgen_progress.py AGENTS.md skills/delegated-live-broadcasting/SKILL.md skills/webgen/SKILL.md docs/webgen-live-broadcast-migration.md
git commit -m "feat: add portable webgen live broadcast fallback"
```
