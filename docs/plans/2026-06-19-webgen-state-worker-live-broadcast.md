# WebGen State-Driven Live Broadcast Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace cron-driven delegated `webgen` live broadcast with a state-driven `ensure + short worker` model that survives refreshes, main-process restarts, and worker crashes without losing key progress or the final summary.

**Architecture:** Keep the existing watch-state summarization and `rebroadcast` delivery helpers, but move the primary recovery signal from cron/rechain to persistent watch state plus worker leases. `runtime/ensure-live-watch.py` becomes the single decision point for `start / resume / active / idle`, while `runtime/live-webgen-progress.py` becomes a short-lived, re-entrant worker that polls history, rebroadcasts summaries, updates lease heartbeat, and exits when idle. Existing project detection and deterministic resume routing remain unchanged and continue to run before the new watch lifecycle begins.

**Tech Stack:** Python 3, unittest, markdown docs

---

### Task 1: Add failing tests for lease-based watch state

**Files:**
- Modify: `tests/test_live_watch.py`
- Test: `tests/test_live_watch.py`

**Step 1: Write the failing tests**

Add tests covering:
- `WatchState` round-trips `status`, `lease_owner`, `lease_until`, `last_worker_heartbeat_at`, `final_delivered`, and `final_summary`
- helper logic correctly distinguishes active vs expired lease
- terminal states still load safely from older state files with missing new fields

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python3 tests/test_live_watch.py`
Expected: FAIL because the new fields and lease helpers do not exist yet.

### Task 1.5: Lock project-resume compatibility before refactor

**Files:**
- Verify only

**Step 1: Re-read existing project routing contract**

Confirm the existing behavior that must stay unchanged:
- `runtime/webgen_resume_resolver.py`
- deterministic `projects/<slug>` / explicit `slug` / exact project-name matching
- `agent:webgen:proj-<slug>` session identity

**Step 2: Record the compatibility rule in implementation notes**

Implementation rule:
- do not move project detection into `ensure-live-watch.py`
- do not alter `slug -> sessionKey` binding
- always run resume resolver before entering the new watch lifecycle

### Task 2: Implement minimal lease model in watch state

**Files:**
- Modify: `runtime/live_watch.py`
- Test: `tests/test_live_watch.py`

**Step 1: Write minimal implementation**

Add:
- new `WatchState` fields:
  - `status`
  - `lease_owner`
  - `lease_until`
  - `last_worker_heartbeat_at`
  - `final_delivered`
  - `final_summary`
- load/save support
- small helpers for:
  - `has_active_lease(...)`
  - `is_terminal_watch(...)`
  - `needs_final_delivery(...)`

**Step 2: Run focused tests**

Run: `PYTHONPATH=. python3 tests/test_live_watch.py`
Expected: PASS

### Task 3: Add failing tests for ensure-watch state decisions

**Files:**
- Modify: `tests/test_ensure_live_watch.py`
- Test: `tests/test_ensure_live_watch.py`

**Step 1: Write the failing tests**

Add cases covering:
- no state -> `start`
- active lease -> `active`
- expired lease + running state -> `resume`
- terminal state + `final_delivered=false` -> `resume`
- terminal state + `final_delivered=true` -> `idle`

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python3 tests/test_ensure_live_watch.py`
Expected: FAIL because `ensure-live-watch.py` does not use lease/final-delivery semantics yet.

### Task 4: Promote ensure-watch to the only control-plane decision entry

**Files:**
- Modify: `runtime/ensure-live-watch.py`
- Modify: `runtime/live_watch.py`
- Test: `tests/test_ensure_live_watch.py`

**Step 1: Write minimal implementation**

Update `resolve_watch_action(...)` to:
- treat active lease as `active`
- treat expired lease on non-terminal watches as `resume`
- treat `final_delivered=false` as resumable even after terminal detection
- keep `start` behavior for first-time watches
- return a single normalized invocation for both `start` and `resume`

**Step 2: Run focused tests**

Run: `PYTHONPATH=. python3 tests/test_ensure_live_watch.py`
Expected: PASS

### Task 5: Add failing worker tests for lease heartbeat and idle exit

**Files:**
- Modify: `tests/test_live_webgen_progress.py`
- Test: `tests/test_live_webgen_progress.py`

