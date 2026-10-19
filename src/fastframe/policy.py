"""Shared rule-selection and inline-suppression policy."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .antipatterns import Finding, detect

_SUPPRESSION = re.compile(r"#\s*fastframe:\s*ignore(?:\[([^\]]+)\])?", re.IGNORECASE)


@dataclass(frozen=True)
class ScanConfig:
    select: frozenset[str] = frozenset()
    ignore: frozenset[str] = frozenset()


def load_config(path: Path) -> ScanConfig:
    start = path if path.is_dir() else path.parent
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if not candidate.exists():
            continue
        with candidate.open("rb") as handle:
            data = tomllib.load(handle)
        settings = data.get("tool", {}).get("fastframe", {})
        return ScanConfig(
            frozenset(str(item).upper() for item in settings.get("select", [])),
            frozenset(str(item).upper() for item in settings.get("ignore", [])),
        )
    return ScanConfig()


def is_suppressed(source: str, finding: Finding) -> bool:
    lines = source.splitlines()
    if not 1 <= finding.line <= len(lines):
        return False
    match = _SUPPRESSION.search(lines[finding.line - 1])
    if not match:
        return False
    selected = match.group(1)
    return not selected or finding.pattern in {item.strip().upper() for item in selected.split(",")}


def is_enabled(finding: Finding, config: ScanConfig) -> bool:
    return (not config.select or finding.pattern in config.select) and finding.pattern not in config.ignore


def active_findings(source: str, config: ScanConfig | None = None) -> list[Finding]:
    config = config or ScanConfig()
    return [finding for finding in detect(source) if is_enabled(finding, config) and not is_suppressed(source, finding)]
