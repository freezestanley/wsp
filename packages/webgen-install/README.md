# openclaw-webgen-install

Local `npx`-style installer package for bundling and deploying the `webgen` agent.

This package installs two layers:

- the `agents/webgen` agent payload
- a main-workspace overlay for:
  - `workspace/runtime`
  - `workspace/skills/webgen`
  - `workspace/skills/delegated-live-broadcasting`
  - the managed WebGen delegation block inside `workspace/AGENTS.md`

## Commands

```bash
node ./bin/openclaw-webgen-install.mjs build
node ./bin/openclaw-webgen-install.mjs install --state-dir ~/.openclaw
node ./bin/openclaw-webgen-install.mjs install --state-dir ~/.openclaw --model gpt5.5
node ./bin/openclaw-webgen-install.mjs verify --state-dir ~/.openclaw
bash ./scripts/build-release.sh
```

## Notes

- `build` creates `payload/webgen-agent-payload.zip`
- `install` extracts the payload and registers the agent
- `verify` checks files, host config, and main-workspace overlay installation
- `bash ./scripts/build-release.sh` runs tests, rebuilds payload, refreshes the Desktop package, and writes `dist/openclaw-webgen-install-<version>.zip`

## Model behavior

- The installer does **not** package `agents/webgen/agent/models.json`
- Default installed model id is `gpt5.5`
- You can override it explicitly with `--model <your-model-id>`
