#!/usr/bin/env python3
from __future__ import annotations


def _clip_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    clipped = encoded[:max_bytes]
    return clipped.decode("utf-8", errors="ignore")


def truncate_tool_output(
    text: str,
    max_lines: int = 80,
    max_bytes: int = 8192,
    head_lines: int = 20,
    tail_lines: int = 20,
) -> dict[str, int | bool | str]:
    raw = text or ""
    total_bytes = len(raw.encode("utf-8"))
    lines = raw.splitlines()
    total_lines = len(lines)
    needs_truncation = total_lines > max_lines or total_bytes > max_bytes
    if not needs_truncation:
        return {
            "text": raw,
            "truncated": False,
            "dropped_lines": 0,
            "dropped_bytes": 0,
        }

    head_count = max(0, min(head_lines, total_lines))
    tail_count = max(0, min(tail_lines, max(0, total_lines - head_count)))
    while head_count + tail_count >= total_lines and tail_count > 0:
        tail_count -= 1
    while head_count + tail_count >= total_lines and head_count > 0:
        head_count -= 1

    kept_head = lines[:head_count]
    kept_tail = lines[total_lines - tail_count :] if tail_count else []
    dropped_lines = max(0, total_lines - head_count - tail_count)
    kept_text = "\n".join([*kept_head, *kept_tail])
    dropped_bytes = max(0, total_bytes - len(kept_text.encode("utf-8")))
    marker = f"... [truncated {dropped_lines} lines, {dropped_bytes} bytes] ..."
    parts = [*kept_head, marker, *kept_tail]
    bounded = "\n".join(part for part in parts if part)
    if len(bounded.encode("utf-8")) > max_bytes:
        bounded = "\n".join(part for part in [*kept_head[:1], marker, *kept_tail[-1:]] if part)
    bounded = _clip_bytes(bounded, max_bytes)
    return {
        "text": bounded,
        "truncated": True,
        "dropped_lines": dropped_lines,
        "dropped_bytes": dropped_bytes,
    }


def summarize_tool_payload(
    tool_name: str,
    text: str,
    *,
    max_lines: int = 80,
    max_bytes: int = 8192,
    head_lines: int = 20,
    tail_lines: int = 20,
) -> dict[str, object]:
    truncation = truncate_tool_output(
        text,
        max_lines=max_lines,
        max_bytes=max_bytes,
        head_lines=head_lines,
        tail_lines=tail_lines,
    )
    summarized = bool(truncation["truncated"]) and tool_name in {"read", "exec"}
    if summarized:
        summary = (
            f"{tool_name} 输出已摘要，仅保留头尾片段；"
            f"省略 {truncation['dropped_lines']} 行 / {truncation['dropped_bytes']} 字节"
        )
    elif truncation["truncated"]:
        summary = (
            f"{tool_name} 输出已截断；"
            f"省略 {truncation['dropped_lines']} 行 / {truncation['dropped_bytes']} 字节"
        )
    else:
        summary = f"{tool_name} 输出保留原文"
    return {
        "tool_name": tool_name,
        "text": truncation["text"],
        "summarized": summarized,
        "summary": summary,
        "truncation": truncation,
    }


def compaction_band(context_size: int) -> str:
    if context_size >= 160000:
        return "hard-stop"
    if context_size >= 140000:
        return "compact"
    if context_size >= 120000:
        return "warn"
    return "ok"


def _normalize_context_ratio(used_ratio: float) -> float:
    ratio = float(used_ratio)
    if ratio < 0.0:
        return 0.0
    if ratio <= 1.0:
        return ratio
    if ratio < 2.0:
        return 1.0
    if ratio <= 100.0:
        ratio = ratio / 100.0
    if ratio > 1.0:
        return 1.0
    return ratio


def compaction_band_for_ratio(used_ratio: float) -> str:
    ratio = _normalize_context_ratio(used_ratio)
    if ratio >= 0.92:
        return "force-compact"
    if ratio >= 0.85:
        return "compact"
    if ratio >= 0.80:
        return "warn"
    return "ok"
