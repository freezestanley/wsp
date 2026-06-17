# WebGen NPX Installer Design

**Goal:** Provide a self-contained `npx` installer that can deploy the current `webgen` agent into another OpenClaw state directory with one command and an immediate verification pass.

## Problem

The current `webgen` deployment is not a single distributable unit. It is spread across:

- `agents/webgen/agent`
- `agents/webgen/workspace/{skills,scripts,templates,docs,tests,install,...}`
- host-level `openclaw.json` agent registration
- host-level routing prerequisites:
  - `tools.agentToAgent.enabled = true`
  - `tools.sessions.visibility = "all"`

Manual migration works, but it is slow and error-prone. Runtime garbage is also mixed into the source tree, including session history, generated projects, local registries, and Git metadata.

## Chosen Distribution Shape

Use an `npx` installer package instead of a skill lifecycle hook.

Reasons:

- `openclaw agents add` exists as a stable CLI surface.
- `openclaw config set` and `openclaw config patch` exist as stable CLI surfaces.
- The current OpenClaw skill install flow does not provide a clear, trusted skill `preinstall` lifecycle for arbitrary filesystem setup.
- `npx` is a better fit for "copy files, patch config, verify install".

## Package Shape

The installer lives as a standalone Node package under the local workspace and can later be published or copied elsewhere.

Proposed structure:

```text
workspace/packages/webgen-install/
  package.json
  README.md
  bin/openclaw-webgen-install.mjs
  src/
    cli.mjs
    manifest.mjs
    build-payload.mjs
    install-webgen.mjs
    verify-install.mjs
    utils.mjs
  tests/
    manifest.test.mjs
    install-plan.test.mjs
  payload/
    webgen-agent-payload.zip
    payload-manifest.json
```

## Payload Policy

Payload creation is whitelist-based.

Include:

- `agent/models.json`
- workspace root docs:
  - `AGENTS.md`
  - `HEARTBEAT.md`
  - `IDENTITY.md`
  - `MEMORY.md`
  - `SOUL.md`
  - `TOOLS.md`
  - `USER.md`
  - `.gitignore`
- workspace subtrees:
  - `skills/`
  - `scripts/`
  - `templates/`
  - `docs/`
  - `tests/`
  - `install/`
  - `memory/`
  - `demos/`
- `workspace/.agents/skills/design-taste-frontend/SKILL.md`
- `workspace/skills-lock.json`

Exclude:

- `agents/webgen/sessions/`
- `workspace/projects/`
- `workspace/.git/`
- `workspace/.openclaw/`
- `workspace/.remember/`
- `workspace/.clawhub/`
- macOS junk like `.DS_Store`
- temporary files, logs, lockfiles produced at runtime

## Installation Flow

The installer command performs these steps:

1. Resolve target OpenClaw state directory.
2. Extract `payload/webgen-agent-payload.zip` into `agents/webgen/`.
3. Run `openclaw agents add webgen ...` if the agent does not already exist.
4. Run `openclaw agents set-identity --agent webgen --workspace <...> --from-identity`.
5. Run config mutations:
   - enable `tools.agentToAgent.enabled`
   - set `tools.sessions.visibility` to `"all"`
   - ensure `main.subagents.allowAgents` includes `webgen`
   - ensure `webgen.subagents.allowAgents` includes `webgen`
6. Run verification:
   - `openclaw agents list --json`
   - confirm the `webgen` workspace path exists
   - confirm local webgen skills exist in the extracted workspace

## Verification Scope

The installer is considered successful when:

- target state has `agents/webgen/agent/models.json`
- target state has `agents/webgen/workspace/skills/webgen/SKILL.md`
- `openclaw agents list --json` includes `webgen`
- `openclaw.json` contains the required session routing settings

Optional smoke runs can be added later, but the first version should stop at static and CLI-level verification to avoid requiring model credentials during installation.

## Delivery Target

The working package is built inside the local workspace, then copied to:

`/Users/za-stanlexu/Desktop/openclaw/webgen-install`

That directory becomes the handoff artifact for review and later publication.
