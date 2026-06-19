from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _openclaw_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
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


def _agent_id_from_session_key(session_key: str) -> str:
    parts = session_key.split(":")
    if len(parts) < 2 or parts[0] != "agent":
        return ""
    return parts[1].strip()


@dataclass(frozen=True)
class SessionFileSample:
    path: Path | None
    exists: bool
    mtime: float
    size: int
    inode: int
    sampled_at: float


def resolve_session_file_path(session_key: str, root: Path | None = None) -> Path | None:
    agent_id = _agent_id_from_session_key(session_key.strip())
    if not agent_id:
        return None

    sessions_dir = _openclaw_root(root) / "agents" / agent_id / "sessions"
    sessions = _load_json(sessions_dir / "sessions.json")
    metadata = sessions.get(session_key)
    if not isinstance(metadata, dict):
        return None

    session_file = str(metadata.get("sessionFile") or "").strip()
    if session_file:
        return Path(session_file).expanduser()

    session_id = str(metadata.get("sessionId") or "").strip()
    if session_id:
        return sessions_dir / f"{session_id}.jsonl"
    return None


def sample_session_file(path: Path | None) -> SessionFileSample:
    now = time.time()
    if path is None:
        return SessionFileSample(
            path=None,
            exists=False,
            mtime=0.0,
            size=0,
            inode=0,
            sampled_at=now,
        )

    try:
        stat = path.stat()
    except OSError:
        return SessionFileSample(
            path=path,
            exists=False,
            mtime=0.0,
            size=0,
            inode=0,
            sampled_at=now,
        )

    return SessionFileSample(
        path=path,
        exists=True,
        mtime=float(stat.st_mtime),
        size=int(stat.st_size),
        inode=int(stat.st_ino),
        sampled_at=now,
    )


def detect_session_file_change(previous: SessionFileSample, current: SessionFileSample) -> bool:
    return (
        previous.path != current.path
        or previous.exists != current.exists
        or previous.mtime != current.mtime
        or previous.size != current.size
        or previous.inode != current.inode
    )
