import { access, cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { constants } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { applyMainWorkspaceOverlay } from "./main-workspace-overlay.mjs";
import { runCommand } from "./utils.mjs";

export function createInstallPlan({
  stateDir,
  model = "gpt5.5",
}) {
  return {
    extractDir: join(stateDir, "agents", "webgen"),
    agent: {
      id: "webgen",
      workspace: join(stateDir, "agents", "webgen", "workspace"),
      agentDir: join(stateDir, "agents", "webgen", "agent"),
      model,
    },
    config: {
      agentToAgentEnabled: true,
      sessionsVisibility: "all",
      mainAllowAgents: ["webgen"],
      webgenAllowAgents: ["webgen"],
    },
  };
}

export async function agentExists({ stateDir, openclawBin }) {
  const output = runCommand(openclawBin, ["agents", "list", "--json"], {
    env: {
      ...process.env,
      OPENCLAW_STATE_DIR: stateDir,
    },
  });
  const agents = JSON.parse(output || "[]");
  return agents.some((agent) => agent.id === "webgen");
}

export async function extractPayload({ zipPath, extractDir, stateDir }) {
  const stageDir = await mkdtemp(join(tmpdir(), "webgen-install-stage-"));
  try {
    runCommand("unzip", ["-oq", zipPath, "-d", stageDir]);
    await mkdir(extractDir, { recursive: true });
    await mkdir(join(extractDir, "agent"), { recursive: true });
    await cp(join(stageDir, "workspace"), join(extractDir, "workspace"), {
      recursive: true,
      force: true,
    });
    await applyMainWorkspaceOverlay({ stateDir, stageRoot: stageDir });
  } finally {
    await rm(stageDir, { recursive: true, force: true });
  }
}

export async function registerAgent({ stateDir, openclawBin, plan }) {
  if (await agentExists({ stateDir, openclawBin })) {
    return;
  }
  runCommand(
    openclawBin,
    [
      "agents",
      "add",
      plan.agent.id,
      "--workspace",
      plan.agent.workspace,
      "--agent-dir",
      plan.agent.agentDir,
      "--model",
      plan.agent.model,
      "--non-interactive",
    ],
    {
      env: {
        ...process.env,
        OPENCLAW_STATE_DIR: stateDir,
      },
    },
  );
}

export async function syncIdentity({ stateDir, openclawBin, plan }) {
  runCommand(
    openclawBin,
    [
      "agents",
      "set-identity",
      "--agent",
      plan.agent.id,
      "--workspace",
      plan.agent.workspace,
      "--from-identity",
    ],
    {
      env: {
        ...process.env,
        OPENCLAW_STATE_DIR: stateDir,
      },
    },
  );
}

function ensureArrayContains(target, values) {
  const current = Array.isArray(target) ? target : [];
  const next = [...current];
  for (const value of values) {
    if (!next.includes(value)) {
      next.push(value);
    }
  }
  return next;
}

export async function applyConfig({ stateDir, openclawBin, plan }) {
  const configPath = join(stateDir, "openclaw.json");
  const config = JSON.parse(await readFile(configPath, "utf8"));

  config.tools ??= {};
  config.tools.agentToAgent ??= {};
  config.tools.agentToAgent.enabled = plan.config.agentToAgentEnabled;
  config.tools.sessions ??= {};
  config.tools.sessions.visibility = plan.config.sessionsVisibility;

  const agents = config.agents?.list ?? [];
  const mainAgent = agents.find((agent) => agent.id === "main");
  const webgenAgent = agents.find((agent) => agent.id === "webgen");

  if (mainAgent) {
    mainAgent.subagents ??= {};
    mainAgent.subagents.allowAgents = ensureArrayContains(
      mainAgent.subagents.allowAgents,
      plan.config.mainAllowAgents,
    );
  }

  if (webgenAgent) {
    webgenAgent.subagents ??= {};
    webgenAgent.subagents.allowAgents = ensureArrayContains(
      webgenAgent.subagents.allowAgents,
      plan.config.webgenAllowAgents,
    );
  }

  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
  runCommand(openclawBin, ["config", "validate"], {
    env: {
      ...process.env,
      OPENCLAW_STATE_DIR: stateDir,
    },
  });
}

export async function pathExists(pathname) {
  try {
    await access(pathname, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}
