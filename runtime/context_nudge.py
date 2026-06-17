#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from runtime.live_watch import WatchState


_BAND_ORDER = {
    "ok": 0,
    "warn": 1,
    "compact": 2,
    "force-compact": 3,
    "hard-stop": 3,
}

_BAND_THRESHOLDS = {
    "warn": ">=80%",
    "compact": ">=85%",
    "force-compact": ">=92%",
    "hard-stop": ">=92%",
}

_ACK_PATTERNS = (
    re.compile(r"已(?:执行|完成)\s*/?compact"),
    re.compile(r"/compact\s*已(?:执行|完成)"),
    re.compile(r"\bcompact(?:ion)?\s+(?:completed|done|finished|successful(?:ly)?)\b"),
    re.compile(r"\bcontext\s+compacted\b"),
)


def _band_rank(band: str) -> int:
    return _BAND_ORDER.get(band, 0)


def build_hidden_context_nudge_message(context_band: str) -> str:
    threshold = _BAND_THRESHOLDS.get(context_band)
    if not threshold:
        return "检查 context；必要时先/compact，再继续。"
    if context_band in {"force-compact", "hard-stop"}:
        return f"检查 context；{threshold} 立刻/compact，再继续。"
    return f"检查 context；{threshold} 先/compact，再继续。"


def maybe_plan_hidden_context_nudge(
    state: WatchState,
    *,
    context_band: str,
    now: float,
    cooldown_seconds: float = 300.0,
) -> tuple[dict[str, Any] | None, WatchState]:
    updated = replace(state, last_context_band=context_band)
    if _band_rank(context_band) <= _band_rank("ok"):
        return None, replace(updated, awaiting_context_ack=False)

    previous_rank = _band_rank(state.last_context_band)
    current_rank = _band_rank(context_band)
    in_cooldown = state.last_context_nudge_at > 0 and (now - state.last_context_nudge_at) < cooldown_seconds
    stronger_band = current_rank > previous_rank
    repeated_band = current_rank == previous_rank

    if repeated_band and in_cooldown:
        return None, updated

    action = {
        "kind": "context_nudge",
        "delivery": "hidden",
        "band": context_band,
        "sessionKey": state.target_session_key,
        "message": build_hidden_context_nudge_message(context_band),
    }

    return action, replace(
        updated,
        last_context_nudge_at=now,
        awaiting_context_ack=True,
    )


def clear_context_ack(state: WatchState, items: list[dict[str, Any]]) -> WatchState:
    if not state.awaiting_context_ack:
        return state

    for item in items:
        text = " ".join(
            str(item.get(key, ""))
            for key in ("summary", "raw", "text", "content")
            if item.get(key)
        ).lower()
        if any(pattern.search(text) for pattern in _ACK_PATTERNS):
            return replace(state, awaiting_context_ack=False)
    return state
