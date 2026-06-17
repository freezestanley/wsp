#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from math import isfinite
from pathlib import Path
from typing import Any, TextIO

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.live_watch import (
    build_broadcast_batch,
    WatchState,
    load_watch_state,
    record_control_event,
    record_cycle_state,
    save_watch_state,
    summarize_new_messages,
)
from runtime.context_nudge import clear_context_ack, maybe_plan_hidden_context_nudge
from runtime.context_stopgap import compaction_band_for_ratio
from runtime.context_stopgap import truncate_tool_output

CFG_PATH = Path(os.environ.get('OPENCLAW_CONFIG_PATH', '/Users/za-stanlexu/.openclaw/openclaw.json'))


def load_config() -> dict[str, Any]:
    with CFG_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def gateway_endpoint(cfg: dict[str, Any]) -> tuple[str, dict[str, str]]:
    gateway = cfg.get('gateway', {})
    port = gateway.get('port', 18789)
    auth = gateway.get('auth', {})
    mode = auth.get('mode', 'none')
    headers = {'Content-Type': 'application/json'}
    if mode in ('token', 'password'):
        secret = auth.get('token') or auth.get('password')
        if not secret:
            raise RuntimeError(f'gateway.auth.mode={mode} 但配置里没有 token/password')
        headers['Authorization'] = f'Bearer {secret}'
    return f'http://127.0.0.1:{port}/tools/invoke', headers


