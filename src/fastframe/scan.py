"""Project-aware scanning and rewriting for Python files and notebooks."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from libcst import ParserSyntaxError

from .antipatterns import Finding, rewrite
from .policy import ScanConfig, active_findings, is_enabled, is_suppressed, load_config

_suppressed = is_suppressed
_enabled = is_enabled

DEFAULT_EXCLUDES = frozenset({".venv", "venv", "site-packages", "node_modules", ".git", "build", "dist", "__pycache__"})


def _mask_magics(source: str) -> tuple[str, dict[int, str]]:
    lines = source.splitlines(keepends=True)
    protected: dict[int, str] = {}
    masked: list[str] = []
    for index, line in enumerate(lines):
        text = line.rstrip("\r\n")
        newline = line[len(text):]
        magic = re.match(r"^\s*(?:%%|%|!)", text) is not None
        if magic:
            protected[index] = line
            marker = f"# fastframe masked {index}"
            marker = marker[: max(1, len(text))].ljust(len(text)) if len(text) >= len(marker) else "#".ljust(len(text))
            masked.append(marker + newline)
        else:
            masked.append(line)
    return "".join(masked), protected


def _restore_magics(source: str, protected: dict[int, str]) -> str:
    lines = source.splitlines(keepends=True)
    for index, original in protected.items():
        if index < len(lines):
            current = lines[index].rstrip("\r\n")
            if current.lstrip().startswith("# fastframe masked") or current.strip() == "#":
                lines[index] = original
    return "".join(lines)


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


def _python_items(path: Path, config: ScanConfig, warnings: list[str]) -> Iterator[ScanItem]:
    source = path.read_text(encoding="utf-8")
    try:
        findings = active_findings(source, config)
    except (SyntaxError, ParserSyntaxError) as exc:
        warnings.append(f"skipped {path}: syntax error at line {getattr(exc, 'raw_line', 1)}")
        return
    for finding in findings:
        yield ScanItem(path, finding)


def _notebook_items(path: Path, config: ScanConfig) -> Iterator[ScanItem]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    for cell_number, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        masked, _ = _mask_magics(source)
        try:
            findings = active_findings(masked, config)
        except (SyntaxError, ParserSyntaxError):
            continue
        for finding in findings:
            yield ScanItem(path, finding, cell_number)


def scan_path(path: str | Path, config: ScanConfig | None = None, warnings: list[str] | None = None) -> list[ScanItem]:
    path = Path(path)
    config = config or load_config(path)
    warnings = warnings if warnings is not None else []
    if path.is_dir():
        targets = sorted(
            p for p in path.rglob("*")
            if p.suffix in {".py", ".ipynb"}
            and not any(part in DEFAULT_EXCLUDES or part in config.exclude for part in p.relative_to(path).parts[:-1])
        )
    else:
        targets = [path]
    items: list[ScanItem] = []
    for target in targets:
        if target.suffix == ".ipynb":
            items.extend(_notebook_items(target, config))
        elif target.suffix == ".py":
            items.extend(_python_items(target, config, warnings))
    return items


def rewrite_notebook(source: Path, destination: Path, config: ScanConfig | None = None) -> None:
    """Rewrite active code cells into a separate notebook copy."""
    config = config or load_config(source)
    notebook = json.loads(source.read_text(encoding="utf-8"))
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "code":
            code = "".join(cell.get("source", []))
            masked, protected = _mask_magics(code)
            try:
                rewritten = rewrite(masked, config=config)
            except (SyntaxError, ParserSyntaxError):
                continue
            cell["source"] = _restore_magics(rewritten, protected).splitlines(keepends=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(notebook, indent=1) + "\n", encoding="utf-8")


def rewrite_path(source: Path, destination: Path, config: ScanConfig | None = None) -> None:
    config = config or load_config(source)
    if source.suffix == ".ipynb":
        rewrite_notebook(source, destination, config)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rewrite(source.read_text(encoding="utf-8"), config=config), encoding="utf-8")
