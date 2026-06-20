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
npm pack --pack-destination ./dist
node ./bin/openclaw-webgen-install.mjs install --state-dir ~/.openclaw
node ./bin/openclaw-webgen-install.mjs install --state-dir ~/.openclaw --main-workspace ~/claw-workspace
node ./bin/openclaw-webgen-install.mjs install --state-dir ~/.openclaw --model gpt5.5
node ./bin/openclaw-webgen-install.mjs verify --state-dir ~/.openclaw
node ./bin/openclaw-webgen-install.mjs verify --state-dir ~/.openclaw --main-workspace ~/claw-workspace
bash ./scripts/build-release.sh
```

## Notes

- `build` creates `payload/webgen-agent-payload.zip`
- `npm pack --pack-destination ./dist` creates `dist/openclaw-webgen-install-<version>.tgz`
- `install` extracts the payload and registers the agent
- `verify` checks files, host config, and main-workspace overlay installation
- `--main-workspace <path>` lets you override the target main agent workspace when it is not `~/.openclaw/workspace`
- `bash ./scripts/build-release.sh` is the canonical release entry: it runs tests, rebuilds payload, refreshes the Desktop package, and writes both `dist/openclaw-webgen-install-<version>.zip` and `dist/openclaw-webgen-install-<version>.tgz`
- `dist/*`, `payload/webgen-agent-payload.zip`, and `payload/payload-manifest.json` are generated release artifacts, not source files to maintain by hand
- Installed `workspace/runtime/live_watch.py` now includes portable watcher helpers for WebGen live broadcast bootstrap:
  - `build_watch_bootstrap(...)`
  - `build_watch_invocation(...)`
- Installed `workspace/runtime/ensure-live-watch.py` provides the preferred single entry for watcher bootstrap and normal-turn rechain recovery
  - machine-friendly usage: `python3 runtime/ensure-live-watch.py --session-key agent:webgen:proj-<slug> --json`
  - returns `status: start | resume | active | idle`
- Installed `workspace/runtime/prepare-webgen-live-watch.py` provides a higher-level bridge for normal user turns
  - machine-friendly usage: `python3 runtime/prepare-webgen-live-watch.py --message "<user text>" --slug <new-slug> --json`
  - preserves deterministic resume lookup first, then calls `ensure-live-watch.py`
- Installed `workspace/runtime/rechain-watch.py` provides a thin CLI for resuming watches marked `needs_rechain`
  - legacy compatibility only; the primary path is `prepare-webgen-live-watch.py` or `ensure-live-watch.py`
  - recommended machine-friendly usage: `--ok-if-idle --dry-run --json`
- Installed `workspace/runtime/rechain-watch-once.py` is a thinner wrapper that auto-injects `--ok-if-idle`
  - legacy compatibility only

## TGZ / NPX

Local tarball install:

```bash
npm exec --yes --package ./dist/openclaw-webgen-install-0.1.0.tgz openclaw-webgen-install -- install --state-dir ~/.openclaw
```

Or if the package is later published to a registry:

```bash
npx --yes openclaw-webgen-install install --state-dir ~/.openclaw
```

## Model behavior

- The installer does **not** package `agents/webgen/agent/models.json`
- Default installed model id is `gpt5.5`
- You can override it explicitly with `--model <your-model-id>`
