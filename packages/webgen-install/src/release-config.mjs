import { homedir } from "node:os";
import { join } from "node:path";

export function createReleaseConfig({
  packageRoot,
  packageJson,
  targetDirOverride,
}) {
  const desktopTargetDir =
    targetDirOverride || join(homedir(), "Desktop", "openclaw", "webgen-install");
  const distArchivePath = join(
    packageRoot,
    "dist",
    `${packageJson.name}-${packageJson.version}.zip`,
  );

  return {
    desktopTargetDir,
    distArchivePath,
  };
}
