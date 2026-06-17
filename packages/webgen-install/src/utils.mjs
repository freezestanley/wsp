import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

export function packageRootFromMeta(importMetaUrl) {
  return resolve(dirname(fileURLToPath(importMetaUrl)), "..");
}

export function normalizeRelativePath(value) {
  return value.replaceAll("\\", "/").replace(/^\.\/+/, "").replace(/\/+/g, "/");
}

export function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      args._.push(token);
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
      continue;
    }
    args[key] = next;
    i += 1;
  }
  return args;
}

export function runCommand(command, commandArgs, options = {}) {
  const result = spawnSync(command, commandArgs, {
    stdio: "pipe",
    encoding: "utf8",
    ...options,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(
      `${command} ${commandArgs.join(" ")} failed with code ${result.status}\n${result.stderr || result.stdout}`,
    );
  }
  return result.stdout.trim();
}

export function uniqueSorted(values) {
  return [...new Set(values)].sort();
}
