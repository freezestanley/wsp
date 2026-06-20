# Webgen Rebroadcast Reliability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make delegated webgen live broadcast treat rebroadcast delivery as a first-class health signal so new progress is automatically pushed back to the origin chat whenever collection is still alive.

**Architecture:** Keep the current `ensure-live-watch -> live-watch-supervisor -> live-webgen-progress` structure, but upgrade watch state to track delivery freshness, backlog age, and repeated rebroadcast failures. The supervisor becomes responsible for replaying pending backlog before and alongside newly collected summaries, while `ensure-live-watch.py` stops calling a watch `active` when collection is alive but delivery is lagging or failing.

**Tech Stack:** Python 3, unittest, existing `runtime/live_watch.py` state store, `runtime/live-watch-supervisor.py`, `runtime/live-webgen-progress.py`, `runtime/ensure-live-watch.py`

---

### Task 1: Define delivery-health state and helper semantics

**Files:**
- Modify: `runtime/live_watch.py`
- Test: `tests/test_live_watch.py`

**Step 1: Write the failing tests**

Add tests that pin the new delivery-health behavior:

```python
def test_watch_is_delivery_degraded_when_backlog_exists_for_rebroadcast():
    state = WatchState(
        watch_id="watch-rebroadcast",
        target_session_key="agent:webgen:proj-demo",
        delivery_strategy="rebroadcast",
        pending_broadcast_items=[{"seq": 41, "summary": "🔧 正在验证"}],
        pending_count=1,
        delivery_failure_count=2,
        delivery_backlog_since=100.0,
    )
    assert watch_is_delivery_degraded(state) is True


def test_watch_has_delivery_lag_when_last_seen_is_ahead_of_last_delivered():
    state = WatchState(
        watch_id="watch-rebroadcast",
        target_session_key="agent:webgen:proj-demo",
        delivery_strategy="rebroadcast",
        last_seen_seq=45,
        last_delivered_seq=42,
    )
    assert watch_has_delivery_lag(state) is True
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_watch.py -k "delivery_degraded or delivery_lag" -v`

Expected: FAIL because `WatchState` and helper functions do not model rebroadcast backlog/failure health yet.

**Step 3: Write minimal implementation**

In `runtime/live_watch.py`:

- Extend `WatchState` with:
  - `last_delivery_attempt_at: float = 0.0`
  - `last_delivery_success_at: float = 0.0`
  - `delivery_failure_count: int = 0`
  - `delivery_backlog_since: float = 0.0`
  - `last_delivery_error: str = ""`
- Load/save these fields with backward-compatible defaults.
- Add helper `watch_has_delivery_lag(state: WatchState) -> bool`.
- Change `watch_is_delivery_degraded(...)` so it returns `True` for:
  - `manual_pull`
  - any pending rebroadcast backlog
  - any non-empty `last_delivery_error`
  - any `last_delivered_seq < last_seen_seq` lag once the watch has already seen messages

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_live_watch.py -k "delivery_degraded or delivery_lag" -v`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live_watch.py tests/test_live_watch.py
git commit -m "test: define delivery health state for live watch"
```

### Task 2: Make backlog a replay queue instead of passive storage

**Files:**
- Modify: `runtime/live-watch-supervisor.py`
- Test: `tests/test_live_watch_supervisor.py`

**Step 1: Write the failing tests**

Add tests for replay-first semantics:

```python
def test_process_watch_once_replays_existing_backlog_before_new_items():
    state = WatchState(
        watch_id="watch-demo",
        target_session_key="agent:webgen:proj-demo",
        delivery_strategy="rebroadcast",
        pending_broadcast_items=[{"seq": 41, "summary": "🔧 正在构建"}],
        pending_count=1,
        last_delivered_seq=40,
    )

    delivered_batches = []

    def fake_run_watch_cycle(**kwargs):
        return kwargs["watch_state"], 42, [{"seq": 42, "summary": "✅ 构建成功"}], True

    updated, batch, delivered = process_watch_once(
        state,
        now=100.0,
        run_watch_cycle_fn=fake_run_watch_cycle,
        deliver_batch_fn=lambda items: delivered_batches.append(items) or True,
    )

    assert delivered is True
    assert delivered_batches == [[
        {"seq": 41, "summary": "🔧 正在构建"},
        {"seq": 42, "summary": "✅ 构建成功"},
    ]]
    assert updated.pending_count == 0
    assert updated.last_delivered_seq == 42
```

