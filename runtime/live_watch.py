#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from runtime.live_wake_token import is_visible_wake_text, looks_like_wake_token


@dataclass(eq=True)
class WatchState:
    watch_id: str
    target_session_key: str
    origin_session_key: str = ""
    delivery_strategy: str = "hidden_wake"
    status: str = "pending"
    lease_owner: str = ""
    lease_until: float = 0.0
    last_worker_heartbeat_at: float = 0.0
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
    final_delivered: bool = False
    final_summary: str = ""
    needs_rechain: bool = False
    rechain_reason: str = ""
    session_file_path: str = ""
    session_file_mtime: float = 0.0
    session_file_size: int = 0
    session_file_inode: int = 0
    last_session_event_at: float = 0.0
    last_history_pull_at: float = 0.0


def is_terminal_watch(state: WatchState) -> bool:
    return state.status in {"done", "blocked", "canceled"} or state.phase in {
        "done",
        "blocked",
        "canceled",
        "waiting_user",
    }


def has_active_lease(state: WatchState, *, now: float) -> bool:
    return bool(state.lease_owner.strip()) and float(state.lease_until) > now


def needs_final_delivery(state: WatchState) -> bool:
    return is_terminal_watch(state) and not state.final_delivered


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
        origin_session_key=str(raw.get("origin_session_key") or ""),
        delivery_strategy=str(raw.get("delivery_strategy") or "hidden_wake"),
        status=str(raw.get("status") or "pending"),
        lease_owner=str(raw.get("lease_owner") or ""),
        lease_until=float(raw.get("lease_until", 0.0)),
        last_worker_heartbeat_at=float(raw.get("last_worker_heartbeat_at", 0.0)),
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
        final_delivered=bool(raw.get("final_delivered", False)),
        final_summary=str(raw.get("final_summary", "")),
        needs_rechain=bool(raw.get("needs_rechain", False)),
        rechain_reason=str(raw.get("rechain_reason", "")),
        session_file_path=str(raw.get("session_file_path", "")),
        session_file_mtime=float(raw.get("session_file_mtime", 0.0)),
        session_file_size=int(raw.get("session_file_size", 0)),
        session_file_inode=int(raw.get("session_file_inode", 0)),
        last_session_event_at=float(raw.get("last_session_event_at", 0.0)),
        last_history_pull_at=float(raw.get("last_history_pull_at", 0.0)),
    )


