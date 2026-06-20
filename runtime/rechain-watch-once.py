#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def normalize_args(argv: list[str]) -> list[str]:
    args = list(argv)
    if "--ok-if-idle" not in args:
        args.append("--ok-if-idle")
    return args


def load_rechain_watch_module():
    module_path = Path(__file__).resolve().parent / "rechain-watch.py"
    spec = importlib.util.spec_from_file_location("rechain_watch_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/rechain-watch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    module = load_rechain_watch_module()
    return int(module.main(normalize_args(argv or [])))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