Add a second test proving backlog is retried even when no new history arrives.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_watch_supervisor.py -k "replay or backlog" -v`

Expected: FAIL because current `process_watch_once()` only delivers the fresh batch and does not proactively replay stored backlog.

**Step 3: Write minimal implementation**

In `runtime/live-watch-supervisor.py`:

- Add a helper that merges `pending_broadcast_items` with the new batch in seq order without duplication.
- Change `process_watch_once(...)` so each cycle:
  - takes pending backlog from state
  - fetches new history
  - merges backlog + fresh items
  - attempts delivery on the merged batch
  - re-queues undelivered items on failure
- Preserve `session_file_path` and `last_seen_seq` updates from `run_watch_cycle(...)`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_live_watch_supervisor.py -k "replay or backlog" -v`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live-watch-supervisor.py tests/test_live_watch_supervisor.py
git commit -m "feat: replay pending rebroadcast backlog in supervisor"
```

### Task 3: Persist delivery attempts and rebroadcast failure details

**Files:**
- Modify: `runtime/live-watch-supervisor.py`
- Modify: `runtime/live-webgen-progress.py`
- Test: `tests/test_live_watch_supervisor.py`
- Test: `tests/test_live_webgen_progress.py`

**Step 1: Write the failing tests**

Add tests such as:

```python
def test_process_watch_once_records_delivery_failure_metadata():
    state = WatchState(
        watch_id="watch-demo",
        target_session_key="agent:webgen:proj-demo",
        delivery_strategy="rebroadcast",
        last_seen_seq=41,
    )

    def fake_run_watch_cycle(**kwargs):
        return kwargs["watch_state"], 42, [{"seq": 42, "summary": "🔧 继续验证"}], True

    updated, _batch, delivered = process_watch_once(
        state,
        now=100.0,
        run_watch_cycle_fn=fake_run_watch_cycle,
        deliver_batch_fn=lambda _batch: False,
    )

    assert delivered is False
    assert updated.delivery_failure_count == 1
    assert updated.last_delivery_attempt_at == 100.0
    assert updated.delivery_backlog_since == 100.0
```

Add a `live-webgen-progress.py` test proving non-`sessions_send unavailable` rebroadcast failures still surface structured error text rather than silently vanishing.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_watch_supervisor.py tests/test_live_webgen_progress.py -k "delivery_failure_metadata or rebroadcast_failure" -v`

Expected: FAIL because current code tracks only `delivery_degraded_reason` and swallows generic rebroadcast failures.

**Step 3: Write minimal implementation**

In `runtime/live-watch-supervisor.py`:

- When attempting delivery, update:
  - `last_delivery_attempt_at`
  - `last_delivery_success_at`
  - `delivery_failure_count`
  - `delivery_backlog_since`
  - `last_delivery_error`
- Reset failure counters only on successful delivery of the merged batch.

In `runtime/live-webgen-progress.py`:

- Keep `handle_delivery_failure(...)` for hard downgrade to `manual_pull` when `sessions_send` is unavailable.
- Add a helper that normalizes rebroadcast exceptions into bounded text so supervisor can persist the latest error reason even when it stays on `rebroadcast`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_live_watch_supervisor.py tests/test_live_webgen_progress.py -k "delivery_failure_metadata or rebroadcast_failure" -v`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/live-watch-supervisor.py runtime/live-webgen-progress.py tests/test_live_watch_supervisor.py tests/test_live_webgen_progress.py
git commit -m "feat: persist rebroadcast delivery failures in watch state"
```

### Task 4: Make ensure-live-watch gate on delivery freshness, not just heartbeat

**Files:**
- Modify: `runtime/ensure-live-watch.py`
- Test: `tests/test_ensure_live_watch.py`

**Step 1: Write the failing tests**

Add tests that make the contract explicit:

```python
def test_resolve_watch_action_returns_degraded_when_supervisor_alive_but_backlog_pending():
    save_watch_state(
        state_file,
        WatchState(
            watch_id="watch-demo",
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="agent:main:main",
            delivery_strategy="rebroadcast",
            status="running",
            phase="implementing",
            supervisor_heartbeat_at=100.0,
            lease_owner="worker-1",
            lease_until=130.0,
            pending_broadcast_items=[{"seq": 42, "summary": "✅ 构建成功"}],
            pending_count=1,
            last_seen_seq=42,
            last_delivered_seq=41,
        ),
    )

    payload = resolve_watch_action(..., now=110.0)
    assert payload["status"] == "degraded"
```

Add a second test where `last_seen_seq == last_delivered_seq` and no backlog exists, which should still return `active`.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ensure_live_watch.py -k "backlog_pending or delivery_freshness" -v`

Expected: FAIL because current `resolve_watch_action(...)` returns `active` whenever supervisor heartbeat and lease are fresh.

**Step 3: Write minimal implementation**

In `runtime/ensure-live-watch.py`:

- Import and use the new delivery-health helpers from `runtime/live_watch.py`.
- Return `status="degraded"` when:
  - `watch_is_delivery_degraded(state)` is true
  - or `watch_has_delivery_lag(state)` is true
- Include in payload:
  - `lastDeliveredSeq`
  - `deliveryFailureCount`
  - `lastDeliveryError`
  - `deliveryBacklogSince`
- Keep `resume` only for missing supervisor / expired lease / final delivery pending, not for mere backlog.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ensure_live_watch.py -k "backlog_pending or delivery_freshness" -v`

