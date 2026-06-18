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
  "workspace/config.js",
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

const BLOCKED_SEGMENTS = [
  "/__pycache__/",
  "/node_modules/",
];

const MAIN_WORKSPACE_ALLOWED_EXACT = new Set([
  "AGENTS.md",
]);

const MAIN_WORKSPACE_ALLOWED_PREFIXES = [
  "runtime/",
  "skills/webgen/",
  "skills/delegated-live-broadcasting/",
];

function isBlockedRelativePath(normalized) {
  if (!normalized || normalized.endsWith("/")) {
    return false;
  }
  if (normalized.endsWith(".DS_Store") || normalized.endsWith(".pyc")) {
    return true;
  }
  if (BLOCKED_PREFIXES.some((prefix) => normalized.startsWith(prefix))) {
    return true;
  }
  return BLOCKED_SEGMENTS.some(
    (segment) => normalized.includes(segment) || normalized.endsWith(segment.slice(1, -1)),
  );
}

function isWorkspaceRootDirectFile(normalized) {
  if (!normalized.startsWith("workspace/")) {
    return false;
  }
  const remainder = normalized.slice("workspace/".length);
  return remainder.length > 0 && !remainder.includes("/");
}

export function shouldIncludeRelativePath(value) {
  const normalized = normalizeRelativePath(value);
  if (!normalized || normalized.endsWith("/")) {
    return false;
  }
  if (isBlockedRelativePath(normalized)) {
    return false;
  }
  if (ALLOWED_EXACT.has(normalized)) {
    return true;
  }
  if (isWorkspaceRootDirectFile(normalized)) {
    const basename = normalized.slice("workspace/".length);
    return !basename.startsWith(".");
  }
  return ALLOWED_PREFIXES.some((prefix) => normalized.startsWith(prefix));
}

export function shouldIncludeMainWorkspacePath(value) {
  const normalized = normalizeRelativePath(value);
  if (!normalized || normalized.endsWith("/")) {
    return false;
  }
  if (isBlockedRelativePath(normalized)) {
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
  if (
    BLOCKED_PREFIXES.some((prefix) => normalized.startsWith(prefix)) ||
    BLOCKED_SEGMENTS.some((segment) => normalized.includes(segment))
  ) {
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
    if ((entry.isFile() || entry.isSymbolicLink()) && shouldIncludeRelativePath(relativePath)) {
      results.push(relativePath);
    }
  }
}

export async function collectPayloadEntries(sourceRoot) {
  const results = [];
  await walkFiles(sourceRoot, sourceRoot, results);
  return uniqueSorted(results);
}
