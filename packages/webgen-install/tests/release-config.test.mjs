import test from "node:test";
import assert from "node:assert/strict";

test("release config resolves desktop target and versioned archive name", async () => {
  const mod = await import("../src/release-config.mjs");
  const config = mod.createReleaseConfig({
    packageRoot: "/repo/workspace/packages/webgen-install",
    packageJson: {
      name: "openclaw-webgen-install",
      version: "0.1.0",
    },
  });

  assert.equal(
    config.desktopTargetDir,
    "/Users/za-stanlexu/Desktop/openclaw/webgen-install",
  );
  assert.equal(
    config.distArchivePath,
    "/repo/workspace/packages/webgen-install/dist/openclaw-webgen-install-0.1.0.zip",
  );
});
