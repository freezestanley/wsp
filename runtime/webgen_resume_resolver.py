#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

SlugResolver = Callable[[str], dict[str, str]]

SLUG_RE = r"[a-z0-9]+(?:-[a-z0-9]+)*"
PROJECT_PATH_PATTERN = re.compile(rf"projects/({SLUG_RE})\b", re.IGNORECASE)
EXPLICIT_SLUG_PATTERN = re.compile(rf"\bslug\b\s*[:=：]\s*`?({SLUG_RE})`?", re.IGNORECASE)
TITLE_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def default_openclaw_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_projects_root(openclaw_root: Path | None = None) -> Path:
    root = openclaw_root or default_openclaw_root()
    return root / "agents" / "webgen" / "workspace" / "projects"


def default_session_route_script(openclaw_root: Path | None = None) -> Path:
    root = openclaw_root or default_openclaw_root()
    return root / "agents" / "webgen" / "workspace" / "scripts" / "session-route.sh"


def default_session_recover_script(openclaw_root: Path | None = None) -> Path:
    root = openclaw_root or default_openclaw_root()
    return root / "agents" / "webgen" / "workspace" / "scripts" / "session-recover.sh"


def normalize_title(text: str) -> str:
    lowered = text.casefold()
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def parse_project_title(project_dir: Path) -> str:
    project_md = project_dir / "PROJECT.md"
    if project_md.exists():
        content = project_md.read_text(encoding="utf-8")
        match = TITLE_PATTERN.search(content)
        if match:
            return match.group(1).strip()
    return project_dir.name.replace("-", " ")


def load_project_index(projects_root: Path) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    if not projects_root.exists():
        return index
    for entry in sorted(projects_root.iterdir()):
        if not entry.is_dir():
            continue
        slug = entry.name
        index[slug] = {
            "slug": slug,
            "title": parse_project_title(entry),
            "projectDir": str(entry),
        }
    return index


def parse_envelope_output(stdout: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def invoke_session_route_resume(slug: str, session_route_script: Path | None = None) -> dict[str, str]:
    script = session_route_script or default_session_route_script()
    completed = subprocess.run(
        ["sh", str(script), "envelope", "resume", slug],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_envelope_output(completed.stdout)


def invoke_session_recover_resume(slug: str, session_recover_script: Path | None = None) -> dict[str, str]:
    script = session_recover_script or default_session_recover_script()
    completed = subprocess.run(
        ["sh", str(script), "resume", slug],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_envelope_output(completed.stdout)


def _collect_project_dir_matches(message: str, project_index: dict[str, dict[str, str]]) -> set[str]:
    return {
        match.group(1).lower()
        for match in PROJECT_PATH_PATTERN.finditer(message)
        if match.group(1).lower() in project_index
    }


def _collect_slug_matches(message: str, project_index: dict[str, dict[str, str]]) -> set[str]:
    matches = {
        match.group(1).lower()
        for match in EXPLICIT_SLUG_PATTERN.finditer(message)
        if match.group(1).lower() in project_index
    }
    lowered = message.casefold()
    for slug in project_index:
        if re.search(rf"(?<![a-z0-9-]){re.escape(slug)}(?![a-z0-9-])", lowered):
            matches.add(slug)
    return matches


def _collect_title_matches(message: str, project_index: dict[str, dict[str, str]]) -> tuple[set[str], bool]:
    normalized_message = f" {normalize_title(message)} "
    if not normalized_message.strip():
        return set(), False

    title_to_slugs: dict[str, list[str]] = {}
    for slug, meta in project_index.items():
        normalized_title = normalize_title(meta["title"])
        if normalized_title:
            title_to_slugs.setdefault(normalized_title, []).append(slug)

    matched_slugs: set[str] = set()
    ambiguous = False
    for normalized_title, slugs in title_to_slugs.items():
        if f" {normalized_title} " not in normalized_message:
            continue
        if len(slugs) > 1:
            ambiguous = True
        matched_slugs.update(slugs)
    return matched_slugs, ambiguous


def resolve_resume_target(
    message: str,
    *,
    projects_root: Path | None = None,
    session_route_resolver: SlugResolver | None = None,
    session_recover_resolver: SlugResolver | None = None,
    session_route_script: Path | None = None,
    session_recover_script: Path | None = None,
) -> dict[str, str | bool]:
    root = projects_root or default_projects_root()
    project_index = load_project_index(root)
    if not project_index:
        return {"matched": False, "reason": "projects-root-empty"}

    by_source = [
        ("project-dir", _collect_project_dir_matches(message, project_index), False),
        ("slug", _collect_slug_matches(message, project_index), False),
    ]
    title_matches, title_ambiguous = _collect_title_matches(message, project_index)
    by_source.append(("project-name", title_matches, title_ambiguous))

    source_matches: list[tuple[str, str]] = []
    all_slugs: set[str] = set()
    ambiguous_name_only = False
    for source, slugs, ambiguous in by_source:
        if ambiguous and not slugs:
            ambiguous_name_only = True
        for slug in sorted(slugs):
            source_matches.append((source, slug))
            all_slugs.add(slug)
        if ambiguous and slugs:
            return {"matched": False, "reason": "ambiguous-deterministic-project-match"}

    if len(all_slugs) > 1:
        return {"matched": False, "reason": "ambiguous-deterministic-project-match"}
    if not all_slugs:
        if title_ambiguous or ambiguous_name_only:
            return {"matched": False, "reason": "ambiguous-deterministic-project-match"}
        return {"matched": False, "reason": "no-deterministic-project-match"}

    source_priority = {"project-dir": 0, "slug": 1, "project-name": 2}
    resolved_slug = next(iter(all_slugs))
    resolved_source = min(
        (source for source, slug in source_matches if slug == resolved_slug),
        key=lambda item: source_priority[item],
    )

    resolver = session_route_resolver
    if resolver is None:
        resolver = lambda slug: invoke_session_route_resume(slug, session_route_script=session_route_script)
    recover_resolver = session_recover_resolver
    if recover_resolver is None:
        recover_resolver = lambda slug: invoke_session_recover_resume(
            slug,
            session_recover_script=session_recover_script,
        )

    try:
        envelope = resolver(resolved_slug)
    except subprocess.CalledProcessError:
        envelope = recover_resolver(resolved_slug)
    result = {
        "matched": True,
        "slug": resolved_slug,
        "source": resolved_source,
        "projectDir": project_index[resolved_slug]["projectDir"],
        "projectName": project_index[resolved_slug]["title"],
        "sessionKey": envelope.get("sessionKey", ""),
        "mode": envelope.get("mode", f"resume:{resolved_slug}"),
    }
    return result


def _load_message_from_args(args: argparse.Namespace) -> str:
    if args.message is not None:
        return args.message
    if args.stdin or not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("Provide --message or pipe the user message via stdin.")


def _print_result(result: dict[str, str | bool], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
        return
    for key in ("matched", "slug", "source", "sessionKey", "mode", "projectName", "projectDir", "reason"):
        if key in result:
            print(f"{key}={result[key]}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve deterministic webgen resume targets before delegation.",
    )
    parser.add_argument("--message", help="Raw user message to inspect.")
    parser.add_argument("--stdin", action="store_true", help="Read the user message from stdin.")
    parser.add_argument("--projects-root", type=Path, help="Override projects root.")
    parser.add_argument("--session-route-script", type=Path, help="Override session-route.sh path.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of key=value lines.")
    args = parser.parse_args()

    message = _load_message_from_args(args)
    result = resolve_resume_target(
        message,
        projects_root=args.projects_root,
        session_route_script=args.session_route_script,
    )
    _print_result(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
