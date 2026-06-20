#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.live_watch import (
    WatchState,
    build_rechain_invocation,
    build_watch_bootstrap,
    build_watch_invocation,
    has_active_lease,
    is_terminal_watch,
    load_watch_state,
    needs_final_delivery,
    prepare_watch_state,
    save_watch_state,
    watch_is_delivery_degraded,
)
from runtime.session_origin import discover_origin_session_key, discover_sessions_send_support


OriginSessionKeyResolver = Callable[[], str]
SupportsSessionsSendResolver = Callable[[], bool]
SUPERVISOR_HEARTBEAT_TTL_SECONDS = 30.0


def has_saved_watch_state(state_file: Path, watch_id: str) -> bool:
    if not state_file.exists():
        return False
    try:
        store = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    watches = store.get("watches")
    if not isinstance(watches, dict):
        return False
    return isinstance(watches.get(watch_id), dict)


def has_active_supervisor(
    state: WatchState,
    *,
    now: float,
    heartbeat_ttl_seconds: float = SUPERVISOR_HEARTBEAT_TTL_SECONDS,
) -> bool:
    return (
        float(state.supervisor_heartbeat_at) > 0.0
        and (float(now) - float(state.supervisor_heartbeat_at)) <= max(float(heartbeat_ttl_seconds), 1.0)
    )


def build_supervisor_invocation(
    *,
    state_file: Path,
    origin_session_key: str,
    python_bin: str = "python3",
    script_path: str = "runtime/live-watch-supervisor.py",
    debounce_ms: int = 0,
    fallback_history_interval_seconds: float | None = None,
) -> dict[str, Any]:
    command = [
        python_bin,
        script_path,
        "--state-root",
        str(state_file.parent),
    ]
    if debounce_ms > 0:
        command.extend(["--debounce-ms", str(int(debounce_ms))])
    if fallback_history_interval_seconds is not None:
        command.extend([
            "--fallback-history-interval-seconds",
            str(float(fallback_history_interval_seconds)),
        ])
    env: dict[str, str] = {}
    if origin_session_key.strip():
        env["OPENCLAW_ORIGIN_SESSION_KEY"] = origin_session_key.strip()
    return {
        "command": command,
        "env": env,
    }


def resolve_watch_action(
    *,
    session_key: str,
    state_file: Path | str | None,
    watch_id: str,
    origin_session_key: str,
    delivery_strategy: str,
    supports_hidden_wake: bool,
    supports_sessions_send: bool,
    interval: float = 5.0,
    limit: int = 30,
    max_items: int = 3,
    debounce_ms: int = 0,
    fallback_history_interval_seconds: float | None = None,
    now: float | None = None,
    origin_session_key_resolver: OriginSessionKeyResolver | None = None,
    supports_sessions_send_resolver: SupportsSessionsSendResolver | None = None,
) -> dict[str, Any]:
    normalized_session_key = session_key.strip()
    if not normalized_session_key:
        raise ValueError("session_key is required")
    effective_now = time.time() if now is None else float(now)
    effective_origin_session_key = origin_session_key.strip()
    if not effective_origin_session_key:
        origin_resolver = origin_session_key_resolver or discover_origin_session_key
        effective_origin_session_key = origin_resolver().strip()
    effective_supports_sessions_send = bool(supports_sessions_send)
    if not effective_supports_sessions_send:
        supports_resolver = supports_sessions_send_resolver or discover_sessions_send_support
        effective_supports_sessions_send = bool(supports_resolver())

    effective_watch_id = "" if watch_id == "default" else watch_id
    bootstrap = build_watch_bootstrap(
        target_session_key=normalized_session_key,
        origin_session_key=effective_origin_session_key,
        requested_strategy=delivery_strategy,
        supports_hidden_wake=supports_hidden_wake,
        supports_sessions_send=effective_supports_sessions_send,
        watch_id=effective_watch_id,
    )
    if state_file:
        bootstrap["state_file"] = Path(state_file)

    resolved_state_file = Path(bootstrap["state_file"])
    resolved_watch_id = str(bootstrap["watch_id"])
    base_payload = {
        "watchId": resolved_watch_id,
        "stateFile": str(resolved_state_file),
        "targetSessionKey": str(bootstrap["target_session_key"]),
        "originSessionKey": str(bootstrap["origin_session_key"]),
        "deliveryStrategy": str(bootstrap["delivery_strategy"]),
    }

    if has_saved_watch_state(resolved_state_file, resolved_watch_id):
        state = load_watch_state(
            resolved_state_file,
            resolved_watch_id,
            target_session_key=normalized_session_key,
        )
        state = prepare_watch_state(
            state,
            target_session_key=normalized_session_key,
            origin_session_key=str(bootstrap["origin_session_key"]),
            requested_strategy=str(bootstrap["delivery_strategy"]),
            supports_hidden_wake=supports_hidden_wake,
            supports_sessions_send=effective_supports_sessions_send,
        )
        active_payload = {
            **base_payload,
            "phase": state.phase,
            "statusValue": state.status,
            "lastSeenSeq": state.last_seen_seq,
            "lastBroadcastSeq": state.last_broadcast_seq,
            "lastDeliveredSeq": state.last_delivered_seq,
            "deliveryFailureCount": state.delivery_failure_count,
            "deliveryBacklogSince": state.delivery_backlog_since,
            "lastDeliveryError": state.last_delivery_error,
            "pendingCount": state.pending_count,
            "lastPendingSummary": state.last_pending_summary,
        }
        if state.needs_rechain:
            invocation = build_rechain_invocation(
                state,
                state_file=resolved_state_file,
                interval=interval,
                limit=limit,
                max_items=max_items,
                debounce_ms=debounce_ms,
                fallback_history_interval_seconds=fallback_history_interval_seconds,
            )
            return {
                **active_payload,
                "status": "resume",
                "reason": state.rechain_reason,
                "invocation": invocation,
            }
        if needs_final_delivery(state):
            return {
                **active_payload,
                "status": "resume",
                "reason": "final_delivery_pending",
                "invocation": build_watch_invocation(
                    bootstrap,
                    interval=interval,
                    limit=limit,
                    max_items=max_items,
                    debounce_ms=debounce_ms,
                    fallback_history_interval_seconds=fallback_history_interval_seconds,
                    supports_hidden_wake=str(bootstrap["delivery_strategy"]) == "hidden_wake",
                ),
            }
        if not state.target_session_key or is_terminal_watch(state):
            return {
                **active_payload,
                "status": "idle",
            }
        if not has_active_supervisor(state, now=effective_now):
            return {
                **active_payload,
                "status": "resume",
                "reason": "supervisor_inactive",
                "invocation": build_supervisor_invocation(
                    state_file=resolved_state_file,
                    origin_session_key=str(bootstrap["origin_session_key"]),
                    debounce_ms=debounce_ms,
                    fallback_history_interval_seconds=fallback_history_interval_seconds,
                ),
            }
        if watch_is_delivery_degraded(state):
            return {
                **active_payload,
                "status": "degraded",
            }
        if has_active_lease(state, now=effective_now):
            return {
                **active_payload,
                "status": "active",
            }
        return {
            **active_payload,
            "status": "resume",
            "reason": "lease_expired",
            "invocation": build_supervisor_invocation(
                state_file=resolved_state_file,
                origin_session_key=str(bootstrap["origin_session_key"]),
                debounce_ms=debounce_ms,
                fallback_history_interval_seconds=fallback_history_interval_seconds,
            ),
        }

    initial_state = prepare_watch_state(
        WatchState(
            watch_id=resolved_watch_id,
            target_session_key=normalized_session_key,
        ),
        target_session_key=normalized_session_key,
        origin_session_key=str(bootstrap["origin_session_key"]),
        requested_strategy=str(bootstrap["delivery_strategy"]),
        supports_hidden_wake=supports_hidden_wake,
        supports_sessions_send=effective_supports_sessions_send,
    )
    save_watch_state(resolved_state_file, initial_state)
    return {
        **base_payload,
        "status": "start",
        "invocation": build_supervisor_invocation(
            state_file=resolved_state_file,
            origin_session_key=str(bootstrap["origin_session_key"]),
            debounce_ms=debounce_ms,
            fallback_history_interval_seconds=fallback_history_interval_seconds,
        ),
    }


