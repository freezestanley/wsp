import test from "node:test";
import assert from "node:assert/strict";

test("install plan targets agents/webgen and patches required config", async () => {
  const mod = await import("../src/install-webgen.mjs");
  const plan = mod.createInstallPlan({
    stateDir: "/tmp/openclaw-state",
    mainWorkspaceDir: "/tmp/openclaw-state/workspace",
  });

  assert.equal(plan.extractDir, "/tmp/openclaw-state/agents/webgen");
  assert.equal(plan.agent.id, "webgen");
  assert.equal(plan.agent.workspace, "/tmp/openclaw-state/agents/webgen/workspace");
  assert.equal(plan.agent.agentDir, "/tmp/openclaw-state/agents/webgen/agent");
  assert.equal(plan.mainWorkspaceDir, "/tmp/openclaw-state/workspace");
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
    mainWorkspaceDir: "/external/main-workspace",
  });

  assert.equal(plan.agent.model, "custom/provider-model");
  assert.equal(plan.mainWorkspaceDir, "/external/main-workspace");
});

test("resolveMainWorkspaceDir prefers explicit override and falls back to main agent workspace", async () => {
  const mod = await import("../src/install-webgen.mjs");

  assert.equal(
    mod.resolveMainWorkspaceDir({
      stateDir: "/tmp/openclaw-state",
      explicitMainWorkspaceDir: "/external/claw-workspace",
      agents: [{ id: "main", workspace: "/ignored/workspace" }],
    }),
    "/external/claw-workspace",
  );

  assert.equal(
    mod.resolveMainWorkspaceDir({
      stateDir: "/tmp/openclaw-state",
      agents: [{ id: "main", workspace: "/Users/test/claw-workspace" }],
    }),
    "/Users/test/claw-workspace",
  );

  assert.equal(
    mod.resolveMainWorkspaceDir({
      stateDir: "/tmp/openclaw-state",
      agents: [{ id: "webgen", workspace: "/tmp/openclaw-state/agents/webgen/workspace" }],
    }),
    "/tmp/openclaw-state/workspace",
  );
});
