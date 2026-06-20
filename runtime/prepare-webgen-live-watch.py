#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.webgen_resume_resolver import resolve_resume_target

EnsureResolver = Callable[..., dict[str, Any]]
ResumeResolver = Callable[[str], dict[str, Any]]


def default_ensure_resolver(**kwargs: Any) -> dict[str, Any]:
    import importlib.util

    module_path = Path(__file__).resolve().parent / "ensure-live-watch.py"
    spec = importlib.util.spec_from_file_location("ensure_live_watch_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/ensure-live-watch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.resolve_watch_action(**kwargs)


def session_key_for_slug(slug: str) -> str:
    return f"agent:webgen:proj-{slug.strip()}"


def resolve_prepared_watch(
    *,
    message: str,
    session_key: str,
    slug: str,
    origin_session_key: str,
    delivery_strategy: str,
    supports_hidden_wake: bool,
    supports_sessions_send: bool,
    state_file: str = "",
    watch_id: str = "default",
    interval: float = 5.0,
    limit: int = 30,
    max_items: int = 3,
    resume_resolver: ResumeResolver | None = None,
    ensure_resolver: EnsureResolver | None = None,
) -> dict[str, Any]:
    normalized_session_key = session_key.strip()
    normalized_slug = slug.strip()
    resolver = resume_resolver or resolve_resume_target
    ensure = ensure_resolver or default_ensure_resolver

    routing: dict[str, Any]
    target_session_key = normalized_session_key

    if normalized_session_key:
        routing = {
            "mode": "direct-session",
            "resumeMatched": False,
        }
    else:
        resume_result = resolver(message)
        if bool(resume_result.get("matched")):
            target_session_key = str(resume_result.get("sessionKey") or "").strip()
            routing = {
                "mode": str(resume_result.get("mode") or ""),
                "resumeMatched": True,
                "resume": resume_result,
            }
        elif normalized_slug:
            target_session_key = session_key_for_slug(normalized_slug)
            routing = {
                "mode": f"new:{normalized_slug}",
                "resumeMatched": False,
                "resume": resume_result,
            }
        else:
            return {
                "status": "unresolved",
                "reason": "no_target_session",
                "routing": {
                    "mode": "unresolved",
                    "resumeMatched": False,
                    "resume": resume_result,
                },
            }

    watch = ensure(
        session_key=target_session_key,
        state_file=state_file,
        watch_id=watch_id,
        origin_session_key=origin_session_key,
        delivery_strategy=delivery_strategy,
        supports_hidden_wake=supports_hidden_wake,
        supports_sessions_send=supports_sessions_send,
        interval=interval,
        limit=limit,
        max_items=max_items,
    )

    return {
        "status": "ready",
        "targetSessionKey": target_session_key,
        "routing": routing,
        "watch": watch,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="在普通用户回合统一串起 webgen resume 预检与 ensure-watch")
    parser.add_argument("--message", default="", help="原始用户消息")
    parser.add_argument("--session-key", default="", help="若已确定目标 sessionKey，可直接传入")
    parser.add_argument("--slug", default="", help="若是新项目，可显式传入 slug")
    parser.add_argument("--origin-session-key", default="", help="来源会话 sessionKey")
    parser.add_argument("--delivery-strategy", default="auto", choices=["auto", "hidden_wake", "rebroadcast", "manual_pull"])
    parser.add_argument("--supports-hidden-wake", action="store_true")
    parser.add_argument("--supports-sessions-send", action="store_true")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--watch-id", default="default")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--max-items", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = resolve_prepared_watch(
        message=args.message,
        session_key=args.session_key,
        slug=args.slug,
        origin_session_key=args.origin_session_key,
        delivery_strategy=args.delivery_strategy,
        supports_hidden_wake=args.supports_hidden_wake,
        supports_sessions_send=args.supports_sessions_send,
        state_file=args.state_file,
        watch_id=args.watch_id,
        interval=args.interval,
        limit=args.limit,
        max_items=args.max_items,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
