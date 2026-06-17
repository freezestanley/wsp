#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from runtime.live_wake_token import is_visible_wake_text, looks_like_wake_token


@dataclass(eq=True)
class WatchState:
    watch_id: str
    target_session_key: str
    last_seen_seq: int = -1
    last_broadcast_seq: int = -1
    phase: str = "implementing"
    last_heartbeat_at: float = 0.0
    idle_poll_count: int = 0
    last_progress_summary: str = ""
    last_control_event_id: str = ""
    pending_control_summary: str = ""
    last_context_band: str = "ok"
    last_context_nudge_at: float = 0.0
    awaiting_context_ack: bool = False


def _replace_state(state: WatchState, **changes: Any) -> WatchState:
    return replace(state, **changes)


def _read_state_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"watches": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"watches": {}}
    watches = data.get("watches")
    if not isinstance(watches, dict):
        return {"watches": {}}
    return {"watches": watches}


def load_watch_state(path: Path, watch_id: str, target_session_key: str | None = None) -> WatchState:
    store = _read_state_store(path)
    raw = store["watches"].get(watch_id)
    if not isinstance(raw, dict):
        return WatchState(
            watch_id=watch_id,
            target_session_key=target_session_key or "",
        )
    return WatchState(
        watch_id=watch_id,
        target_session_key=str(raw.get("target_session_key") or target_session_key or ""),
        last_seen_seq=int(raw.get("last_seen_seq", -1)),
        last_broadcast_seq=int(raw.get("last_broadcast_seq", -1)),
        phase=str(raw.get("phase", "implementing")),
        last_heartbeat_at=float(raw.get("last_heartbeat_at", 0.0)),
        idle_poll_count=int(raw.get("idle_poll_count", 0)),
        last_progress_summary=str(raw.get("last_progress_summary", "")),
        last_control_event_id=str(raw.get("last_control_event_id", "")),
        pending_control_summary=str(raw.get("pending_control_summary", "")),
        last_context_band=str(raw.get("last_context_band", "ok")),
        last_context_nudge_at=float(raw.get("last_context_nudge_at", 0.0)),
        awaiting_context_ack=bool(raw.get("awaiting_context_ack", False)),
    )


