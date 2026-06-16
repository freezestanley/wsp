# Live Broadcast Hidden Wake Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the visible cron prompt pattern with a hidden wake protocol, persistent watch state, and deterministic incremental progress summarization for delegated live broadcasts.

**Architecture:** The workspace implementation will add a small Python watch-state library plus tests and will update agent guidance to consume a hidden internal wake contract instead of user-visible cron text. The actual OpenClaw runtime still needs a matching hidden-delivery/session injection change outside this workspace; this plan documents that boundary explicitly.

**Tech Stack:** Python 3, pytest, markdown docs, AGENTS/skill protocol docs

---

### Task 1: Document the implementation boundary

**Files:**
- Create: `docs/plans/2026-06-16-live-broadcast-hidden-wake.md`
- Modify: `docs/webgen-live-broadcast-migration.md`

**Step 1: Write the workspace/runtime split into docs**

Describe which parts can be implemented here:
- watch state persistence
- incremental summarization
- prompt-leak filtering rules

Describe which parts still require upstream runtime changes:
- hidden wake payload delivery
- transcript filtering for internal wake events
- `sessions_history(afterSeq=...)`

**Step 2: Verify docs stay aligned**

Run: `rg -n "announce|agentTurn|继续监听任务|internalWake|hidden wake" AGENTS.md skills/delegated-live-broadcasting/SKILL.md docs/webgen-live-broadcast-migration.md`

Expected: current and new protocol references are visible and can be reconciled.

### Task 2: Add failing tests for live watch state behavior

**Files:**
- Create: `tests/test_live_watch.py`
- Test: `tests/test_live_watch.py`

**Step 1: Write the failing tests**

Cover:
- loading missing state returns defaults
- saving and loading watch state round-trips
- only messages newer than `last_seen_seq` are summarized
- cron/internal wake text is filtered from user-facing summaries
- multiple session targets do not auto-switch

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_live_watch.py -q`

Expected: FAIL because `runtime.live_watch` does not exist yet.

### Task 3: Implement the watch-state module

**Files:**
- Create: `runtime/live_watch.py`
- Modify: `runtime/live-webgen-progress.py`

**Step 1: Write minimal implementation**

Add:
- `WatchState` dataclass
- JSON store helpers
- incremental message selection
- user-facing summary extraction with internal-prompt filtering

**Step 2: Wire the progress script to use the module**

Replace ad-hoc in-memory-only handling with:
- optional state file path
- persisted `last_seen_seq`
- no auto-switch by default
- filtered summaries

**Step 3: Run tests to verify pass**

Run: `python3 -m pytest tests/test_live_watch.py -q`

Expected: PASS

### Task 4: Update protocol docs and agent rules

**Files:**
- Modify: `AGENTS.md`
- Modify: `skills/delegated-live-broadcasting/SKILL.md`
- Modify: `docs/webgen-live-broadcast-migration.md`

**Step 1: Replace visible announce guidance**

Update guidance from:
- `sessionTarget:"current" + payload.kind:"agentTurn" + delivery.mode:"announce"`

To:
- hidden/internal wake payload
- current conversation summary generated only after `sessions_history` pull

**Step 2: Add a runtime contract section**

Document required upstream changes:
- hidden `internalWake`
- transcript suppression for internal wake events
- structured wake data instead of natural-language wake prompts

### Task 5: Verify integrated behavior

**Files:**
- Verify only

**Step 1: Run focused tests**

Run: `python3 -m pytest tests/test_live_watch.py -q`

Expected: PASS

**Step 2: Run script smoke checks**

Run:
- `python3 runtime/live-webgen-progress.py agent:webgen:proj-demo --once --jsonl --state-file /tmp/live-watch-state.json`
- `python3 runtime/watch-session-history.py agent:webgen:proj-demo --once --jsonl`

Expected:
- command parses successfully
- state file support works
- no user-facing summary is produced for internal wake prompt text

**Step 3: Commit**

```bash
git add AGENTS.md skills/delegated-live-broadcasting/SKILL.md docs/webgen-live-broadcast-migration.md docs/plans/2026-06-16-live-broadcast-hidden-wake.md runtime/live_watch.py runtime/live-webgen-progress.py tests/test_live_watch.py
git commit -m "fix: harden delegated live broadcast polling"
```
