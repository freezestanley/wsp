import test from "node:test";
import assert from "node:assert/strict";

test("payload manifest includes stable webgen assets and excludes runtime garbage", async () => {
  const mod = await import("../src/manifest.mjs");

  assert.equal(
    mod.shouldIncludeRelativePath("agent/models.json"),
    false,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/skills/webgen/SKILL.md"),
    true,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/scripts/project-init.sh"),
    true,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/projects/demo/index.html"),
    false,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/.openclaw/webgen-config.json"),
    false,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("sessions/example.jsonl"),
    false,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/.git/HEAD"),
    false,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/.DS_Store"),
    false,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("skills/webgen/SKILL.md"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("skills/delegated-live-broadcasting/SKILL.md"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("AGENTS.md"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("runtime/live_watch.py"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("runtime/__pycache__/live_watch.cpython-313.pyc"),
    false,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("skills/other/SKILL.md"),
    false,
  );
});
