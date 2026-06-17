import { join } from "node:path";
import { buildPayload } from "./build-payload.mjs";
import {
  applyConfig,
  createInstallPlan,
  extractPayload,
  registerAgent,
  syncIdentity,
} from "./install-webgen.mjs";
import { parseArgs, packageRootFromMeta } from "./utils.mjs";
import { verifyInstall } from "./verify-install.mjs";

export function listCommands() {
  return ["build", "install", "verify"];
}

function usage() {
  return `Usage:
  openclaw-webgen-install build
  openclaw-webgen-install install --state-dir <path> [--openclaw-bin openclaw]
  openclaw-webgen-install verify --state-dir <path>`;
}

export async function runCli(argv) {
  const [command] = argv;
  const args = parseArgs(argv.slice(1));
  const packageRoot = packageRootFromMeta(import.meta.url);

  if (!command || !listCommands().includes(command)) {
    process.stdout.write(`${usage()}\n`);
    if (command) {
      process.exitCode = 1;
    }
    return;
  }

  if (command === "build") {
    const result = await buildPayload({ packageRoot });
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return;
  }

  const stateDir = args["state-dir"];
  if (!stateDir || typeof stateDir !== "string") {
    throw new Error("--state-dir is required");
  }
  const openclawBin = typeof args["openclaw-bin"] === "string" ? args["openclaw-bin"] : "openclaw";

  if (command === "install") {
    const plan = createInstallPlan({
      stateDir,
      model: typeof args.model === "string" ? args.model : undefined,
    });
    const zipPath = join(packageRoot, "payload", "webgen-agent-payload.zip");
    await extractPayload({ zipPath, extractDir: plan.extractDir, stateDir });
    await registerAgent({ stateDir, openclawBin, plan });
    await syncIdentity({ stateDir, openclawBin, plan });
    await applyConfig({ stateDir, openclawBin, plan });
    const result = await verifyInstall({ stateDir });
    process.stdout.write(`${JSON.stringify({ installed: true, ...result }, null, 2)}\n`);
    return;
  }

  const result = await verifyInstall({ stateDir });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}
