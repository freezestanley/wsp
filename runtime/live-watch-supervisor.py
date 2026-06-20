#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, TextIO

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.live_watch import (
    WatchState,
    is_terminal_watch,
    load_watch_state,
    save_watch_state,
    watch_is_delivery_degraded,
)


Batch = list[dict[str, Any]]
DeliverBatchFn = Callable[[Batch], bool]
RunWatchCycleFn = Callable[..., tuple[WatchState, int, Batch, bool]]


def _load_live_webgen_progress_module():
    module_path = Path(__file__).resolve().parent / "live-webgen-progress.py"
    spec = importlib.util.spec_from_file_location("live_webgen_progress_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/live-webgen-progress.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_progress_watch_cycle(**kwargs: Any) -> tuple[WatchState, int, Batch, bool]:
    module = _load_live_webgen_progress_module()
    return module.run_watch_cycle(**kwargs)


def build_default_watch_cycle_kwargs(
    *,
    limit: int,
    max_items: int,
    heartbeat_idle_polls: int,
    heartbeat_interval_seconds: float,
    debounce_ms: int,
    fallback_history_interval_seconds: float,
) -> dict[str, Any]:
    module = _load_live_webgen_progress_module()
    cfg = module.load_config()
    url, headers = module.gateway_endpoint(cfg)
    return {
        "limit": int(limit),
        "max_items": int(max_items),
        "heartbeat_idle_polls": int(heartbeat_idle_polls),
        "heartbeat_interval_seconds": float(heartbeat_interval_seconds),
        "fallback_history_interval_seconds": float(fallback_history_interval_seconds),
        "session_file_resolver": module.resolve_session_file_path,
        "sample_session_file_fn": module.sample_session_file,
        "invoke_sessions_history_fn": (
            lambda session_key, include_tools, history_limit: module.invoke_sessions_history(
                url,
                headers,
                session_key,
                include_tools,
                history_limit,
            )
        ),
        "debounce_seconds": max(float(debounce_ms), 0.0) / 1000.0,
        "sleep_fn": time.sleep,
        "context_usage_ratio": None,
        "context_nudge_cooldown_seconds": 300.0,
    }


def build_stateful_deliver_batch_fn(
    state: WatchState,
    *,
    jsonl: bool = False,
    stream: TextIO = sys.stdout,
) -> DeliverBatchFn:
    module = _load_live_webgen_progress_module()
    cfg = module.load_config()
    url, headers = module.gateway_endpoint(cfg)

    def _deliver(batch: Batch) -> bool:
        try:
            return module.deliver_batch(
                batch,
                delivery_strategy=state.delivery_strategy,
                origin_session_key=state.origin_session_key,
                url=url,
                headers=headers,
                send_fn=module.invoke_sessions_send,
                jsonl=jsonl,
                stream=stream,
            )
        except Exception:
            return False

    return _deliver


def _max_batch_seq(batch: Batch, fallback: int) -> int:
    max_seq = fallback
    for item in batch:
        seq = item.get("seq")
        if isinstance(seq, int) and seq > max_seq:
            max_seq = seq
    return max_seq


def _merge_pending_items(existing: Batch, incoming: Batch) -> Batch:
    merged: Batch = list(existing)
    seen = {
        (
            item.get("seq"),
            str(item.get("summary", "")),
        )
        for item in merged
    }
    for item in incoming:
        key = (item.get("seq"), str(item.get("summary", "")))
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    return merged


def deliver_or_queue_batch(
    state: WatchState,
    batch: Batch,
    *,
    deliver_batch_fn: DeliverBatchFn,
) -> tuple[WatchState, bool]:
    if not batch:
        return replace(
            state,
            pending_broadcast_items=list(state.pending_broadcast_items or []),
            pending_count=len(state.pending_broadcast_items or []),
        ), False

    if watch_is_delivery_degraded(state):
        queued = _merge_pending_items(list(state.pending_broadcast_items or []), batch)
        return replace(
            state,
            status="degraded",
            pending_broadcast_items=queued,
            pending_count=len(queued),
            last_pending_summary=str(queued[-1].get("summary", "")) if queued else "",
            delivery_degraded_reason=state.delivery_degraded_reason or "manual_pull_requires_user_turn",
        ), False

    if deliver_batch_fn(batch):
        return replace(
            state,
            pending_broadcast_items=[],
            pending_count=0,
            last_pending_summary="",
            last_delivered_seq=_max_batch_seq(batch, state.last_delivered_seq),
            delivery_degraded_reason="",
        ), True

    queued = _merge_pending_items(list(state.pending_broadcast_items or []), batch)
    return replace(
        state,
        status="degraded",
        pending_broadcast_items=queued,
        pending_count=len(queued),
        last_pending_summary=str(queued[-1].get("summary", "")) if queued else "",
        delivery_degraded_reason="delivery_failed",
    ), False


def process_watch_once(
    state: WatchState,
    *,
    now: float,
    run_watch_cycle_fn: RunWatchCycleFn | None = None,
    deliver_batch_fn: DeliverBatchFn,
    **watch_cycle_kwargs: Any,
) -> tuple[WatchState, Batch, bool]:
    cycle = run_progress_watch_cycle if run_watch_cycle_fn is None else run_watch_cycle_fn
    updated_state, new_last_seen, batch, _pulled = cycle(
        watch_state=state,
        current_session_key=state.target_session_key,
        last_seen=state.last_seen_seq,
        now=now,
        **watch_cycle_kwargs,
    )
    updated_state = replace(
        updated_state,
        last_seen_seq=max(updated_state.last_seen_seq, int(new_last_seen)),
    )
    updated_state, delivered = deliver_or_queue_batch(
        updated_state,
        batch,
        deliver_batch_fn=deliver_batch_fn,
    )
    return updated_state, batch, delivered


def collect_supervisable_watches(state_root: Path) -> list[tuple[Path, WatchState]]:
    collected: list[tuple[Path, WatchState]] = []
    for state_file in sorted(state_root.glob("*.json")):
        try:
            store = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        watches = store.get("watches")
        if not isinstance(watches, dict):
            continue
        for watch_id, raw in watches.items():
            if not isinstance(watch_id, str) or not isinstance(raw, dict):
                continue
            state = load_watch_state(state_file, watch_id)
            if is_terminal_watch(state):
                continue
            collected.append((state_file, state))
    return collected


def claim_supervisor_lock(
    lock_file: Path,
    *,
    owner: str,
    now: float,
    lease_seconds: float,
) -> bool:
    safe_lease_seconds = max(float(lease_seconds), 1.0)
    payload = {
        "owner": owner,
        "lease_until": float(now) + safe_lease_seconds,
    }
    if lock_file.exists():
        try:
            existing = json.loads(lock_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        existing_owner = str(existing.get("owner", ""))
        lease_until = float(existing.get("lease_until", 0.0))
        if existing_owner and existing_owner != owner and lease_until > float(now):
            return False
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def mark_watch_supervisor_heartbeat(
    state_file: Path,
    *,
    watch_id: str,
    pid: int,
    now: float,
    started_at: float,
) -> WatchState:
    state = load_watch_state(state_file, watch_id)
    updated = replace(
        state,
        supervisor_pid=int(pid),
        supervisor_started_at=float(started_at),
        supervisor_heartbeat_at=float(now),
    )
    save_watch_state(state_file, updated)
    return updated


def run_supervisor_cycle(
    state_root: Path,
    *,
    now: float,
    owner: str,
    lease_seconds: float,
    started_at: float,
    process_watch_once_fn=process_watch_once,
    deliver_batch_fn: DeliverBatchFn | None = None,
    **watch_cycle_kwargs: Any,
) -> dict[str, Any]:
    state_root = Path(state_root)
    lock_file = state_root / "supervisor.lock"
    if not claim_supervisor_lock(
        lock_file,
        owner=owner,
        now=now,
        lease_seconds=lease_seconds,
    ):
        return {
            "status": "locked",
            "processed": 0,
        }

    try:
        pid = int(owner) if str(owner).isdigit() else 0
    except ValueError:
        pid = 0

    processed = 0
    for state_file, state in collect_supervisable_watches(state_root):
        updated_state = replace(
            state,
            supervisor_pid=pid,
            supervisor_started_at=float(started_at),
            supervisor_heartbeat_at=float(now),
        )
        effective_deliver_batch_fn = deliver_batch_fn or build_stateful_deliver_batch_fn(updated_state)
        updated_state, _batch, _delivered = process_watch_once_fn(
            updated_state,
            now=now,
            deliver_batch_fn=effective_deliver_batch_fn,
            **watch_cycle_kwargs,
        )
        updated_state = replace(
            updated_state,
            supervisor_pid=pid,
            supervisor_started_at=float(started_at),
            supervisor_heartbeat_at=float(now),
        )
        save_watch_state(state_file, updated_state)
        processed += 1

    return {
        "status": "ok",
        "processed": processed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="常驻 webgen live watch supervisor")
    parser.add_argument("--state-root", required=True, help="watch state 文件所在目录")
    parser.add_argument("--once", action="store_true", help="只执行一次 supervisor cycle")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="循环模式下的间隔秒数")
    parser.add_argument("--lease-seconds", type=float, default=30.0, help="supervisor lock 的租期秒数")
    parser.add_argument("--owner", default="", help="显式指定 supervisor owner，默认当前进程 pid")
    parser.add_argument("--limit", type=int, default=30, help="history 抓取条数")
    parser.add_argument("--max-items", type=int, default=3, help="每次最多处理多少条摘要")
    parser.add_argument("--heartbeat-idle-polls", type=int, default=3, help="无新增时的心跳阈值")
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=60.0, help="心跳最小间隔秒数")
    parser.add_argument("--debounce-ms", type=int, default=0, help="session 文件变化去抖毫秒数")
    parser.add_argument(
        "--fallback-history-interval-seconds",
        type=float,
        default=15.0,
        help="文件无变化时 history 兜底拉取间隔秒数",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    owner = args.owner.strip() or str(os.getpid())
    started_at = time.time()
    watch_cycle_kwargs = build_default_watch_cycle_kwargs(
        limit=args.limit,
        max_items=args.max_items,
        heartbeat_idle_polls=args.heartbeat_idle_polls,
        heartbeat_interval_seconds=args.heartbeat_interval_seconds,
        debounce_ms=args.debounce_ms,
        fallback_history_interval_seconds=args.fallback_history_interval_seconds,
    )

    while True:
        payload = run_supervisor_cycle(
            Path(args.state_root),
            now=time.time(),
            owner=owner,
            lease_seconds=args.lease_seconds,
            started_at=started_at,
            **watch_cycle_kwargs,
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(payload)
        if args.once:
            return 0
        time.sleep(max(float(args.interval_seconds), 0.5))


if __name__ == "__main__":
    raise SystemExit(main())
