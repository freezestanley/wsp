from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_HTTP_GATEWAY_DENY = {
    "sessions_spawn",
    "sessions_send",
    "cron",
    "gateway",
    "whatsapp_login",
}


def openclaw_root() -> Path:
    configured = os.environ.get("OPENCLAW_HOME", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".openclaw"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def discover_origin_session_key(root: Path | None = None) -> str:
    base = root or openclaw_root()

    sessions_path = base / "agents" / "main" / "sessions" / "sessions.json"
    sessions = _load_json(sessions_path)
    ranked_sessions: list[tuple[int, str]] = []
    for session_key, meta in sessions.items():
        if not isinstance(session_key, str) or not session_key.startswith("agent:main:"):
            continue
        if not isinstance(meta, dict):
            continue
        updated_at = meta.get("lastInteractionAt", meta.get("updatedAt", 0))
        if not isinstance(updated_at, (int, float)):
            updated_at = 0
        ranked_sessions.append((int(updated_at), session_key))
    if ranked_sessions:
        ranked_sessions.sort(reverse=True)
        return ranked_sessions[0][1]

    last_session_path = base / "tui" / "last-session.json"
    last_sessions = _load_json(last_session_path)
    ranked_last_sessions: list[tuple[int, str]] = []
    for meta in last_sessions.values():
        if not isinstance(meta, dict):
            continue
        session_key = str(meta.get("sessionKey") or "").strip()
        if not session_key:
            continue
        updated_at = meta.get("updatedAt", 0)
        if not isinstance(updated_at, (int, float)):
            updated_at = 0
        ranked_last_sessions.append((int(updated_at), session_key))
    if ranked_last_sessions:
        ranked_last_sessions.sort(reverse=True)
        return ranked_last_sessions[0][1]

    return ""


def discover_sessions_send_support(root: Path | None = None) -> bool:
    base = root or openclaw_root()
    cfg = _load_json(base / "openclaw.json")
    gateway = cfg.get("gateway", {})
    if not isinstance(gateway, dict):
        return False
    gateway_tools = gateway.get("tools", {})
    if not isinstance(gateway_tools, dict):
        return False

    allow = {
        str(name).strip()
        for name in gateway_tools.get("allow", [])
        if isinstance(name, str) and str(name).strip()
    }
    deny = {
        str(name).strip()
        for name in gateway_tools.get("deny", [])
        if isinstance(name, str) and str(name).strip()
    }
    if "sessions_send" in deny:
        return False
    if "sessions_send" in DEFAULT_HTTP_GATEWAY_DENY and "sessions_send" not in allow:
        return False
    return True
