"""Project-aware scanning and rewriting for Python files and notebooks."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .antipatterns import Finding, rewrite
from .policy import ScanConfig, active_findings, is_enabled, is_suppressed, load_config

_suppressed = is_suppressed
_enabled = is_enabled


@dataclass(frozen=True)
class ScanItem:
    path: Path
    finding: Finding
    cell: int | None = None

    @property
    def location(self) -> str:
        if self.cell is None:
            return f"{self.path}:{self.finding.line}"
        return f"{self.path}:cell {self.cell} line {self.finding.line}"

    def as_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path), "cell": self.cell, "line": self.finding.line,
            "column": self.finding.column, "pattern": self.finding.pattern,
            "message": self.finding.message, "manual_fix": self.finding.manual_fix,
            "location": self.location,
        }


def _python_items(path: Path, config: ScanConfig) -> Iterator[ScanItem]:
    source = path.read_text(encoding="utf-8")
    for finding in active_findings(source, config):
        yield ScanItem(path, finding)


def _notebook_items(path: Path, config: ScanConfig) -> Iterator[ScanItem]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    for cell_number, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        for finding in active_findings(source, config):
            yield ScanItem(path, finding, cell_number)


def scan_path(path: str | Path, config: ScanConfig | None = None) -> list[ScanItem]:
    path = Path(path)
    config = config or load_config(path)
    targets = sorted(p for p in path.rglob("*") if p.suffix in {".py", ".ipynb"}) if path.is_dir() else [path]
    items: list[ScanItem] = []
    for target in targets:
        if target.suffix == ".ipynb":
            items.extend(_notebook_items(target, config))
        elif target.suffix == ".py":
            items.extend(_python_items(target, config))
    return items


def rewrite_notebook(source: Path, destination: Path, config: ScanConfig | None = None) -> None:
    """Rewrite active code cells into a separate notebook copy."""
    config = config or load_config(source)
    notebook = json.loads(source.read_text(encoding="utf-8"))
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "code":
            code = "".join(cell.get("source", []))
            cell["source"] = rewrite(code, config=config).splitlines(keepends=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")


def rewrite_path(source: Path, destination: Path, config: ScanConfig | None = None) -> None:
    config = config or load_config(source)
    if source.suffix == ".ipynb":
        rewrite_notebook(source, destination, config)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rewrite(source.read_text(encoding="utf-8"), config=config), encoding="utf-8")
