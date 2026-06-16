#!/usr/bin/env python3
from __future__ import annotations

from urllib.parse import quote, unquote

TOKEN_PREFIX = "__oc_live__"
VISIBLE_TEXT = "当前进度"
LEGACY_VISIBLE_PREFIX = "当前进度为："


def encode_wake_token(watch_id: str, target_session_key: str, last_seen_seq: int) -> str:
    encoded_session = quote(target_session_key, safe="")
    return f"{TOKEN_PREFIX}:{watch_id}:{last_seen_seq}:{encoded_session}"


def format_visible_wake_text(watch_id: str, target_session_key: str, last_seen_seq: int) -> str:
    return VISIBLE_TEXT


def strip_visible_prefix(text: str) -> str:
    if text.startswith(LEGACY_VISIBLE_PREFIX):
        return text[len(LEGACY_VISIBLE_PREFIX) :].strip()
    return text


def decode_wake_token(token: str) -> dict[str, object]:
    token = strip_visible_prefix(token)
    prefix, watch_id, last_seen_seq, encoded_session = token.split(":", 3)
    if prefix != TOKEN_PREFIX:
        raise ValueError(f"Unsupported wake token prefix: {prefix}")
    return {
        "watch_id": watch_id,
        "target_session_key": unquote(encoded_session),
        "last_seen_seq": int(last_seen_seq),
    }


def looks_like_wake_token(text: str) -> bool:
    return strip_visible_prefix(text).startswith(f"{TOKEN_PREFIX}:")


def is_visible_wake_text(text: str) -> bool:
    return text.strip() == VISIBLE_TEXT
