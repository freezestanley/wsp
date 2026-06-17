#!/usr/bin/env python3
from __future__ import annotations

import re


SECTION_ALIASES = {
    "design read": "design_read",
    "design_read": "design_read",
    "design variance": "design_variance",
    "design_variance": "design_variance",
    "motion intensity": "motion_intensity",
    "motion_intensity": "motion_intensity",
    "visual density": "visual_density",
    "visual_density": "visual_density",
    "device adaptation": "device_adaptation",
    "device_adaptation": "device_adaptation",
}


def _normalize_heading(text: str) -> str:
    lowered = text.strip().casefold()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    return SECTION_ALIASES.get(lowered, "")


def _clean_section_lines(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        cleaned.append(line)
    return cleaned


def extract_discovery_summary(text: str) -> dict[str, object]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in (text or "").splitlines():
        heading_match = re.match(r"^#{2,6}\s+(.+?)\s*$", raw_line)
        if heading_match:
            current = _normalize_heading(heading_match.group(1))
            if current and current not in sections:
                sections[current] = []
            continue
        if current:
            sections.setdefault(current, []).append(raw_line)

    result: dict[str, object] = {}
    if "design_read" in sections:
        result["design_read"] = _clean_section_lines(sections["design_read"])
    for key in ("design_variance", "motion_intensity", "visual_density"):
        if key in sections:
            values = _clean_section_lines(sections[key])
            if values:
                result[key] = values[0]
    if "device_adaptation" in sections:
        result["device_adaptation"] = _clean_section_lines(sections["device_adaptation"])
    return result