Expected: PASS

**Step 5: Commit**

```bash
git add runtime/ensure-live-watch.py tests/test_ensure_live_watch.py
git commit -m "fix: report degraded watch when delivery lags behind collection"
```

### Task 5: Lock the end-to-end rebroadcast contract

**Files:**
- Modify: `tests/test_live_watch_supervisor.py`
- Modify: `tests/test_ensure_live_watch.py`
- Modify: `tests/test_webgen_live_broadcast_contract.py`

**Step 1: Write the failing tests**

Add an end-to-end regression case covering the real outage:

```python
def test_watch_is_not_reported_active_when_collection_alive_but_origin_repush_is_stuck():
    # saved state has fresh supervisor heartbeat, fresh lease,
    # advanced last_seen_seq, stale last_delivered_seq, and queued backlog
    ...
    payload = resolve_watch_action(...)
    assert payload["status"] == "degraded"
```

Add a contract test asserting the migration docs and AGENTS contract still point normal recovery to `prepare-webgen-live-watch.py` / `ensure-live-watch.py`, not cron.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_watch_supervisor.py tests/test_ensure_live_watch.py tests/test_webgen_live_broadcast_contract.py -v`

Expected: FAIL until the degraded-vs-active contract is consistent across runtime and docs-facing tests.

**Step 3: Write minimal implementation**

- Update any mismatched test fixtures or helper payloads so they include new delivery-health fields.
- Ensure the public contract is:
  - collection alive + delivery healthy -> `active`
  - collection alive + delivery lag/failure -> `degraded`
  - no supervisor / expired lease -> `resume`

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_live_watch_supervisor.py tests/test_ensure_live_watch.py tests/test_webgen_live_broadcast_contract.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_live_watch_supervisor.py tests/test_ensure_live_watch.py tests/test_webgen_live_broadcast_contract.py
git commit -m "test: lock degraded rebroadcast contract"
```

### Task 6: Run the full verification sweep

**Files:**
- Verify: `runtime/live_watch.py`
- Verify: `runtime/live-watch-supervisor.py`
- Verify: `runtime/live-webgen-progress.py`
- Verify: `runtime/ensure-live-watch.py`
- Verify: `tests/test_live_watch.py`
- Verify: `tests/test_live_watch_supervisor.py`
- Verify: `tests/test_live_webgen_progress.py`
- Verify: `tests/test_ensure_live_watch.py`
- Verify: `tests/test_webgen_live_broadcast_contract.py`

**Step 1: Run the focused runtime test suite**

Run:

```bash
python3 -m pytest \
  tests/test_live_watch.py \
  tests/test_live_watch_supervisor.py \
  tests/test_live_webgen_progress.py \
  tests/test_ensure_live_watch.py \
  tests/test_webgen_live_broadcast_contract.py -v
```

Expected: PASS

**Step 2: Run a manual spot-check of ensure output**

Run:

```bash
python3 runtime/ensure-live-watch.py --session-key agent:webgen:proj-demo --json
```

Expected:

- returns `start` if no state exists
- returns `degraded` instead of `active` for a state with stale delivery
- includes `lastDeliveredSeq` and delivery failure fields in the JSON payload

**Step 3: Inspect no-doc-regression search**

Run:

```bash
rg -n "degraded|delivery lag|lastDeliveredSeq|prepare-webgen-live-watch|ensure-live-watch" \
  AGENTS.md skills/delegated-live-broadcasting/SKILL.md docs/webgen-live-broadcast-migration.md runtime tests
```

Expected: runtime/tests mention the new degraded contract, and existing docs still point recovery to `prepare` / `ensure`.

**Step 4: Commit**

```bash
git add runtime/live_watch.py runtime/live-watch-supervisor.py runtime/live-webgen-progress.py runtime/ensure-live-watch.py \
  tests/test_live_watch.py tests/test_live_watch_supervisor.py tests/test_live_webgen_progress.py tests/test_ensure_live_watch.py \
  tests/test_webgen_live_broadcast_contract.py docs/plans/2026-06-20-webgen-rebroadcast-reliability.md
git commit -m "fix: harden webgen live rebroadcast reliability"
```

## Notes for Implementation

- Do not change deterministic resume, project `sessionKey`, or the `prepare-webgen-live-watch.py` bridge semantics.
- Do not reintroduce cron as a primary recovery path.
- Do not let `supervisor_heartbeat_at` alone define health.
- Treat `pending_broadcast_items` as a durable delivery queue, not a passive debug snapshot.
- Preserve backward compatibility for existing watch state files missing new fields.