def invoke_tool(url: str, headers: dict[str, str], tool: str, args: dict[str, Any]) -> Any:
    payload = {
        'tool': tool,
        'args': args,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.load(resp)
    if not body.get('ok'):
        raise RuntimeError(json.dumps(body, ensure_ascii=False))
    content = body.get('result', {}).get('content', [])
    if not content:
        return None
    text = ''.join(part.get('text', '') for part in content if part.get('type') == 'text')
    return json.loads(text) if text else None


def invoke_sessions_history(url: str, headers: dict[str, str], session_key: str, include_tools: bool, limit: int) -> dict[str, Any]:
    result = invoke_tool(url, headers, 'sessions_history', {
        'sessionKey': session_key,
        'includeTools': include_tools,
        'limit': limit,
    })
    return result or {'sessionKey': session_key, 'messages': []}


def invoke_sessions_list(url: str, headers: dict[str, str], agent_id: str, limit: int) -> dict[str, Any]:
    result = invoke_tool(url, headers, 'sessions_list', {
        'agentId': agent_id,
        'limit': limit,
    })
    return result or {'sessions': []}


def pick_webgen_project_session(sessions_payload: dict[str, Any]) -> str | None:
    sessions = sessions_payload.get('sessions', [])
    proj_sessions = [
        s for s in sessions
        if isinstance(s, dict) and isinstance(s.get('key'), str) and s['key'].startswith('agent:webgen:proj-')
    ]
    if not proj_sessions:
        return None
    proj_sessions.sort(key=lambda s: s.get('updatedAt', 0), reverse=True)
    return proj_sessions[0].get('key')


def print_intro(session_key: str, interval: float) -> None:
    print(f'📡 开始直播｜session={session_key}｜每 {interval:g} 秒轮询｜输出新增关键步骤 + assistant 进展', flush=True)


def normalize_context_usage_ratio(raw_ratio: float | None) -> float | None:
    if raw_ratio is None:
        return None
    ratio = float(raw_ratio)
    if not isfinite(ratio):
        raise ValueError('context usage ratio must be finite')
    if ratio < 0.0:
        return 0.0
    if ratio <= 1.0:
        return ratio
    if ratio < 2.0:
        raise ValueError('context usage ratio in (1, 2) is ambiguous; use 0..1 or 2..100 percentage form')
    if ratio <= 100.0:
        return ratio / 100.0
    return 1.0


def sanitize_context_nudge_cooldown_seconds(raw_cooldown: float) -> float:
    cooldown = float(raw_cooldown)
    if not isfinite(cooldown) or cooldown <= 0.0:
        return 1.0
    return cooldown


def emit_batch(batch: list[dict[str, Any]], *, jsonl: bool, stream: TextIO) -> None:
    for item in batch:
        if jsonl:
            stream.write(json.dumps(item, ensure_ascii=False) + '\n')
            continue
        if item.get("seq") is not None and item["kind"] in {"tool", "assistant"}:
            stream.write(f'[{item["seq"]}] {item["summary"]}\n')
        else:
            stream.write(f'{item["summary"]}\n')
    stream.flush()


def evaluate_silent_context_nudge_cycle(
    state: WatchState,
    *,
    items: list[dict[str, Any]],
    now: float,
    context_usage_ratio: float | None,
    cooldown_seconds: float = 300.0,
) -> tuple[dict[str, Any] | None, WatchState]:
    if context_usage_ratio is None:
        return None, state

    updated = clear_context_ack(state, items)
    normalized_ratio = normalize_context_usage_ratio(context_usage_ratio)
    context_band = compaction_band_for_ratio(normalized_ratio)
    return maybe_plan_hidden_context_nudge(
        updated,
        context_band=context_band,
        now=now,
        cooldown_seconds=sanitize_context_nudge_cooldown_seconds(cooldown_seconds),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='面向 webgen 建站委托的 session 直播摘要器')
    parser.add_argument('session_key', help='例如 agent:webgen:main 或 agent:webgen:proj-user-list-table')
    parser.add_argument('--interval', type=float, default=5.0, help='轮询间隔秒数，默认 5')
    parser.add_argument('--limit', type=int, default=30, help='每次抓取最近多少条消息，默认 30')
    parser.add_argument('--max-items', type=int, default=3, help='每次最多输出多少条用户可见摘要，默认 3')
    parser.add_argument('--once', action='store_true', help='只抓一次并输出摘要')
    parser.add_argument('--jsonl', action='store_true', help='以 JSONL 输出摘要')
    parser.add_argument('--since-seq', type=int, default=None, help='只输出 seq 大于该值的新增消息')
    parser.add_argument('--auto-switch-webgen', action='store_true', help='若发现新的 agent:webgen:proj-* session，自动切换追踪')
    parser.add_argument('--state-file', help='持久化 watch 游标的 JSON 文件路径')
    parser.add_argument('--watch-id', default='default', help='state-file 下的 watch 标识，默认 default')
    parser.add_argument('--heartbeat-idle-polls', type=int, default=3, help='连续多少次无新增后发进度心跳，默认 3')
    parser.add_argument('--heartbeat-interval-seconds', type=float, default=60.0, help='两次进度心跳的最小间隔秒数，默认 60')
    parser.add_argument('--control-event-id', help='可选：注入一条委托/控制面同步事件 id')
    parser.add_argument('--control-summary', help='可选：注入一条委托/控制面同步事件摘要')
    parser.add_argument('--control-phase', help='可选：注入控制面事件后的阶段标记')
    parser.add_argument('--context-usage-ratio', type=float, default=None, help='可选：注入本轮 context 使用率，0..1 或百分比')
    parser.add_argument('--context-nudge-cooldown-seconds', type=float, default=300.0, help='silent context nudge 的最小重试间隔秒数，默认 300')
    args = parser.parse_args()
    context_usage_ratio = normalize_context_usage_ratio(args.context_usage_ratio)
    context_nudge_cooldown_seconds = sanitize_context_nudge_cooldown_seconds(args.context_nudge_cooldown_seconds)

    cfg = load_config()
    url, headers = gateway_endpoint(cfg)
    state_path = Path(args.state_file) if args.state_file else None
    watch_state = (
        load_watch_state(state_path, args.watch_id, target_session_key=args.session_key)
        if state_path
        else WatchState(watch_id=args.watch_id, target_session_key=args.session_key)
    )
    current_session_key = watch_state.target_session_key or args.session_key
    last_seen = args.since_seq if args.since_seq is not None else watch_state.last_seen_seq

    if args.control_event_id and args.control_summary:
        bounded_control = truncate_tool_output(
            args.control_summary,
            max_lines=4,
            max_bytes=280,
            head_lines=3,
            tail_lines=1,
        )
        watch_state = record_control_event(
            watch_state,
            event_id=args.control_event_id,
            summary=str(bounded_control['text']),
            phase=args.control_phase,
        )

    if not args.jsonl:
        print_intro(current_session_key, args.interval)

    while True:
        try:
            if args.auto_switch_webgen:
                sessions_payload = invoke_sessions_list(url, headers, 'webgen', 50)
                switched_to = pick_webgen_project_session(sessions_payload)
                if switched_to and switched_to != current_session_key:
                    current_session_key = switched_to
                    last_seen = -1
                    if args.jsonl:
                        print(json.dumps({'event': 'session_switch', 'sessionKey': current_session_key}, ensure_ascii=False), flush=True)
                    else:
                        print(f'🔀 已切换直播目标 session：{current_session_key}', flush=True)

            history = invoke_sessions_history(url, headers, current_session_key, True, args.limit)
            messages = history.get('messages', [])
            items, last_seen = summarize_new_messages(messages, last_seen, current_session_key, max_items=args.max_items)
            now = time.time()
            watch_state.target_session_key = current_session_key
            watch_state.last_seen_seq = last_seen
            watch_state = record_cycle_state(watch_state, items, now)
            _silent_nudge, watch_state = evaluate_silent_context_nudge_cycle(
                watch_state,
                items=items,
                now=now,
                context_usage_ratio=context_usage_ratio,
                cooldown_seconds=context_nudge_cooldown_seconds,
            )
            batch, watch_state = build_broadcast_batch(
                watch_state,
                items,
                now,
                max_items=args.max_items,
                min_idle_polls=args.heartbeat_idle_polls,
                min_heartbeat_interval_seconds=args.heartbeat_interval_seconds,
            )
            emit_batch(batch, jsonl=args.jsonl, stream=sys.stdout)
            if state_path:
                save_watch_state(state_path, watch_state)
        except KeyboardInterrupt:
            return 130
        except urllib.error.HTTPError as e:
            print(f'HTTPError {e.code}: {e.read().decode("utf-8", errors="replace")}', file=sys.stderr, flush=True)
            if args.once:
                return 1
        except Exception as e:
            print(f'ERROR: {e}', file=sys.stderr, flush=True)
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
