import test from "node:test";
import assert from "node:assert/strict";

test("install plan targets agents/webgen and patches required config", async () => {
  const mod = await import("../src/install-webgen.mjs");
  const plan = mod.createInstallPlan({
    stateDir: "/tmp/openclaw-state",
  });

  assert.equal(plan.extractDir, "/tmp/openclaw-state/agents/webgen");
  assert.equal(plan.agent.id, "webgen");
  assert.equal(plan.agent.workspace, "/tmp/openclaw-state/agents/webgen/workspace");
  assert.equal(plan.agent.agentDir, "/tmp/openclaw-state/agents/webgen/agent");
  assert.equal(plan.agent.model, "gpt5.5");
  assert.equal(plan.config.agentToAgentEnabled, true);
  assert.equal(plan.config.sessionsVisibility, "all");
  assert.deepEqual(plan.config.mainAllowAgents, ["webgen"]);
  assert.deepEqual(plan.config.webgenAllowAgents, ["webgen"]);
});

test("install plan accepts explicit model override", async () => {
  const mod = await import("../src/install-webgen.mjs");
  const plan = mod.createInstallPlan({
    stateDir: "/tmp/openclaw-state",
    model: "custom/provider-model",
  });

  assert.equal(plan.agent.model, "custom/provider-model");
});
