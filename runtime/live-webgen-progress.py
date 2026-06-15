#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

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
    return text.strip()


def single_line(text: str, max_len: int = 140) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + '…'


def summarize_tool_result(tool_name: str, text: str, is_error: bool) -> str:
    t = text.lower()
    if is_error:
        return f'❌ {tool_name} 报错：{single_line(text, 110)}'
    if tool_name == 'exec':
        if 'error' in t or 'failed' in t or 'command not found' in t or 'traceback' in t:
            return f'❌ 命令失败：{single_line(text, 110)}'
        if 'built in' in t or 'build succeeded' in t or 'compiled successfully' in t:
            return f'✅ 构建成功：{single_line(text, 110)}'
        if 'test' in t and ('passed' in t or 'pass' in t):
            return f'✅ 测试通过：{single_line(text, 110)}'
        if 'vite' in t and ('ready in' in t or 'local:' in t):
            return f'🚀 预览服务已启动：{single_line(text, 110)}'
        return f'🔧 命令输出：{single_line(text, 110)}'
    if tool_name == 'write':
        m = re.search(r'Successfully wrote \d+ bytes to (.+)', text)
        return f'📝 写入文件：{m.group(1)}' if m else f'📝 写入内容：{single_line(text, 110)}'
    if tool_name == 'edit':
        return f'✏️ 编辑文件：{single_line(text, 110)}'
    if tool_name == 'apply_patch':
        return f'🩹 应用补丁：{single_line(text, 110)}'
    if tool_name == 'sessions_send':
        return f'📨 发送消息到其他 session'
    return f'🛠️ {tool_name}：{single_line(text, 110)}'


def summarize_assistant(text: str) -> str:
    s = single_line(text, 140)
    lower = text.lower()
    if 'clarify' in lower or '澄清' in text or '请确认' in text or '你需要' in text or '请提供' in text:
        return f'❓ 需要澄清：{s}'
    if 'block' in lower or 'blocked' in lower or '阻塞' in text or '无法继续' in text:
        return f'⛔ 遇到阻塞：{s}'
    if '交付' in text or '完成' in text or 'done' in lower or 'delivered' in lower or '已实现' in text:
        return f'✅ 阶段结果：{s}'
    return f'💬 {s}'


def is_key_message(msg: dict[str, Any], text: str) -> bool:
    role = msg.get('role', 'unknown')
    tool_name = msg.get('toolName')
    is_error = bool(msg.get('isError'))
    lower = text.lower()
    if role == 'toolResult':
        if is_error:
            return True
        if tool_name in {'write', 'edit', 'apply_patch', 'sessions_send'}:
            return True
        if tool_name == 'exec':
            markers = ['error', 'failed', 'command not found', 'traceback', 'built in', 'build succeeded', 'compiled successfully', 'ready in', 'local:', 'passed', 'pass']
            return any(m in lower for m in markers)
        return False
    if role == 'assistant':
        return bool(text)
    return False


def summarize_message(msg: dict[str, Any], seq: int, session_key: str) -> dict[str, Any] | None:
    role = msg.get('role', 'unknown')
    text = flatten_content(msg)
    tool_name = msg.get('toolName')
    is_error = bool(msg.get('isError'))
    if not is_key_message(msg, text):
        return None
    if role == 'toolResult' and tool_name:
        summary = summarize_tool_result(tool_name, text, is_error)
        kind = 'tool'
    elif role == 'assistant':
        summary = summarize_assistant(text)
        kind = 'assistant'
    else:
        summary = f'ℹ️ {role}：{single_line(text, 140) or "(empty)"}'
        kind = role
    return {
        'seq': seq,
        'sessionKey': session_key,
        'role': role,
        'kind': kind,
        'summary': summary,
        'raw': text,
        'toolName': tool_name,
        'isError': is_error,
    }


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


def main() -> int:
    parser = argparse.ArgumentParser(description='面向 webgen 建站委托的 session 直播摘要器')
    parser.add_argument('session_key', help='例如 agent:webgen:main 或 agent:webgen:proj-user-list-table')
    parser.add_argument('--interval', type=float, default=5.0, help='轮询间隔秒数，默认 5')
    parser.add_argument('--limit', type=int, default=30, help='每次抓取最近多少条消息，默认 30')
    parser.add_argument('--once', action='store_true', help='只抓一次并输出摘要')
    parser.add_argument('--jsonl', action='store_true', help='以 JSONL 输出摘要')
    parser.add_argument('--since-seq', type=int, default=None, help='只输出 seq 大于该值的新增消息')
    parser.add_argument('--show-raw', action='store_true', help='输出摘要时追加原始文本')
    parser.add_argument('--auto-switch-webgen', action='store_true', help='若发现新的 agent:webgen:proj-* session，自动切换追踪')
    args = parser.parse_args()

    cfg = load_config()
    url, headers = gateway_endpoint(cfg)
    current_session_key = args.session_key
    last_seen = args.since_seq if args.since_seq is not None else -1

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
            new_rows = []
            for i, msg in enumerate(messages):
                seq = message_seq(msg, i)
                if seq > last_seen:
                    new_rows.append((seq, msg))
            new_rows.sort(key=lambda x: x[0])
            for seq, msg in new_rows:
                last_seen = max(last_seen, seq)
                item = summarize_message(msg, seq, current_session_key)
                if item is None:
                    continue
                if args.jsonl:
                    print(json.dumps(item, ensure_ascii=False), flush=True)
                else:
                    line = f'[{seq}] {item["summary"]}'
                    if args.show_raw and item['raw']:
                        line += f'\n    raw: {single_line(item["raw"], 200)}'
                    print(line, flush=True)
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
