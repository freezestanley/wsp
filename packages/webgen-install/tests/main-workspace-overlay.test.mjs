import test from "node:test";
import assert from "node:assert/strict";

test("managed AGENTS section is appended with stable markers", async () => {
  const mod = await import("../src/main-workspace-overlay.mjs");
  const merged = mod.mergeManagedAgentsSection({
    currentContent: "# Existing\n",
    sectionContent: "## 🌐 建站需求 → 自动委托 WebGen(全程逐步监听)\n内容\n",
  });

  assert.match(merged, /webgen-install:main-workspace-overlay:start/);
  assert.match(merged, /webgen-install:main-workspace-overlay:end/);
  assert.match(merged, /## 🌐 建站需求 → 自动委托 WebGen/);
});

test("managed AGENTS section is replaced instead of duplicated", async () => {
  const mod = await import("../src/main-workspace-overlay.mjs");
  const once = mod.mergeManagedAgentsSection({
    currentContent: "# Existing\n",
    sectionContent: "first\n",
  });
  const twice = mod.mergeManagedAgentsSection({
    currentContent: once,
    sectionContent: "second\n",
  });

  assert.equal((twice.match(/webgen-install:main-workspace-overlay:start/g) ?? []).length, 1);
  assert.match(twice, /second/);
  assert.doesNotMatch(twice, /first/);
});