def save_watch_state(path: Path, state: WatchState) -> None:
    store = _read_state_store(path)
    store["watches"][state.watch_id] = asdict(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_visible_wake_state(text: str, path: Path) -> WatchState | None:
    if not is_visible_wake_text(text):
        return None

    store = _read_state_store(path)
    candidates: list[WatchState] = []
    for watch_id, raw in store["watches"].items():
        if not isinstance(watch_id, str) or not isinstance(raw, dict):
            continue
        candidates.append(
            WatchState(
                watch_id=watch_id,
                target_session_key=str(raw.get("target_session_key") or ""),
                origin_session_key=str(raw.get("origin_session_key") or ""),
                delivery_strategy=str(raw.get("delivery_strategy") or "hidden_wake"),
                status=str(raw.get("status") or "pending"),
                lease_owner=str(raw.get("lease_owner") or ""),
                lease_until=float(raw.get("lease_until", 0.0)),
                last_worker_heartbeat_at=float(raw.get("last_worker_heartbeat_at", 0.0)),
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
                final_delivered=bool(raw.get("final_delivered", False)),
                final_summary=str(raw.get("final_summary", "")),
                needs_rechain=bool(raw.get("needs_rechain", False)),
                rechain_reason=str(raw.get("rechain_reason", "")),
                session_file_path=str(raw.get("session_file_path", "")),
                session_file_mtime=float(raw.get("session_file_mtime", 0.0)),
                session_file_size=int(raw.get("session_file_size", 0)),
                session_file_inode=int(raw.get("session_file_inode", 0)),
                last_session_event_at=float(raw.get("last_session_event_at", 0.0)),
                last_history_pull_at=float(raw.get("last_history_pull_at", 0.0)),
            )
        )

    if not candidates:
        return None

    active_candidates = [
        state for state in candidates
        if not is_terminal_watch(state)
    ]
    pool = active_candidates or candidates
    pool.sort(
        key=lambda state: (
            state.last_heartbeat_at,
            state.last_broadcast_seq,
            state.last_seen_seq,
        ),
        reverse=True,
    )
    return pool[0]


def resolve_delivery_strategy(
    *,
    requested_strategy: str,
    supports_hidden_wake: bool,
    supports_sessions_send: bool,
    origin_session_key: str,
) -> str:
    requested = (requested_strategy or "auto").strip().lower()
    if requested and requested != "auto":
        return requested
    if supports_hidden_wake:
        return "hidden_wake"
    if supports_sessions_send and origin_session_key.strip():
        return "rebroadcast"
    return "manual_pull"


def prepare_watch_state(
    state: WatchState,
    *,
    target_session_key: str,
    origin_session_key: str,
    requested_strategy: str,
    supports_hidden_wake: bool,
    supports_sessions_send: bool,
) -> WatchState:
    resolved_origin = origin_session_key.strip() or state.origin_session_key
    resolved_target = target_session_key.strip() or state.target_session_key
    resolved_strategy = resolve_delivery_strategy(
        requested_strategy=requested_strategy,
        supports_hidden_wake=supports_hidden_wake,
        supports_sessions_send=supports_sessions_send,
        origin_session_key=resolved_origin,
    )
    return _replace_state(
        state,
        target_session_key=resolved_target,
        origin_session_key=resolved_origin,
        delivery_strategy=resolved_strategy,
    )


def normalize_watch_id_component(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "default"


def build_watch_bootstrap(
    *,
    target_session_key: str,
    origin_session_key: str,
    requested_strategy: str,
    supports_hidden_wake: bool,
    supports_sessions_send: bool,
    watch_id: str | None = None,
    state_root: Path | None = None,
) -> dict[str, Any]:
    resolved_watch_id = watch_id.strip() if isinstance(watch_id, str) and watch_id.strip() else (
        f"watch-{normalize_watch_id_component(target_session_key)}"
    )
    resolved_state_root = state_root or (Path(tempfile.gettempdir()) / "openclaw-live-watch")
    state = prepare_watch_state(
        WatchState(
            watch_id=resolved_watch_id,
            target_session_key=target_session_key,
        ),
        target_session_key=target_session_key,
        origin_session_key=origin_session_key,
        requested_strategy=requested_strategy,
        supports_hidden_wake=supports_hidden_wake,
        supports_sessions_send=supports_sessions_send,
    )
    return {
        "watch_id": state.watch_id,
        "state_file": resolved_state_root / f"{state.watch_id}.json",
        "target_session_key": state.target_session_key,
        "origin_session_key": state.origin_session_key,
        "delivery_strategy": state.delivery_strategy,
    }


def build_watch_invocation(
    bootstrap: dict[str, Any],
    *,
    python_bin: str = "python3",
    script_path: str = "runtime/live-webgen-progress.py",
    interval: float = 5.0,
    limit: int = 30,
    max_items: int = 3,
    auto_switch_webgen: bool = False,
    once: bool = False,
    jsonl: bool = False,
    supports_hidden_wake: bool = False,
) -> dict[str, Any]:
    command = [
        python_bin,
        script_path,
        str(bootstrap["target_session_key"]),
        "--interval",
        str(interval),
        "--limit",
        str(limit),
        "--max-items",
        str(max_items),
        "--state-file",
        str(bootstrap["state_file"]),
        "--watch-id",
        str(bootstrap["watch_id"]),
        "--delivery-strategy",
        str(bootstrap["delivery_strategy"]),
    ]
    if auto_switch_webgen:
        command.append("--auto-switch-webgen")
    if once:
        command.append("--once")
    if jsonl:
        command.append("--jsonl")
    if supports_hidden_wake:
        command.append("--supports-hidden-wake")

    env: dict[str, str] = {}
    origin_session_key = str(bootstrap.get("origin_session_key", "")).strip()
    if origin_session_key:
        env["OPENCLAW_ORIGIN_SESSION_KEY"] = origin_session_key

    return {
        "command": command,
        "env": env,
    }


def build_rechain_invocation(
    state: WatchState,
    *,
    state_file: Path,
    python_bin: str = "python3",
    script_path: str = "runtime/live-webgen-progress.py",
    interval: float = 5.0,
    limit: int = 30,
    max_items: int = 3,
) -> dict[str, Any] | None:
    if not state.needs_rechain:
        return None
    bootstrap = {
        "watch_id": state.watch_id,
        "state_file": state_file,
        "target_session_key": state.target_session_key,
        "origin_session_key": state.origin_session_key,
        "delivery_strategy": state.delivery_strategy,
    }
    invocation = build_watch_invocation(
        bootstrap,
        python_bin=python_bin,
        script_path=script_path,
        interval=interval,
        limit=limit,
        max_items=max_items,
        supports_hidden_wake=state.delivery_strategy == "hidden_wake",
    )
    invocation["reason"] = state.rechain_reason
    return invocation


def load_rechain_invocation(
    *,
    state_file: Path,
    watch_id: str,
    target_session_key: str | None = None,
    python_bin: str = "python3",
    script_path: str = "runtime/live-webgen-progress.py",
    interval: float = 5.0,
    limit: int = 30,
    max_items: int = 3,
) -> dict[str, Any] | None:
    state = load_watch_state(state_file, watch_id, target_session_key=target_session_key)
    return build_rechain_invocation(
        state,
        state_file=state_file,
        python_bin=python_bin,
        script_path=script_path,
        interval=interval,
        limit=limit,
        max_items=max_items,
    )


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


def is_cron_restricted_error_text(text: str) -> bool:
    return "cron tool is restricted to the current cron job." in text.lower()


def summarize_tool_result(tool_name: str, text: str, is_error: bool) -> str:
    t = text.lower()
    if is_error:
        if is_cron_restricted_error_text(text):
            return "♻️ cron 受限：当前回合只能操作当前 cron job，已标记待补链。"
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


def infer_status_from_phase(phase: str, fallback: str) -> str:
    if phase == "done":
        return "done"
    if phase == "blocked":
        return "blocked"
    if phase == "canceled":
        return "canceled"
    if phase in {"implementing", "verifying", "discovery", "waiting_user"}:
        return "running"
    return fallback


def record_cycle_state(state: WatchState, items: list[dict[str, Any]], now: float) -> WatchState:
    if items:
        latest = items[-1]
        latest_summary = str(latest.get("summary", ""))
        if is_cron_restricted_error_text(latest_summary) or "待补链" in latest_summary:
            return _replace_state(
                state,
                last_broadcast_seq=int(latest.get("seq", state.last_broadcast_seq)),
                idle_poll_count=0,
                needs_rechain=True,
                rechain_reason=latest_summary,
                pending_control_summary="⚠️ 当前回合处于 cron 受限态，已标记待补链，需在下一次普通用户回合补链。",
            )
        inferred_phase = infer_phase_from_summary(latest_summary, state.phase)
        return _replace_state(
            state,
            last_broadcast_seq=int(latest.get("seq", state.last_broadcast_seq)),
            phase=inferred_phase,
            status=infer_status_from_phase(inferred_phase, state.status),
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
        needs_rechain=False if state.needs_rechain else state.needs_rechain,
        rechain_reason="" if state.needs_rechain else state.rechain_reason,
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
