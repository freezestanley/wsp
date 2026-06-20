# Webgen Install Release Portability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `packages/webgen-install/scripts/build-release.sh` the single entry that always generates the latest portable release package for other OpenClaw installs.

**Architecture:** Keep release assembly in `release-local.mjs`, but make its tests machine-independent and strengthen payload verification around real release contents. Treat `dist/` and generated payload outputs as build artifacts rather than versioned source, while still generating them during release.

**Tech Stack:** Node.js ESM, `node:test`, shell release script, git-tracked package sources plus ignored build artifacts.

---

### Task 1: Portable Release Config

**Files:**
- Modify: `packages/webgen-install/src/release-config.mjs`
- Modify: `packages/webgen-install/tests/release-config.test.mjs`

**Step 1: Write the failing test**

Add a test that verifies the desktop target is derived from the current home directory instead of a hard-coded username path.

**Step 2: Run test to verify it fails**

Run: `node --test ./tests/release-config.test.mjs`

**Step 3: Write minimal implementation**

Expose the default desktop target calculation as runtime-dependent logic and assert the relative suffix instead of the full absolute user-specific path.

**Step 4: Run test to verify it passes**

Run: `node --test ./tests/release-config.test.mjs`

### Task 2: Real Payload Coverage

**Files:**
- Modify: `packages/webgen-install/tests/build-payload.test.mjs`
- Modify: `packages/webgen-install/src/build-payload.mjs`

**Step 1: Write the failing test**

Add a test that builds a payload manifest with deterministic metadata and verifies newly required overlay/runtime entries are included through the real manifest creation path.

**Step 2: Run test to verify it fails**

Run: `node --test ./tests/build-payload.test.mjs`

**Step 3: Write minimal implementation**

Allow manifest creation to accept a deterministic timestamp and keep the release build path using that helper so tests can verify exact output shape.

**Step 4: Run test to verify it passes**

Run: `node --test ./tests/build-payload.test.mjs`

### Task 3: Artifact-Only Outputs

**Files:**
- Add: `packages/webgen-install/.gitignore`
- Delete: `packages/webgen-install/dist/openclaw-webgen-install-0.1.0.tgz`
- Delete: `packages/webgen-install/dist/openclaw-webgen-install-0.1.0.zip`
- Delete: `packages/webgen-install/payload/payload-manifest.json`
- Delete: `packages/webgen-install/payload/webgen-agent-payload.zip`

**Step 1: Write the failing test**

Use repo state as the failing signal: generated release outputs are currently tracked and dirty after every release run.

**Step 2: Apply minimal implementation**

Ignore generated `dist/*`, `payload/*.zip`, and `payload/payload-manifest.json`, keeping only source files like `payload/.gitkeep`.

**Step 3: Verify repo state**

Run: `git -C /Users/za-stanlexu/.openclaw/workspace status --short`
Expected: generated release outputs remain untracked/ignored instead of permanent tracked diffs.

### Task 4: End-to-End Verification

**Files:**
- Verify: `packages/webgen-install/scripts/build-release.sh`

**Step 1: Run focused tests**

Run: `node --test ./tests/release-config.test.mjs ./tests/build-payload.test.mjs`

**Step 2: Run full package tests**

Run: `node --test ./tests/*.test.mjs`

**Step 3: Run release build**

Run: `bash ./scripts/build-release.sh --target-dir /tmp/webgen-install-release-check`

**Step 4: Verify artifacts**

Check that:
- `dist/openclaw-webgen-install-<version>.zip` exists
- `dist/openclaw-webgen-install-<version>.tgz` exists
- `/tmp/webgen-install-release-check` contains the rebuilt package
- payload manifest includes latest overlay/runtime entries needed for migration
