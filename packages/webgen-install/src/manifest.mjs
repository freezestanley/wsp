import { readdir } from "node:fs/promises";
import { join, relative } from "node:path";
import { normalizeRelativePath, uniqueSorted } from "./utils.mjs";

const ALLOWED_EXACT = new Set([
  "workspace/.gitignore",
  "workspace/AGENTS.md",
  "workspace/HEARTBEAT.md",
  "workspace/IDENTITY.md",
  "workspace/MEMORY.md",
  "workspace/SOUL.md",
  "workspace/TOOLS.md",
  "workspace/USER.md",
  "workspace/skills-lock.json",
  "workspace/.agents/skills/design-taste-frontend/SKILL.md",
]);

const ALLOWED_PREFIXES = [
  "workspace/demos/",
  "workspace/docs/",
  "workspace/install/",
  "workspace/memory/",
  "workspace/scripts/",
  "workspace/skills/",
  "workspace/templates/",
  "workspace/tests/",
];

const BLOCKED_PREFIXES = [
  "sessions/",
  "workspace/.clawhub/",
  "workspace/.git/",
  "workspace/.openclaw/",
  "workspace/.remember/",
  "workspace/projects/",
];

const MAIN_WORKSPACE_ALLOWED_EXACT = new Set([
  "AGENTS.md",
]);

const MAIN_WORKSPACE_ALLOWED_PREFIXES = [
  "runtime/",
  "skills/webgen/",
  "skills/delegated-live-broadcasting/",
];

export function shouldIncludeRelativePath(value) {
  const normalized = normalizeRelativePath(value);
  if (!normalized || normalized.endsWith("/")) {
    return false;
  }
  if (normalized.endsWith(".DS_Store")) {
    return false;
  }
  if (BLOCKED_PREFIXES.some((prefix) => normalized.startsWith(prefix))) {
    return false;
  }
  if (ALLOWED_EXACT.has(normalized)) {
    return true;
  }
  return ALLOWED_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

export function shouldIncludeMainWorkspacePath(value) {
  const normalized = normalizeRelativePath(value);
  if (!normalized || normalized.endsWith("/")) {
    return false;
  }
  if (normalized.endsWith(".DS_Store")) {
    return false;
  }
  if (normalized.includes("/__pycache__/") || normalized.endsWith(".pyc")) {
    return false;
  }
  if (MAIN_WORKSPACE_ALLOWED_EXACT.has(normalized)) {
    return true;
  }
  return MAIN_WORKSPACE_ALLOWED_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

export function shouldTraverseDirectory(value) {
  const normalized = normalizeRelativePath(value).replace(/\/?$/, "/");
  if (normalized === "./") {
    return true;
  }
  if (BLOCKED_PREFIXES.some((prefix) => normalized.startsWith(prefix))) {
    return false;
  }
  if (
    normalized === "agent/" ||
    normalized === "workspace/" ||
    normalized === "workspace/.agents/" ||
    normalized === "workspace/.agents/skills/" ||
    ALLOWED_PREFIXES.some((prefix) => prefix.startsWith(normalized)) ||
    ALLOWED_PREFIXES.some((prefix) => normalized.startsWith(prefix)) ||
    [...ALLOWED_EXACT].some((entry) => entry.startsWith(normalized))
  ) {
    return true;
  }
  return false;
}

async function walkFiles(rootDir, currentDir, results) {
  const entries = await readdir(currentDir, { withFileTypes: true });
  for (const entry of entries) {
    const absolutePath = join(currentDir, entry.name);
    const relativePath = normalizeRelativePath(relative(rootDir, absolutePath));
    if (entry.isDirectory()) {
      if (shouldTraverseDirectory(relativePath)) {
        await walkFiles(rootDir, absolutePath, results);
      }
      continue;
    }
    if (entry.isFile() && shouldIncludeRelativePath(relativePath)) {
      results.push(relativePath);
    }
  }
}

export async function collectPayloadEntries(sourceRoot) {
  const results = [];
  await walkFiles(sourceRoot, sourceRoot, results);
  return uniqueSorted(results);
}
