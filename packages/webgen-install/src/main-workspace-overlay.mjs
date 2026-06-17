import { cp, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { join, relative } from "node:path";
import {
  shouldIncludeMainWorkspacePath,
} from "./manifest.mjs";
import { normalizeRelativePath, uniqueSorted } from "./utils.mjs";

export const OVERLAY_START_MARKER = "<!-- webgen-install:main-workspace-overlay:start -->";
export const OVERLAY_END_MARKER = "<!-- webgen-install:main-workspace-overlay:end -->";

export function defaultMainWorkspaceRoot(packageRoot) {
  return join(packageRoot, "..", "..");
}

export function mergeManagedAgentsSection({ currentContent, sectionContent }) {
  const normalizedCurrent = currentContent ?? "";
  const managedBlock = `${OVERLAY_START_MARKER}\n${sectionContent.trim()}\n${OVERLAY_END_MARKER}`;
  const blockPattern = new RegExp(
    `${OVERLAY_START_MARKER}[\\s\\S]*?${OVERLAY_END_MARKER}`,
    "m",
  );

  if (blockPattern.test(normalizedCurrent)) {
    return normalizedCurrent.replace(blockPattern, managedBlock);
  }

  const base = normalizedCurrent.trimEnd();
  if (!base) {
    return `${managedBlock}\n`;
  }
  return `${base}\n\n${managedBlock}\n`;
}

export function extractWebgenAgentsSection(content) {
  const startHeading = "## 🌐 建站需求 → 自动委托 WebGen(全程逐步监听)";
  const endHeading = "\n## Make It Yours";
  const startIndex = content.indexOf(startHeading);
  if (startIndex === -1) {
    throw new Error("Could not find webgen AGENTS section start heading in workspace/AGENTS.md");
  }
  const endIndex = content.indexOf(endHeading, startIndex);
  if (endIndex === -1) {
    return content.slice(startIndex).trim();
  }
  return content.slice(startIndex, endIndex).trim();
}

async function collectMainWorkspaceEntries(rootDir, currentDir, results) {
  const entries = await readdir(currentDir, { withFileTypes: true });
  for (const entry of entries) {
    const absolutePath = join(currentDir, entry.name);
    const relativePath = normalizeRelativePath(relative(rootDir, absolutePath));
    if (entry.isDirectory()) {
      if (
        relativePath === "skills" ||
        relativePath === "runtime" ||
        relativePath === "." ||
        relativePath === "" ||
        relativePath.startsWith("runtime/") ||
        relativePath.startsWith("skills/webgen") ||
        relativePath.startsWith("skills/delegated-live-broadcasting")
      ) {
        await collectMainWorkspaceEntries(rootDir, absolutePath, results);
      }
      continue;
    }
    if (entry.isFile() && shouldIncludeMainWorkspacePath(relativePath) && relativePath !== "AGENTS.md") {
      results.push(relativePath);
    }
  }
}

export async function collectMainWorkspaceOverlayEntries(mainWorkspaceRoot) {
  const results = [];
  await collectMainWorkspaceEntries(mainWorkspaceRoot, mainWorkspaceRoot, results);
  return uniqueSorted(results);
}

export async function stageMainWorkspaceOverlay({ packageRoot, stageRoot }) {
  const mainWorkspaceRoot = defaultMainWorkspaceRoot(packageRoot);
  const overlayRoot = join(stageRoot, "main-workspace-overlay");
  const skillsRoot = join(overlayRoot, "skills");
  await mkdir(skillsRoot, { recursive: true });

  const entries = await collectMainWorkspaceOverlayEntries(mainWorkspaceRoot);
  for (const entry of entries) {
    const destination = join(overlayRoot, entry);
    await mkdir(join(destination, ".."), { recursive: true });
    await cp(join(mainWorkspaceRoot, entry), destination, {
      recursive: false,
      force: true,
    });
  }

  const agentsPath = join(mainWorkspaceRoot, "AGENTS.md");
  const agentsContent = await readFile(agentsPath, "utf8");
  const sectionContent = extractWebgenAgentsSection(agentsContent);
  await writeFile(
    join(overlayRoot, "AGENTS.webgen-section.md"),
    `${sectionContent}\n`,
    "utf8",
  );

  return {
    overlayRoot,
    files: [
      "main-workspace-overlay/AGENTS.webgen-section.md",
      ...entries.map((entry) => `main-workspace-overlay/${entry}`),
    ],
  };
}

export async function applyMainWorkspaceOverlay({ stateDir, stageRoot }) {
  const overlayRoot = join(stageRoot, "main-workspace-overlay");
  const targetWorkspace = join(stateDir, "workspace");
  const targetSkills = join(targetWorkspace, "skills");
  await mkdir(targetSkills, { recursive: true });

  const overlayEntries = await collectMainWorkspaceOverlayEntries(overlayRoot);
  for (const entry of overlayEntries) {
    const destination = join(targetWorkspace, entry);
    await mkdir(join(destination, ".."), { recursive: true });
    await cp(join(overlayRoot, entry), destination, {
      recursive: false,
      force: true,
    });
  }

  const sectionContent = await readFile(join(overlayRoot, "AGENTS.webgen-section.md"), "utf8");
  const targetAgentsPath = join(targetWorkspace, "AGENTS.md");
  let currentAgents = "";
  try {
    currentAgents = await readFile(targetAgentsPath, "utf8");
  } catch {
    currentAgents = "";
  }
  const merged = mergeManagedAgentsSection({
    currentContent: currentAgents,
    sectionContent,
  });
  await writeFile(targetAgentsPath, merged, "utf8");
}
