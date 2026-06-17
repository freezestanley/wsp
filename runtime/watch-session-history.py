#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.context_stopgap import summarize_tool_payload

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


def invoke_sessions_history(url: str, headers: dict[str, str], session_key: str, include_tools: bool, limit: int) -> dict[str, Any]:
    payload = {
        'tool': 'sessions_history',
        'args': {
            'sessionKey': session_key,
            'includeTools': include_tools,
            'limit': limit,
        },
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
        return {'sessionKey': session_key, 'messages': []}
    text = ''.join(part.get('text', '') for part in content if part.get('type') == 'text')
    return json.loads(text)


def message_seq(msg: dict[str, Any], fallback: int) -> int:
    oc = msg.get('__openclaw') or {}
    seq = oc.get('seq')
    if isinstance(seq, int):
        return seq
    ts = oc.get('recordTimestampMs') or msg.get('timestamp') or 0
    if isinstance(ts, (int, float)):
        return int(ts)
    return fallback


def flatten_content(msg: dict[str, Any]) -> str:
    content = msg.get('content')
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                parts.append(item.get('text', ''))
            elif isinstance(item, str):
                parts.append(item)
        text = '\n'.join(p for p in parts if p)
    elif isinstance(content, str):
        text = content
    else:
        text = ''

    role = msg.get('role', 'unknown')
    tool_name = msg.get('toolName')
    if role == 'toolResult' and tool_name:
        prefix = f'[tool:{tool_name}] '
    else:
        prefix = ''
    return prefix + text.strip()


def format_message(msg: dict[str, Any], seq: int) -> str:
    role = msg.get('role', 'unknown')
    text = flatten_content(msg)
    tool_name = msg.get('toolName')
    if role == 'toolResult' and tool_name:
        payload = summarize_tool_payload(tool_name, text)
        if payload['summarized'] or payload['truncation']['truncated']:
            text = f"{payload['summary']}\n{payload['text']}"
        else:
            text = str(payload['text'])
    if not text:
        text = '(empty)'
    return f'[{seq}] {role}: {text}'


def main() -> int:
    parser = argparse.ArgumentParser(description='轮询 OpenClaw sessions_history，只输出指定 session 的新增消息')
    parser.add_argument('session_key', help='例如 agent:webgen:proj-user-list-table')
    parser.add_argument('--interval', type=float, default=5.0, help='轮询间隔秒数，默认 5')
    parser.add_argument('--limit', type=int, default=30, help='每次抓取最近多少条消息，默认 30')
    parser.add_argument('--no-tools', action='store_true', help='抓取 history 时不包含 tool 结果')
    parser.add_argument('--jsonl', action='store_true', help='以 JSONL 输出新增消息')
    parser.add_argument('--once', action='store_true', help='只抓取一次后退出')
    parser.add_argument('--since-seq', type=int, default=None, help='仅输出 seq 大于该值的消息')
    args = parser.parse_args()

    cfg = load_config()
    url, headers = gateway_endpoint(cfg)
    include_tools = not args.no_tools
    last_seen = args.since_seq if args.since_seq is not None else -1

    while True:
        try:
            history = invoke_sessions_history(url, headers, args.session_key, include_tools, args.limit)
            messages = history.get('messages', [])
            new_rows = []
            for i, msg in enumerate(messages):
                seq = message_seq(msg, i)
                if seq > last_seen:
                    new_rows.append((seq, msg))
            new_rows.sort(key=lambda x: x[0])
            for seq, msg in new_rows:
                last_seen = max(last_seen, seq)
                if args.jsonl:
                    print(json.dumps({'seq': seq, 'message': msg}, ensure_ascii=False), flush=True)
                else:
                    print(format_message(msg, seq), flush=True)
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
