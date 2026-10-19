"""Project-aware scanning for Python files and Jupyter notebooks."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .antipatterns import Finding, detect, rewrite

_SUPPRESSION = re.compile(r"#\s*fastframe:\s*ignore(?:\[([^\]]+)\])?", re.IGNORECASE)


@dataclass(frozen=True)
class ScanItem:
    path: Path
    finding: Finding
    cell: Optional[int] = None

    @property
    def location(self) -> str:
        if self.cell is None:
            return f"{self.path}:{self.finding.line}"
        return f"{self.path}:cell {self.cell} line {self.finding.line}"

    def as_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "cell": self.cell,
            "line": self.finding.line,
            "column": self.finding.column,
            "pattern": self.finding.pattern,
            "message": self.finding.message,
            "manual_fix": self.finding.manual_fix,
            "location": self.location,
        }


@dataclass(frozen=True)
class ScanConfig:
    select: frozenset[str] = frozenset()
    ignore: frozenset[str] = frozenset()


def load_config(path: Path) -> ScanConfig:
    """Load the nearest [tool.fastframe] select/ignore lists."""
    start = path if path.is_dir() else path.parent
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if not candidate.exists():
            continue
        with candidate.open("rb") as handle:
            data = tomllib.load(handle)
        settings = data.get("tool", {}).get("fastframe", {})
        return ScanConfig(frozenset(settings.get("select", [])), frozenset(settings.get("ignore", [])))
    return ScanConfig()


def _suppressed(source: str, finding: Finding) -> bool:
    lines = source.splitlines()
    if not 1 <= finding.line <= len(lines):
        return False
    match = _SUPPRESSION.search(lines[finding.line - 1])
    if not match:
        return False
    selected = match.group(1)
    return not selected or finding.pattern in {item.strip() for item in selected.split(",")}


def _enabled(finding: Finding, config: ScanConfig) -> bool:
    return (not config.select or finding.pattern in config.select) and finding.pattern not in config.ignore


def _python_items(path: Path, config: ScanConfig) -> Iterator[ScanItem]:
    source = path.read_text(encoding="utf-8")
    for finding in detect(source):
        if _enabled(finding, config) and not _suppressed(source, finding):
            yield ScanItem(path, finding)


def _notebook_items(path: Path, config: ScanConfig) -> Iterator[ScanItem]:
    import json

    notebook = json.loads(path.read_text(encoding="utf-8"))
    for cell_number, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        for finding in detect(source):
            if _enabled(finding, config) and not _suppressed(source, finding):
                yield ScanItem(path, finding, cell_number)


def scan_path(path: str | Path, config: Optional[ScanConfig] = None) -> list[ScanItem]:
    path = Path(path)
    config = config or load_config(path)
    if path.is_dir():
        targets = sorted(p for p in path.rglob("*") if p.suffix in {".py", ".ipynb"})
    else:
        targets = [path]
    items: list[ScanItem] = []
    for target in targets:
        if target.suffix == ".ipynb":
            items.extend(_notebook_items(target, config))
        elif target.suffix == ".py":
            items.extend(_python_items(target, config))
    return items


def rewrite_notebook(source: Path, destination: Path) -> None:
    """Rewrite code cells into a separate notebook copy; leave markdown intact."""
    import json

    notebook = json.loads(source.read_text(encoding="utf-8"))
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "code":
            code = "".join(cell.get("source", []))
            cell["source"] = rewrite(code).splitlines(keepends=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")


def rewrite_path(source: Path, destination: Path) -> None:
    if source.suffix == ".ipynb":
        rewrite_notebook(source, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rewrite(source.read_text(encoding="utf-8")), encoding="utf-8")
