# Webgen Resume Precheck Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `main` deterministically reuse an existing `webgen` project session before delegation when the user clearly identifies an old project.

**Architecture:** Add a small resolver in `workspace/runtime/` that inspects the user message for deterministic project identifiers, maps them to an existing `projects/<slug>`, and then asks webgen's `session-route.sh envelope resume <slug>` for the canonical `sessionKey`. Wire the rule into `workspace/AGENTS.md` and `workspace/skills/webgen/SKILL.md` so `main` prefers direct resume over creating a fresh session.

**Tech Stack:** Python 3, unittest/pytest-compatible tests, existing shell routing scripts, Markdown docs/prompts.

---

### Task 1: Lock expected resolver behavior with tests

**Files:**
- Create: `workspace/tests/test_webgen_resume_resolver.py`
- Test: `workspace/tests/test_webgen_resume_resolver.py`

**Step 1: Write the failing test**

Cover:
- explicit `projects/<slug>` path
- explicit `slug: <slug>` reference
- exact project name match when unique
- no deterministic match
- ambiguous exact project name

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_webgen_resume_resolver.py -q`
Expected: FAIL because `runtime.webgen_resume_resolver` does not exist yet.

**Step 3: Write minimal implementation**

Create the resolver module and only enough parsing/indexing logic to satisfy the tests.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_webgen_resume_resolver.py -q`
Expected: PASS.

### Task 2: Implement CLI wrapper for prompt/runtime use

**Files:**
- Create: `workspace/runtime/webgen_resume_resolver.py`
- Test: `workspace/tests/test_webgen_resume_resolver.py`

**Step 1: Write the failing test**

Add a small test that exercises the public result shape through the module API.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_webgen_resume_resolver.py -q`
Expected: FAIL on missing fields or behavior.

**Step 3: Write minimal implementation**

Implement:
- project index loading from `agents/webgen/workspace/projects`
- deterministic slug/path/project-name matching
- shell call to `agents/webgen/workspace/scripts/session-route.sh envelope resume <slug>`
- key/value stdout for CLI callers

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_webgen_resume_resolver.py -q`
Expected: PASS.

### Task 3: Update delegation rules to require pre-resume checks

**Files:**
- Modify: `workspace/AGENTS.md`
- Modify: `workspace/skills/webgen/SKILL.md`

**Step 1: Write the failing test**

No automated prompt test exists here; use the resolver tests as the guard and verify the docs mention deterministic precheck rules.

**Step 2: Write minimal implementation**

Document:
- when `main` must run the precheck
- what counts as deterministic
- when to delegate directly to resolved `sessionKey`
- when to fall back to discovery/new-project routing

**Step 3: Run verification**

Run:
- `python3 -m pytest tests/test_webgen_resume_resolver.py -q`
- `python3 -m pytest tests/test_live_watch.py -q`

Expected: PASS.
