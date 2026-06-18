import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { listAgents, pathExists, resolveMainWorkspaceDir } from "./install-webgen.mjs";

export async function verifyInstall({ stateDir, openclawBin = "openclaw", mainWorkspaceDir }) {
  const agents = await listAgents({ stateDir, openclawBin });
  const resolvedMainWorkspaceDir = resolveMainWorkspaceDir({
    stateDir,
    explicitMainWorkspaceDir: mainWorkspaceDir,
    agents,
  });
  const requiredPaths = [
    join(stateDir, "agents", "webgen", "agent"),
    join(stateDir, "agents", "webgen", "workspace", "skills", "webgen", "SKILL.md"),
    join(stateDir, "agents", "webgen", "workspace", "scripts", "project-init.sh"),
    join(resolvedMainWorkspaceDir, "skills", "webgen", "SKILL.md"),
    join(resolvedMainWorkspaceDir, "skills", "delegated-live-broadcasting", "SKILL.md"),
    join(resolvedMainWorkspaceDir, "runtime", "live_watch.py"),
    join(resolvedMainWorkspaceDir, "AGENTS.md"),
  ];

  for (const pathname of requiredPaths) {
    if (!(await pathExists(pathname))) {
      throw new Error(`Missing required file: ${pathname}`);
    }
  }

  const config = JSON.parse(
    await readFile(join(stateDir, "openclaw.json"), "utf8"),
  );
  if (config.tools?.agentToAgent?.enabled !== true) {
    throw new Error("tools.agentToAgent.enabled is not true");
  }
  if (config.tools?.sessions?.visibility !== "all") {
    throw new Error('tools.sessions.visibility is not "all"');
  }

  const configAgents = config.agents?.list ?? [];
  if (!configAgents.some((agent) => agent.id === "webgen")) {
    throw new Error("webgen agent is missing from config");
  }

  const agentsContent = await readFile(join(resolvedMainWorkspaceDir, "AGENTS.md"), "utf8");
  if (!agentsContent.includes("webgen-install:main-workspace-overlay:start")) {
    throw new Error("workspace/AGENTS.md is missing the managed webgen overlay block");
  }

  return {
    ok: true,
    mainWorkspaceDir: resolvedMainWorkspaceDir,
    checkedPaths: requiredPaths,
  };
}
