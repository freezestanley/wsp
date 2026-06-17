# WebGen Hidden Wake + Silent Context Nudge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make delegated WebGen polling and context-protection logic user-invisible by adding hidden wake semantics, silent context nudges, and visible-only-on-real-progress output rules.

**Architecture:** Split the work into two layers. The workspace layer adds watch-state fields, context-band decision helpers, and hidden-control message policy. The runtime layer adds hidden wake delivery, suppresses cron/time wrappers for hidden turns, and only emits user-visible output when the wake turn produced real progress. Keep the existing project identity, deterministic resume, and single active project session model unchanged.

**Tech Stack:** Python 3 runtime helpers, AGENTS/skill prompt rules, markdown docs, OpenClaw runtime wake/session delivery pipeline

---

### Task 1: Document the target behavior and boundaries

**Files:**
- Create: `docs/plans/2026-06-17-webgen-hidden-wake-context-nudge-design.md`
- Modify: `docs/webgen-live-broadcast-migration.md`
- Modify: `AGENTS.md`
- Modify: `skills/delegated-live-broadcasting/SKILL.md`

**Step 1: Write the design rules**

Document:
- users must not see `[cron:...]`, `Current time`, `Reference UTC`
- silent context nudges are internal control-plane actions
- no session rollover / no `slug -> sessionKey` remap
- visible output only when there is real new progress

**Step 2: Verify the rules are discoverable**

Run:
- `rg -n "hidden wake|silent|context nudge|Current time|Reference UTC|session rollover|slug -> sessionKey" AGENTS.md skills/delegated-live-broadcasting/SKILL.md docs/webgen-live-broadcast-migration.md docs/plans/2026-06-17-webgen-hidden-wake-context-nudge-design.md`

Expected: the new behavior and non-goals are explicitly documented.

### Task 2: Add failing tests for context-nudge decision logic

**Files:**
- Create: `tests/test_hidden_context_nudge.py`
- Modify: `runtime/live_watch.py`
- Test: `tests/test_hidden_context_nudge.py`

**Step 1: Write the failing tests**

Cover:
- `ok -> warn` can trigger a single nudge
- repeating the same band inside cooldown does not re-nudge
- `warn -> compact` triggers a stronger nudge
- ack detection clears `awaiting_context_ack`
- no user-visible broadcast is produced for silent nudge only

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_hidden_context_nudge -v`

Expected: FAIL because the helpers and fields do not exist yet.

**Step 3: Write minimal implementation**

Implement only the new watch-state fields and minimal decision helpers needed by the tests.

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_hidden_context_nudge -v`

Expected: PASS.

### Task 3: Extend watch state for silent wake and context governance

**Files:**
- Modify: `runtime/live_watch.py`
- Modify: `tests/test_live_watch.py`

**Step 1: Write the failing test**

Add tests for:
- watch state round-trip with `last_context_band`
- storing `last_context_nudge_at`
- `awaiting_context_ack` transitions
- silent-only cycles produce no broadcast batch

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_live_watch -v`

Expected: FAIL on missing fields or behavior.

**Step 3: Write minimal implementation**

Update:
- `WatchState`
- load/save round-trip
- batch builder logic

so silent control cycles remain invisible to the user.

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_live_watch -v`

Expected: PASS.

### Task 4: Add context-band helpers and nudge message builder

**Files:**
- Modify: `runtime/context_stopgap.py`
- Create: `runtime/context_nudge.py`
- Test: `tests/test_hidden_context_nudge.py`

**Step 1: Write the failing test**

Add tests for:
- `<80% -> ok`
- `>=80% -> warn`
- `>=85% -> compact`
- `>=92% -> force-compact`
- control message text is short and stable

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_hidden_context_nudge -v`

Expected: FAIL because the band helper or message builder is incomplete.

**Step 3: Write minimal implementation**

Implement:
- normalized band helper
- cooldown check
- message builder for hidden control delivery

**Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_hidden_context_nudge -v`

Expected: PASS.

### Task 5: Wire watcher tooling to evaluate silent nudges

**Files:**
- Modify: `runtime/live-webgen-progress.py`
- Modify: `runtime/watch-session-history.py`
- Modify: `docs/webgen-live-broadcast-migration.md`

**Step 1: Write the failing test**

Add or extend tests so a cycle with:
- no new progress
- upgraded context band
- sent silent nudge

results in:
- no visible batch
- updated watch state

**Step 2: Run test to verify it fails**

Run:
- `python3 -m unittest tests.test_hidden_context_nudge -v`
- `python3 -m unittest tests.test_live_watch -v`

Expected: FAIL until the watcher flow records the silent action correctly.

**Step 3: Write minimal implementation**

Wire the cycle so it can:
- evaluate context risk
- decide whether to send a hidden control nudge
- keep the cycle user-silent unless real progress exists

**Step 4: Run test to verify it passes**

Run:
- `python3 -m unittest tests.test_hidden_context_nudge -v`
- `python3 -m unittest tests.test_live_watch -v`

Expected: PASS.

### Task 6: Define the runtime hidden wake contract

**Files:**
- Modify: `docs/webgen-live-broadcast-migration.md`
- Modify: `docs/plans/2026-06-17-webgen-hidden-wake-context-nudge-design.md`

**Step 1: Write the runtime contract**

Specify:
- hidden wake payload shape
- suppression of `[cron:...]`, `Current time`, `Reference UTC`
- hidden `sessions_send` control path
- silent wake completion semantics

**Step 2: Verify docs are explicit**

Run:
- `rg -n "hidden wake|delivery.mode|Current time|Reference UTC|silent completion|hidden sessions_send" docs/webgen-live-broadcast-migration.md docs/plans/2026-06-17-webgen-hidden-wake-context-nudge-design.md`

Expected: the runtime work is precise enough for a separate implementation owner.

### Task 7: Verify and hand off

**Files:**
- Verify only

**Step 1: Run focused tests**

Run:
- `python3 -m unittest tests.test_hidden_context_nudge -v`
- `python3 -m unittest tests.test_live_watch -v`
- `python3 -m unittest tests.test_context_stopgap -v`

Expected: PASS.

**Step 2: Smoke-check helper behavior**

Run:
- `python3 -c "from runtime.context_nudge import context_band_from_ratio; print(context_band_from_ratio(0.86))"`
- `python3 -c "from runtime.context_nudge import build_context_nudge_message; print(build_context_nudge_message('compact'))"`

Expected:
- first command prints `compact`
- second command prints a short internal-control message

**Step 3: Commit**

```bash
git add AGENTS.md skills/delegated-live-broadcasting/SKILL.md docs/webgen-live-broadcast-migration.md docs/plans/2026-06-17-webgen-hidden-wake-context-nudge-design.md docs/plans/2026-06-17-webgen-hidden-wake-context-nudge.md runtime/live_watch.py runtime/live-webgen-progress.py runtime/watch-session-history.py runtime/context_stopgap.py runtime/context_nudge.py tests/test_live_watch.py tests/test_hidden_context_nudge.py tests/test_context_stopgap.py
git commit -m "feat: add hidden wake context nudge design"
```
