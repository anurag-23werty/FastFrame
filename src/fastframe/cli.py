"""Typer command-line interface for FastFrame."""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

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
def fix(
    file: Path,
    output: Optional[Path] = typer.Option(None, "-o", "--output"),
    diff: bool = typer.Option(False, "--diff", help="Print the diff without writing a file."),
    in_place: bool = typer.Option(False, "--in-place", help="Rewrite the input and keep a .bak copy."),
    no_verify: bool = typer.Option(False, "--no-verify", help="Skip equivalence verification (unsafe)."),
) -> None:
    """Write a deterministic rewrite, verifying it unless explicitly skipped."""
    if diff and (output or in_place):
        raise typer.BadParameter("--diff cannot be combined with -o/--output or --in-place")
    if output and in_place:
        raise typer.BadParameter("choose either -o/--output or --in-place")
    if not diff and not output and not in_place:
        raise typer.BadParameter("provide -o/--output or --in-place, or use --diff")
    before = file.read_text(encoding="utf-8")
    after = rewrite(before)
    if no_verify:
        console.print("[yellow]Warning: equivalence verification skipped (--no-verify).[/yellow]")
    else:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{file.stem}.fastframe-", suffix=file.suffix, dir=file.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(after, encoding="utf-8")
            result = verify_scripts(file, temporary)
        finally:
            temporary.unlink(missing_ok=True)
        if not result.passed:
            console.print("[red]Verification failed; no output was written.[/red]")
            if result.error:
                console.print(result.error)
            raise typer.Exit(1)
        console.print("[green]Verification passed.[/green]")
    if diff:
        console.print("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), str(file), str(file))))
        return
    destination = file if in_place else output
    assert destination is not None
    if in_place:
        backup = file.with_name(file.name + ".bak")
        shutil.copy2(file, backup)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(after, encoding="utf-8")
    console.print("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), str(file), str(destination))))


def _print_verification(result) -> None:
    status = "PASS" if result.passed else "FAIL"
    console.print(f"[green]{status}[/green] verification" if result.passed else f"[red]{status}[/red] verification")
    table = Table("Variable", "Status", "Details")
    for comparison in result.comparisons:
        table.add_row(comparison.name, "PASS" if comparison.passed else "FAIL", comparison.message or "equivalent")
    if result.comparisons:
        console.print(table)
    console.print(f"stdout: {'PASS' if result.stdout_match else 'FAIL'}")
    if result.error:
        console.print(f"[red]{result.error}[/red]")


@app.command()
def verify(original: Path, rewritten: Path, json_output: bool = typer.Option(False, "--json")) -> None:
    """Compare matching top-level result variables from two scripts."""
    result = verify_scripts(original, rewritten)
    if json_output:
        console.print_json(data=result.as_dict())
    else:
        _print_verification(result)
    if not result.passed:
        raise typer.Exit(1)


@app.command()
def bench(original: Path, rewritten: Path, runs: int = typer.Option(5, min=1), json_output: bool = typer.Option(False, "--json")) -> None:
    """Benchmark two scripts with runtime and peak-memory metrics."""
    result = benchmark(original, rewritten, runs=runs)
    if json_output:
        console.print_json(data=result.as_dict())
    else:
        table = Table("Script", "Median", "Minimum", "Peak memory")
        table.add_row("Original", f"{result.original.median_seconds:.4f}s", f"{result.original.min_seconds:.4f}s", f"{result.original.peak_memory_bytes:,} bytes")
        table.add_row("Rewritten", f"{result.rewritten.median_seconds:.4f}s", f"{result.rewritten.min_seconds:.4f}s", f"{result.rewritten.peak_memory_bytes:,} bytes")
        console.print(table)
        console.print(f"Speedup: {result.speedup:.2f}x")
        console.print(f"Peak memory saved: {result.memory_savings_bytes:+,} bytes ({result.memory_savings_percent:+.2f}%)")


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
