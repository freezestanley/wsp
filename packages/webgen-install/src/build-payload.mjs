import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { collectPayloadEntries } from "./manifest.mjs";
import { stageMainWorkspaceOverlay } from "./main-workspace-overlay.mjs";
import { packageRootFromMeta, runCommand } from "./utils.mjs";

export function defaultAgentSourceRoot(packageRoot) {
  return join(packageRoot, "..", "..", "..", "agents", "webgen");
}

export function createPayloadManifest({ entries }) {
  return {
    schema: "openclaw.webgen.payload-manifest.v1",
    files: [...entries],
  };
}

export async function buildPayload({
  packageRoot,
  sourceRoot = defaultAgentSourceRoot(packageRoot),
}) {
  const payloadDir = join(packageRoot, "payload");
  const zipPath = join(payloadDir, "webgen-agent-payload.zip");
  const manifestPath = join(payloadDir, "payload-manifest.json");
  const stageParent = await mkdtemp(join(tmpdir(), "webgen-payload-"));
  const stageRoot = join(stageParent, "webgen-agent");

  try {
    await mkdir(stageRoot, { recursive: true });
    const entries = await collectPayloadEntries(sourceRoot);
    for (const entry of entries) {
      await mkdir(join(stageRoot, entry, ".."), { recursive: true });
      await cp(join(sourceRoot, entry), join(stageRoot, entry), {
        recursive: false,
        force: true,
      });
    }

    const overlay = await stageMainWorkspaceOverlay({
      packageRoot,
      stageRoot,
    });

    const manifest = createPayloadManifest({
      entries: [...entries, ...overlay.files],
    });
    await mkdir(payloadDir, { recursive: true });
    await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
    await rm(zipPath, { force: true });
    runCommand("zip", ["-qr", zipPath, "."], { cwd: stageRoot });
    return { zipPath, manifestPath, manifest };
  } finally {
    await rm(stageParent, { recursive: true, force: true });
  }
}

export async function readPayloadManifest(packageRoot = packageRootFromMeta(import.meta.url)) {
  const manifestPath = join(packageRoot, "payload", "payload-manifest.json");
  const raw = await readFile(manifestPath, "utf8");
  return JSON.parse(raw);
}
