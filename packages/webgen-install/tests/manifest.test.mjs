import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

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
    mod.shouldIncludeRelativePath("workspace/config.js"),
    true,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/release-notes.md"),
    true,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/.env"),
    false,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/install/pkg/node_modules/react/index.js"),
    false,
  );
  assert.equal(
    mod.shouldIncludeRelativePath("workspace/install/pkg/__pycache__/tool.cpython-313.pyc"),
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
    mod.shouldIncludeMainWorkspacePath("runtime/ensure-live-watch.py"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("runtime/prepare-webgen-live-watch.py"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("runtime/live-watch-supervisor.py"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("runtime/rechain-watch.py"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("runtime/rechain-watch-once.py"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("runtime/session_file_watch.py"),
    true,
  );
  assert.equal(
    mod.shouldIncludeMainWorkspacePath("runtime/session_origin.py"),
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

test("collectPayloadEntries includes allowed top-level files and symlinked assets", async () => {
  const mod = await import("../src/manifest.mjs");
  const sourceRoot = await mkdtemp(join(tmpdir(), "webgen-manifest-"));
  const gsapDir = join(sourceRoot, "workspace", "install", "gsap-skills-main");
  const nodeModulesDir = join(sourceRoot, "workspace", "install", "pkg", "node_modules", "react");
  const pycacheDir = join(sourceRoot, "workspace", "install", "pkg", "__pycache__");

  await mkdir(gsapDir, { recursive: true });
  await mkdir(nodeModulesDir, { recursive: true });
  await mkdir(pycacheDir, { recursive: true });
  await writeFile(join(sourceRoot, "workspace", "config.js"), "module.exports = {};\n", "utf8");
  await writeFile(join(sourceRoot, "workspace", "release-notes.md"), "# release\n", "utf8");
  await writeFile(join(gsapDir, "AGENTS.md"), "# gsap\n", "utf8");
  await writeFile(join(nodeModulesDir, "index.js"), "export {};\n", "utf8");
  await writeFile(join(pycacheDir, "tool.cpython-313.pyc"), "pyc\n", "utf8");
  await symlink("AGENTS.md", join(gsapDir, "CLAUDE.md"));
  await symlink("AGENTS.md", join(gsapDir, "GEMINI.md"));

  const entries = await mod.collectPayloadEntries(sourceRoot);

  assert.equal(entries.includes("workspace/config.js"), true);
  assert.equal(entries.includes("workspace/release-notes.md"), true);
  assert.equal(entries.includes("workspace/install/gsap-skills-main/CLAUDE.md"), true);
  assert.equal(entries.includes("workspace/install/gsap-skills-main/GEMINI.md"), true);
  assert.equal(entries.includes("workspace/install/pkg/node_modules/react/index.js"), false);
  assert.equal(entries.includes("workspace/install/pkg/__pycache__/tool.cpython-313.pyc"), false);
});
