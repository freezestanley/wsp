# WebGen Context Stopgap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop WebGen sessions from blowing past context limits without changing the existing `project -> sessionKey` binding model or the deterministic resume flow.

**Architecture:** Keep the current single active project-session semantics intact. Reduce transcript growth by (1) triggering compaction much earlier, (2) truncating oversized `read`/`exec` tool payloads before they land in history, and (3) enforcing Discovery-stage partial reads plus structured summaries instead of full-file dumps. Do not introduce session rollover or active-session remapping in this phase.

**Tech Stack:** Python 3 runtime helpers, shell/tool policy updates, markdown docs, AGENTS/skill rules

---

### Task 1: Document the non-goal and invariants

**Files:**
- Create: `docs/plans/2026-06-17-webgen-context-stopgap.md`
- Modify: `skills/webgen/SKILL.md`

**Step 1: Write the invariant explicitly**

Document that this phase does **not** change:
- `slug` as the project identity
- deterministic resume via existing `sessionKey`
- single active project session semantics
- session-lock ownership model

**Step 2: Verify the rule is visible**

Run: `rg -n "resume|sessionKey|project session|single active" skills/webgen/SKILL.md runtime/webgen_resume_resolver.py`

Expected: the no-rollover boundary is discoverable.

### Task 2: Add failing tests for transcript-growth controls

**Files:**
- Create: `tests/test_context_stopgap.py`
- Test: `tests/test_context_stopgap.py`

**Step 1: Write failing tests**

Cover:
- large tool output is truncated to a bounded head/tail representation
- transcript classifier marks oversized `read`/`exec` payloads as summarized
- Discovery summary extractor keeps only required fields from `DISCOVERY.md`
- compaction threshold policy reports `warn`, `compact`, `hard-stop` bands

**Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_context_stopgap -v`

Expected: FAIL because stopgap helpers do not exist yet.

### Task 3: Implement tool-output truncation helpers

**Files:**
- Create: `runtime/context_stopgap.py`
- Modify: `runtime/watch-session-history.py`
- Modify: `runtime/live-webgen-progress.py`

**Step 1: Add bounded output helpers**

Implement:
- `truncate_tool_output(text, max_lines, max_bytes, head_lines, tail_lines)`
- return structured metadata:
  - `text`
  - `truncated`
  - `dropped_lines`
  - `dropped_bytes`

**Step 2: Use truncation in watcher tooling**

Watcher scripts should:
- keep summaries concise
- never emit full oversized raw payloads by default
- preserve enough head/tail context for debugging

**Step 3: Verify tests**

Run: `python3 -m unittest tests.test_context_stopgap -v`

Expected: PASS for truncation behavior.

### Task 4: Implement Discovery partial-read extraction

**Files:**
- Create: `runtime/discovery_extract.py`
- Modify: `skills/webgen/SKILL.md`

**Step 1: Add field extractor**

Implement a helper that extracts only:
- `Design Read`
- `DESIGN_VARIANCE`
- `MOTION_INTENSITY`
- `VISUAL_DENSITY`
- device adaptation bullets

from a `DISCOVERY.md`-like document.

**Step 2: Update WebGen guidance**

Document that Discovery must prefer:
- `rg` for field location
- `sed -n` for narrow windows
- structured extraction

and must avoid whole-document dumps into transcript.

**Step 3: Verify tests**

Run: `python3 -m unittest tests.test_context_stopgap -v`

Expected: PASS for extraction behavior.

### Task 5: Add explicit compaction threshold policy helpers

**Files:**
- Modify: `runtime/context_stopgap.py`
- Modify: `docs/webgen-live-broadcast-migration.md`

**Step 1: Encode threshold bands**

Implement a small helper:
- `<120k` → `ok`
- `>=120k` → `warn`
- `>=140k` → `compact`
- `>=160k` → `hard-stop`

This helper only reports policy in the workspace layer; it does not mutate upstream runtime behavior by itself.

**Step 2: Document that runtime must wire it in**

Document that upstream runtime should:
- compact before `140k`
- refuse further large transcript growth at `160k`

without changing project/session identity.

### Task 6: Verify and hand off

**Files:**
- Verify only

**Step 1: Run focused tests**

Run:
- `python3 -m unittest tests.test_context_stopgap -v`
- `python3 -m unittest tests.test_live_watch -q`

Expected: PASS

**Step 2: Smoke-check helper outputs**

Run:
- `python3 -c "from runtime.context_stopgap import truncate_tool_output; ..."`
- `python3 -c "from runtime.discovery_extract import extract_discovery_summary; ..."`

Expected: bounded outputs and extracted summaries only.

**Step 3: Commit**

```bash
git add docs/plans/2026-06-17-webgen-context-stopgap.md skills/webgen/SKILL.md runtime/context_stopgap.py runtime/discovery_extract.py runtime/live-webgen-progress.py runtime/watch-session-history.py docs/webgen-live-broadcast-migration.md tests/test_context_stopgap.py
git commit -m "fix: add webgen context stopgap controls"
```
