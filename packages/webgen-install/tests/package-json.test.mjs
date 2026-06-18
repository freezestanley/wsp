import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));

test("package metadata supports npm pack distribution", async () => {
  const packageJson = JSON.parse(
    await readFile(join(packageRoot, "package.json"), "utf8"),
  );

  assert.equal(packageJson.private, false);
  assert.deepEqual(
    packageJson.files,
    [
      "README.md",
      "bin",
      "payload",
      "scripts",
      "src",
    ],
  );
  assert.equal(packageJson.scripts["build:tgz"], "npm pack --pack-destination ./dist");
});
