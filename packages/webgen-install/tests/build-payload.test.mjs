import test from "node:test";
import assert from "node:assert/strict";

test("build payload creates a serializable manifest from the source tree", async () => {
  const mod = await import("../src/build-payload.mjs");
  const manifest = mod.createPayloadManifest({
    entries: [
      "agent/models.json",
      "workspace/skills/webgen/SKILL.md",
      "workspace/scripts/project-init.sh",
    ],
  });

  assert.equal(Array.isArray(manifest.files), true);
  assert.equal(manifest.files.length, 3);
  assert.equal(manifest.files[0], "agent/models.json");
});
