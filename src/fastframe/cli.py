"""Typer command-line interface for FastFrame."""

from __future__ import annotations

import difflib
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .antipatterns import detect, rewrite
from .bench import benchmark
from .report import render_report
from .verify import verify_scripts

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.command()
def scan(file: Path) -> None:
    """List detected anti-patterns and suggested fixes."""
    findings = detect(file.read_text(encoding="utf-8"))
    table = Table("Pattern", "Line", "Explanation", "Suggested action")
    for finding in findings:
        action = "manual review" if finding.manual_fix else "vectorize with fastframe fix"
        table.add_row(finding.pattern, str(finding.line), finding.message, action)
    console.print(table if findings else "No anti-patterns detected.")


@app.command()
def fix(file: Path, output: Path = typer.Option(..., "-o", "--output")) -> None:
    """Write a deterministic rewrite and print its unified diff."""
    before = file.read_text(encoding="utf-8")
    after = rewrite(before)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(after, encoding="utf-8")
    console.print("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), str(file), str(output))))


@app.command()
def verify(original: Path, rewritten: Path) -> None:
    """Compare matching top-level result variables from two scripts."""
    result = verify_scripts(original, rewritten)
    console.print_json(data=result.as_dict())
    if not result.passed:
        raise typer.Exit(1)


@app.command()
def bench(original: Path, rewritten: Path, runs: int = typer.Option(5, min=1)) -> None:
    """Benchmark two scripts with runtime and peak-memory metrics."""
    result = benchmark(original, rewritten, runs=runs)
    console.print_json(data=result.as_dict())


@app.command()
def report(
    file: Path,
    html: Path = typer.Option(..., "--html"),
    runs: int = typer.Option(3, min=1),
) -> None:
    """Generate a self-contained scan, rewrite, verify, and benchmark report."""
    path = render_report(file, html, runs=runs)
    console.print(f"Wrote {path}")


def main() -> None:
    app()
