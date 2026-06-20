#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.live_watch import load_rechain_invocation


def resolve_rechain_invocation(
    *,
    state_file: Path,
    watch_id: str,
    target_session_key: str | None = None,
) -> dict[str, Any] | None:
    return load_rechain_invocation(
        state_file=state_file,
        watch_id=watch_id,
        target_session_key=target_session_key,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 watch 状态文件恢复一条待补链的 WebGen 直播 watcher（legacy cron 兼容入口）")
    parser.add_argument("--state-file", required=True, help="watch 状态文件路径")
    parser.add_argument("--watch-id", required=True, help="watch 标识")
    parser.add_argument("--target-session-key", default=None, help="可选：target sessionKey 覆盖")
    parser.add_argument("--dry-run", action="store_true", help="只输出恢复规格，不执行")
    parser.add_argument("--json", action="store_true", help="dry-run 时输出 JSON")
    parser.add_argument("--ok-if-idle", action="store_true", help="没有待补链时返回 0，并输出 idle 状态")
    args = parser.parse_args(argv)

    invocation = resolve_rechain_invocation(
        state_file=Path(args.state_file),
        watch_id=args.watch_id,
        target_session_key=args.target_session_key,
    )
    if invocation is None:
        if args.ok_if_idle:
            if args.json:
                print(json.dumps({
                    "status": "idle",
                    "legacy": True,
                    "recommendedEntry": "runtime/ensure-live-watch.py",
                    "watchId": args.watch_id,
                    "stateFile": args.state_file,
                }, ensure_ascii=False))
            return 0
        return 2

    if args.dry_run:
        if args.json:
            print(json.dumps({
                "status": "ready",
                "legacy": True,
                "recommendedEntry": "runtime/ensure-live-watch.py",
                "watchId": args.watch_id,
                "stateFile": args.state_file,
                "invocation": invocation,
            }, ensure_ascii=False, default=str))
        else:
            print(" ".join(str(part) for part in invocation["command"]))
        return 0

    env = os.environ.copy()
    env.update(invocation.get("env", {}))
    result = subprocess.run(invocation["command"], env=env, check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
