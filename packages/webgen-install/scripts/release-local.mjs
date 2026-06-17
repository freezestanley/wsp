#!/usr/bin/env node

import { cp, mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { buildPayload } from "../src/build-payload.mjs";
import { createReleaseConfig } from "../src/release-config.mjs";
import { packageRootFromMeta, runCommand } from "../src/utils.mjs";

const PACKAGE_INCLUDE_NAMES = [
  "README.md",
  "package.json",
  "bin",
  "payload",
  "scripts",
  "src",
  "tests",
];

function parseReleaseArgs(argv) {
  const args = { targetDir: null };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--target-dir") {
      args.targetDir = argv[index + 1] ?? null;
      index += 1;
    }
  }
  return args;
}

async function stageReleasePackage({ packageRoot, stageDir }) {
  const stagePackageDir = join(stageDir, "webgen-install");
  await mkdir(stagePackageDir, { recursive: true });
  for (const entry of PACKAGE_INCLUDE_NAMES) {
    await cp(join(packageRoot, entry), join(stagePackageDir, entry), {
      recursive: true,
      force: true,
    });
  }
  return stagePackageDir;
}

async function copyStageToTarget({ stagePackageDir, targetDir }) {
  await rm(targetDir, { recursive: true, force: true });
  await mkdir(join(targetDir, ".."), { recursive: true });
  await cp(stagePackageDir, targetDir, {
    recursive: true,
    force: true,
  });
}

async function createArchive({ stagePackageDir, archivePath }) {
  await mkdir(join(archivePath, ".."), { recursive: true });
  await rm(archivePath, { force: true });
  runCommand("zip", ["-qr", archivePath, "."], { cwd: stagePackageDir });
}

async function main() {
  const packageRoot = packageRootFromMeta(import.meta.url);
  const packageJson = JSON.parse(
    await readFile(join(packageRoot, "package.json"), "utf8"),
  );
  const cliArgs = parseReleaseArgs(process.argv.slice(2));
  const releaseConfig = createReleaseConfig({
    packageRoot,
    packageJson,
    targetDirOverride: cliArgs.targetDir,
  });

  runCommand("bash", ["-lc", "node --test ./tests/*.test.mjs"], {
    cwd: packageRoot,
  });
  await buildPayload({ packageRoot });

  const stageRoot = await mkdtemp(join(tmpdir(), "webgen-release-"));
  try {
    const stagePackageDir = await stageReleasePackage({
      packageRoot,
      stageDir: stageRoot,
    });
    await copyStageToTarget({
      stagePackageDir,
      targetDir: releaseConfig.desktopTargetDir,
    });
    await createArchive({
      stagePackageDir,
      archivePath: releaseConfig.distArchivePath,
    });
  } finally {
    await rm(stageRoot, { recursive: true, force: true });
  }

  process.stdout.write(
    `${JSON.stringify(
      {
        ok: true,
        targetDir: releaseConfig.desktopTargetDir,
        archivePath: releaseConfig.distArchivePath,
      },
      null,
      2,
    )}\n`,
  );
}

await main();
