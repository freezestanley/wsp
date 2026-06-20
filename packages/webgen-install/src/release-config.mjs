import { homedir } from "node:os";
import { join } from "node:path";

export function createReleaseConfig({
  packageRoot,
  packageJson,
  homeDirOverride,
  targetDirOverride,
}) {
  const desktopTargetDir =
    targetDirOverride
    || join(homeDirOverride || homedir(), "Desktop", "openclaw", "webgen-install");
  const distArchivePath = join(
    packageRoot,
    "dist",
    `${packageJson.name}-${packageJson.version}.zip`,
  );
  const distPackagePath = join(
    packageRoot,
    "dist",
    `${packageJson.name}-${packageJson.version}.tgz`,
  );

  return {
    desktopTargetDir,
    distArchivePath,
    distPackagePath,
  };
}