def save_watch_state(path: Path, state: WatchState) -> None:
    store = _read_state_store(path)
    store["watches"][state.watch_id] = asdict(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def message_seq(msg: dict[str, Any], fallback: int) -> int:
    oc = msg.get("__openclaw") or {}
    seq = oc.get("seq")
    if isinstance(seq, int):
        return seq
    ts = oc.get("recordTimestampMs") or msg.get("timestamp") or 0
    if isinstance(ts, (int, float)):
        return int(ts)
    return fallback


def flatten_content(msg: dict[str, Any]) -> str:
    content = msg.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        text = "\n".join(p for p in parts if p)
    elif isinstance(content, str):
        text = content
    else:
        text = ""
    return text.strip()


def single_line(text: str, max_len: int = 140) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def is_internal_prompt_text(text: str) -> bool:
    lowered = text.lower()
    if is_visible_wake_text(text):
        return True
    if text.startswith("[cron:"):
        return True
    if looks_like_wake_token(text):
        return True
    if "【继续监听任务】" in text or "【继续直播任务】" in text:
        return True
    if "payload.kind:\"agentturn\"" in lowered or "delivery.mode:\"announce\"" in lowered:
        return True
    internal_markers = [
        "inter-session routing echo",
        "not new content from webgen",
        "not a user instruction",
        "reply_skip",
        "nothing to broadcast",
        "staying silent",
        "another routing echo of my own prior message",
    ]
    if any(marker in lowered for marker in internal_markers):
        return True
    return False


def summarize_tool_result(tool_name: str, text: str, is_error: bool) -> str:
    t = text.lower()
    if is_error:
        return f"❌ {tool_name} 报错：{single_line(text, 110)}"
    if tool_name == "exec":
        if "error" in t or "failed" in t or "command not found" in t or "traceback" in t:
            return f"❌ 命令失败：{single_line(text, 110)}"
        if "built in" in t or "build succeeded" in t or "compiled successfully" in t:
            return f"✅ 构建成功：{single_line(text, 110)}"
        if "test" in t and ("passed" in t or "pass" in t):
            return f"✅ 测试通过：{single_line(text, 110)}"
        if "vite" in t and ("ready in" in t or "local:" in t):
            return f"🚀 预览服务已启动：{single_line(text, 110)}"
        return f"🔧 命令输出：{single_line(text, 110)}"
    if tool_name == "write":
        match = re.search(r"Successfully wrote \d+ bytes to (.+)", text)
        return f"📝 写入文件：{match.group(1)}" if match else f"📝 写入内容：{single_line(text, 110)}"
    if tool_name == "edit":
        return f"✏️ 编辑文件：{single_line(text, 110)}"
    if tool_name == "apply_patch":
        return f"🩹 应用补丁：{single_line(text, 110)}"
    if tool_name == "sessions_send":
        return "📨 发送消息到其他 session"
    return f"🛠️ {tool_name}：{single_line(text, 110)}"


def summarize_assistant(text: str) -> str:
    summary = single_line(text, 140)
    lower = text.lower()
    if "clarify" in lower or "澄清" in text or "请确认" in text or "你需要" in text or "请提供" in text:
        return f"❓ 需要澄清：{summary}"
    if "block" in lower or "blocked" in lower or "阻塞" in text or "无法继续" in text:
        return f"⛔ 遇到阻塞：{summary}"
    if "交付" in text or "完成" in text or "done" in lower or "delivered" in lower or "已实现" in text:
        return f"✅ 阶段结果：{summary}"
    return f"💬 {summary}"


def is_key_message(msg: dict[str, Any], text: str) -> bool:
    role = msg.get("role", "unknown")
    tool_name = msg.get("toolName")
    is_error = bool(msg.get("isError"))
    lower = text.lower()
    if role == "toolResult":
        if is_error:
            return True
        if tool_name in {"write", "edit", "apply_patch", "sessions_send"}:
            return True
        if tool_name == "exec":
            markers = [
                "error",
                "failed",
                "command not found",
                "traceback",
                "built in",
                "build succeeded",
                "compiled successfully",
                "ready in",
                "local:",
                "passed",
                "pass",
            ]
            return any(marker in lower for marker in markers)
        return False
    if role == "assistant":
        return bool(text) and not is_internal_prompt_text(text)
    return False


def summarize_message(msg: dict[str, Any], seq: int, session_key: str) -> dict[str, Any] | None:
    role = msg.get("role", "unknown")
    text = flatten_content(msg)
    tool_name = msg.get("toolName")
    is_error = bool(msg.get("isError"))
    if not is_key_message(msg, text):
        return None
    if role == "toolResult" and tool_name:
        summary = summarize_tool_result(tool_name, text, is_error)
        kind = "tool"
    elif role == "assistant":
        summary = summarize_assistant(text)
        kind = "assistant"
    else:
        summary = f"ℹ️ {role}：{single_line(text, 140) or '(empty)'}"
        kind = role
    return {
        "seq": seq,
        "sessionKey": session_key,
        "role": role,
        "kind": kind,
        "summary": summary,
        "raw": text,
        "toolName": tool_name,
        "isError": is_error,
    }


def summarize_new_messages(
    messages: list[dict[str, Any]],
    last_seen_seq: int,
    session_key: str,
    max_items: int = 3,
) -> tuple[list[dict[str, Any]], int]:
    new_rows: list[tuple[int, dict[str, Any]]] = []
    new_last_seen = last_seen_seq
    for index, msg in enumerate(messages):
        seq = message_seq(msg, index)
        if seq > last_seen_seq:
            new_rows.append((seq, msg))
        new_last_seen = max(new_last_seen, seq)
    new_rows.sort(key=lambda row: row[0])

    items: list[dict[str, Any]] = []
    for seq, msg in new_rows:
        if len(items) >= max_items:
            break
        item = summarize_message(msg, seq, session_key)
        if item is not None:
            items.append(item)
    return items, new_last_seen


def infer_phase_from_summary(summary: str, fallback: str) -> str:
    if "需要澄清" in summary:
        return "waiting_user"
    if "遇到阻塞" in summary:
        return "blocked"
    if "截图验证" in summary or "验证" in summary:
        return "verifying"
    if "阶段结果" in summary or "交付" in summary:
        return "done"
    return fallback


def record_cycle_state(state: WatchState, items: list[dict[str, Any]], now: float) -> WatchState:
    if items:
        latest = items[-1]
        latest_summary = str(latest.get("summary", ""))
        return _replace_state(
            state,
            last_broadcast_seq=int(latest.get("seq", state.last_broadcast_seq)),
            phase=infer_phase_from_summary(latest_summary, state.phase),
            idle_poll_count=0,
            last_progress_summary=latest_summary,
        )
    return _replace_state(
        state,
        idle_poll_count=state.idle_poll_count + 1,
    )


def phase_label(phase: str) -> str:
    return {
        "discovery": "澄清",
        "implementing": "实现",
        "verifying": "验证",
        "waiting_user": "等待确认",
        "blocked": "阻塞",
        "done": "完成",
        "canceled": "已取消",
    }.get(phase, phase)


def maybe_create_heartbeat(
    state: WatchState,
    now: float,
    min_idle_polls: int = 3,
    min_heartbeat_interval_seconds: float = 60.0,
) -> dict[str, Any] | None:
    if state.phase in {"waiting_user", "blocked", "done", "canceled"}:
        return None
    if state.idle_poll_count < min_idle_polls:
        return None
    if state.last_heartbeat_at > 0 and (now - state.last_heartbeat_at) < min_heartbeat_interval_seconds:
        return None

    label = phase_label(state.phase)
    if state.last_progress_summary:
        summary = (
            f"💓 当前进度为：仍在{label}阶段，最近一次动作是“"
            f"{single_line(state.last_progress_summary, 90)}”。"
        )
    else:
        summary = f"💓 当前进度为：仍在{label}阶段，webgen 暂无新步骤输出。"
    return {
        "seq": state.last_broadcast_seq,
        "kind": "heartbeat",
        "summary": summary,
        "sessionKey": state.target_session_key,
    }


def record_heartbeat_sent(state: WatchState, now: float) -> WatchState:
    return _replace_state(
        state,
        last_heartbeat_at=now,
    )


def record_control_event(state: WatchState, event_id: str, summary: str, phase: str | None = None) -> WatchState:
    return _replace_state(
        state,
        phase=phase or state.phase,
        last_control_event_id=event_id,
        pending_control_summary=summary,
    )


def maybe_take_control_event(state: WatchState) -> tuple[dict[str, Any] | None, WatchState]:
    if not state.pending_control_summary:
        return None, state
    item = {
        "seq": state.last_broadcast_seq,
        "kind": "control",
        "summary": state.pending_control_summary,
        "sessionKey": state.target_session_key,
    }
    updated = _replace_state(
        state,
        pending_control_summary="",
    )
    return item, updated


def build_broadcast_batch(
    state: WatchState,
    progress_items: list[dict[str, Any]],
    now: float,
    max_items: int = 3,
    min_idle_polls: int = 3,
    min_heartbeat_interval_seconds: float = 60.0,
) -> tuple[list[dict[str, Any]], WatchState]:
    batch: list[dict[str, Any]] = list(progress_items[:max_items])
    updated = state

    if len(batch) < max_items:
        control_item, updated = maybe_take_control_event(updated)
        if control_item is not None:
            batch.append(control_item)

    if len(batch) < max_items:
        heartbeat = maybe_create_heartbeat(
            updated,
            now,
            min_idle_polls=min_idle_polls,
            min_heartbeat_interval_seconds=min_heartbeat_interval_seconds,
        )
        if heartbeat is not None:
            batch.append(heartbeat)
            updated = record_heartbeat_sent(updated, now)

    return batch, updated