def format_text_payload(payload: dict[str, Any]) -> str:
    status = str(payload.get("status", "unknown")).upper()
    if "invocation" in payload:
        command = " ".join(str(part) for part in payload["invocation"].get("command", []))
        return f"{status} {payload['watchId']} {command}".strip()
    phase = str(payload.get("phase", "")).strip()
    if phase:
        return f"{status} {payload['watchId']} phase={phase}".strip()
    return f"{status} {payload['watchId']}".strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一解析 live watch 的 start/resume/active/idle 决策")
    parser.add_argument("--session-key", required=True, help="目标 sessionKey，例如 agent:webgen:proj-demo")
    parser.add_argument("--state-file", default="", help="可选：watch 状态文件路径")
    parser.add_argument("--watch-id", default="default", help="可选：watch 标识，默认按 sessionKey 稳定生成")
    parser.add_argument("--origin-session-key", default="", help="可选：来源会话 sessionKey")
    parser.add_argument(
        "--delivery-strategy",
        default="auto",
        choices=["auto", "hidden_wake", "rebroadcast", "manual_pull"],
        help="投递策略，默认 auto",
    )
    parser.add_argument("--supports-hidden-wake", action="store_true", help="声明当前实例支持 hidden wake")
    parser.add_argument("--supports-sessions-send", action="store_true", help="声明当前实例支持 sessions_send")
    parser.add_argument("--interval", type=float, default=5.0, help="watcher 轮询间隔秒数")
    parser.add_argument("--limit", type=int, default=30, help="watcher 每次抓取的 history 条数")
    parser.add_argument("--max-items", type=int, default=3, help="watcher 每次最多播报多少条摘要")
    parser.add_argument("--debounce-ms", type=int, default=0, help="session 文件变化后的去抖毫秒数")
    parser.add_argument(
        "--fallback-history-interval-seconds",
        type=float,
        default=None,
        help="文件无变化时的 history 兜底拉取间隔秒数",
    )
    parser.add_argument("--dry-run", action="store_true", help="兼容占位参数；当前脚本本身不执行 watcher")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    payload = resolve_watch_action(
        session_key=args.session_key,
        state_file=args.state_file,
        watch_id=args.watch_id,
        origin_session_key=args.origin_session_key,
        delivery_strategy=args.delivery_strategy,
        supports_hidden_wake=args.supports_hidden_wake,
        supports_sessions_send=args.supports_sessions_send,
        interval=args.interval,
        limit=args.limit,
        max_items=args.max_items,
        debounce_ms=args.debounce_ms,
        fallback_history_interval_seconds=args.fallback_history_interval_seconds,
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(format_text_payload(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
