import test from "node:test";
import assert from "node:assert/strict";

test("cli exposes build install and verify commands", async () => {
  const mod = await import("../src/cli.mjs");
  const commands = mod.listCommands();
  assert.deepEqual(commands, ["build", "install", "verify"]);
});

test("cli usage documents main workspace override", async () => {
  const mod = await import("../src/cli.mjs");
  const usage = mod.renderUsage();
  assert.match(usage, /--main-workspace <path>/);
});
