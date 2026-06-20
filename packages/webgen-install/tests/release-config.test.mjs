import test from "node:test";
import assert from "node:assert/strict";

test("release config resolves desktop target from an injected home directory", async () => {
  const mod = await import("../src/release-config.mjs");
  const config = mod.createReleaseConfig({
    packageRoot: "/repo/workspace/packages/webgen-install",
    packageJson: {
      name: "openclaw-webgen-install",
      version: "0.1.0",
    },
    homeDirOverride: "/tmp/test-home",
  });

  assert.equal(
    config.desktopTargetDir,
    "/tmp/test-home/Desktop/openclaw/webgen-install",
  );
  assert.equal(
    config.distArchivePath,
    "/repo/workspace/packages/webgen-install/dist/openclaw-webgen-install-0.1.0.zip",
  );
  assert.equal(
    config.distPackagePath,
    "/repo/workspace/packages/webgen-install/dist/openclaw-webgen-install-0.1.0.tgz",
  );
});

test("release config still honors an explicit target override", async () => {
  const mod = await import("../src/release-config.mjs");
  const config = mod.createReleaseConfig({
    packageRoot: "/repo/workspace/packages/webgen-install",
    packageJson: {
      name: "openclaw-webgen-install",
      version: "0.1.0",
    },
    homeDirOverride: "/tmp/test-home",
    targetDirOverride: "/tmp/custom-target",
  });

  assert.equal(config.desktopTargetDir, "/tmp/custom-target");
});