**Step 1: Write the failing tests**

Add tests covering:
- worker claims lease before polling
- worker refreshes `last_worker_heartbeat_at`
- worker updates `last_seen_seq` and `last_broadcast_seq`
- worker marks `final_delivered=true` after successfully rebroadcasting terminal summary
- worker exits idle without scheduling cron or setting `needs_rechain`

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python3 tests/test_live_webgen_progress.py`
Expected: FAIL because the worker currently lacks lease/final-delivery lifecycle behavior.

### Task 6: Convert live-webgen-progress into a short-lived re-entrant worker

**Files:**
- Modify: `runtime/live-webgen-progress.py`
- Modify: `runtime/live_watch.py`
- Test: `tests/test_live_webgen_progress.py`

**Step 1: Write minimal implementation**

Add:
- worker identity / lease claim on startup
- heartbeat refresh on each cycle
- terminal summary persistence into `final_summary`
- `final_delivered=true` only after successful send
- idle-exit path after configurable quiet cycles
- explicit removal of cron/rechain assumptions from the main worker loop

**Step 2: Run focused tests**

Run: `PYTHONPATH=. python3 tests/test_live_webgen_progress.py`
Expected: PASS

### Task 7: Add regression coverage for old cron compatibility path

**Files:**
- Modify: `tests/test_rechain_watch.py`
- Modify: `tests/test_rechain_watch_once.py`
- Test: `tests/test_rechain_watch.py`
- Test: `tests/test_rechain_watch_once.py`

**Step 1: Write targeted regression tests**

Add tests proving:
- old `needs_rechain` states still resolve through compatibility tools
- new lease-based states do not require rechain CLI in the happy path

**Step 2: Run test to verify it fails where appropriate**

Run:
- `PYTHONPATH=. python3 tests/test_rechain_watch.py`
- `PYTHONPATH=. python3 tests/test_rechain_watch_once.py`

Expected: FAIL only if compatibility assumptions need adjustment.

### Task 8: Update protocol and migration docs

**Files:**
- Modify: `AGENTS.md`
- Modify: `skills/delegated-live-broadcasting/SKILL.md`
- Modify: `skills/webgen/SKILL.md`
- Modify: `docs/webgen-live-broadcast-migration.md`
- Modify: `packages/webgen-install/README.md`

**Step 1: Update guidance**

Document:
- cron is no longer the preferred continuation path
- `ensure-live-watch.py` is the single entry
- short worker + lease model
- final-summary delivery guarantee
- compatibility status of old rechain tools

**Step 2: Verify docs stay aligned**

Run: `rg -n "ensure-live-watch|lease|final_delivered|needs_rechain|cron" AGENTS.md skills/delegated-live-broadcasting/SKILL.md skills/webgen/SKILL.md docs/webgen-live-broadcast-migration.md packages/webgen-install/README.md`
Expected: consistent terminology and no claim that cron remains the primary path.

### Task 9: Run integrated verification

**Files:**
- Verify only

**Step 1: Run focused tests**

Run:
- `PYTHONPATH=. python3 tests/test_live_watch.py`
- `PYTHONPATH=. python3 tests/test_ensure_live_watch.py`
- `PYTHONPATH=. python3 tests/test_live_webgen_progress.py`
- `PYTHONPATH=. python3 tests/test_rechain_watch.py`
- `PYTHONPATH=. python3 tests/test_rechain_watch_once.py`
- `PYTHONPATH=. python3 tests/test_webgen_live_broadcast_contract.py`

Expected: PASS

**Step 2: Commit**

```bash
git add docs/plans/2026-06-19-webgen-state-worker-live-broadcast-design.md docs/plans/2026-06-19-webgen-state-worker-live-broadcast.md runtime/live_watch.py runtime/ensure-live-watch.py runtime/live-webgen-progress.py tests/test_live_watch.py tests/test_ensure_live_watch.py tests/test_live_webgen_progress.py tests/test_rechain_watch.py tests/test_rechain_watch_once.py AGENTS.md skills/delegated-live-broadcasting/SKILL.md skills/webgen/SKILL.md docs/webgen-live-broadcast-migration.md packages/webgen-install/README.md
git commit -m "refactor: move webgen live broadcast to state-driven workers"
```
