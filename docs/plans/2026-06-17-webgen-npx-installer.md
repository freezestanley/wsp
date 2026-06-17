# WebGen NPX Installer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a local `npx` installer package that bundles the current `webgen` agent as a clean payload, installs it into another OpenClaw state directory, patches required config, and verifies the result.

**Architecture:** Keep the installer dependency-light and rely on the stable OpenClaw CLI for agent registration and config mutation. Build the payload from a whitelist manifest so the package captures current workspace changes without carrying runtime garbage such as sessions, projects, local registries, or Git history.

**Tech Stack:** Node.js ESM, built-in `node:test`, OpenClaw CLI, shell `zip`/`unzip` utilities available on the host.

---

### Task 1: Create the installer package skeleton

**Files:**
- Create: `workspace/packages/webgen-install/package.json`
- Create: `workspace/packages/webgen-install/README.md`
- Create: `workspace/packages/webgen-install/bin/openclaw-webgen-install.mjs`
- Create: `workspace/packages/webgen-install/src/cli.mjs`

**Step 1: Write the failing test**

Create a package-level smoke test asserting the CLI module exports a command surface that recognizes `build`, `install`, and `verify`.

**Step 2: Run test to verify it fails**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: FAIL because the package files do not exist yet.

**Step 3: Write minimal implementation**

Add package metadata, a bin entry, and a minimal CLI parser.

**Step 4: Run test to verify it passes**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: PASS for the CLI surface test.

### Task 2: Add payload whitelist logic

**Files:**
- Create: `workspace/packages/webgen-install/src/manifest.mjs`
- Create: `workspace/packages/webgen-install/tests/manifest.test.mjs`

**Step 1: Write the failing test**

Add tests that assert:

- `agents/webgen/sessions/...` is excluded
- `agents/webgen/workspace/projects/...` is excluded
- `agents/webgen/workspace/skills/webgen/SKILL.md` is included
- `agents/webgen/workspace/scripts/project-init.sh` is included

**Step 2: Run test to verify it fails**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: FAIL because the manifest logic does not exist.

**Step 3: Write minimal implementation**

Implement include/exclude matchers and an explicit payload manifest generator.

**Step 4: Run test to verify it passes**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: PASS.

### Task 3: Add install planning logic

**Files:**
- Create: `workspace/packages/webgen-install/src/install-webgen.mjs`
- Create: `workspace/packages/webgen-install/tests/install-plan.test.mjs`

**Step 1: Write the failing test**

Add tests asserting the install plan:

- extracts into `agents/webgen`
- registers agent id `webgen`
- patches required config keys

**Step 2: Run test to verify it fails**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: FAIL because the planner does not exist.

**Step 3: Write minimal implementation**

Implement pure planning helpers and command builders.

**Step 4: Run test to verify it passes**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: PASS.

### Task 4: Implement payload build

**Files:**
- Create: `workspace/packages/webgen-install/src/build-payload.mjs`
- Create: `workspace/packages/webgen-install/payload/.gitkeep`

**Step 1: Write the failing test**

Add a test asserting the build module can produce a payload manifest JSON from the current source tree.

**Step 2: Run test to verify it fails**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: FAIL because the build module does not exist.

**Step 3: Write minimal implementation**

Implement staging, whitelist copy, manifest emission, and `zip` creation.

**Step 4: Run test to verify it passes**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: PASS.

### Task 5: Implement install and verify commands

**Files:**
- Modify: `workspace/packages/webgen-install/src/cli.mjs`
- Create: `workspace/packages/webgen-install/src/verify-install.mjs`

**Step 1: Write the failing test**

Add tests covering command construction for:

- `openclaw agents add`
- `openclaw agents set-identity`
- config patch operations

**Step 2: Run test to verify it fails**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: FAIL because those command builders are incomplete.

**Step 3: Write minimal implementation**

Implement the command dispatchers and verification checks.

**Step 4: Run test to verify it passes**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: PASS.

### Task 6: Build the package and copy it to Desktop

**Files:**
- Generate: `workspace/packages/webgen-install/payload/webgen-agent-payload.zip`
- Generate: `workspace/packages/webgen-install/payload/payload-manifest.json`
- Copy to: `/Users/za-stanlexu/Desktop/openclaw/webgen-install`

**Step 1: Build locally**

Run: `node workspace/packages/webgen-install/bin/openclaw-webgen-install.mjs build`

Expected: payload zip and manifest are generated.

**Step 2: Verify locally**

Run: `node --test workspace/packages/webgen-install/tests/*.test.mjs`

Expected: PASS.

**Step 3: Copy artifact**

Copy the package directory to the Desktop target path.

**Step 4: Verify copied artifact**

Check the Desktop target contains package files plus generated payload.

**Step 5: Commit**

```bash
git -C workspace add docs/plans/2026-06-17-webgen-npx-installer-design.md docs/plans/2026-06-17-webgen-npx-installer.md packages/webgen-install
git -C workspace commit -m "feat: add webgen npx installer package"
```
