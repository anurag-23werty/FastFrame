"""Typer command-line interface for FastFrame."""

from __future__ import annotations

import difflib
import os
import re
import shutil
import tempfile
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .antipatterns import RULES, rewrite, rule_by_id
from .bench import benchmark
from .policy import load_config
from .report import render_report
from .scan import rewrite_path, scan_path
from .verify import VerificationResult, verify_scripts

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.command()
def demo() -> None:
    """Show the FastFrame, pandas, NumPy, and Docker-friendly terminal banner."""
    console.print("[bold bright_blue]╭────────────────────────────────────────────╮[/bold bright_blue]")
    console.print("[bold bright_blue]│[/bold bright_blue] [bold white]FASTFRAME[/bold white] · safe dataframe optimization [bold bright_blue]│[/bold bright_blue]")
    console.print("[bold bright_blue]╰────────────────────────────────────────────╯[/bold bright_blue]")
    console.print("  [bright_yellow]🐼 pandas[/bright_yellow]   [bright_green]▦ NumPy[/bright_green]   [bright_magenta]✦ LibCST[/bright_magenta]")
    console.print("  [cyan]Detect[/cyan] → [yellow]Rewrite[/yellow] → [green]Verify[/green] → [magenta]Benchmark[/magenta]")
    console.print()
    console.print("[bold cyan]Install:[/bold cyan] python -m pip install fastframe-pandas pandas numpy")
    console.print("[bold cyan]Try:[/bold cyan]     fastframe scan my_script.py")
    console.print()
    console.print("[bold blue]      .-~~~-.[/bold blue]")
    console.print("[bold blue]  .- ~ ~-(       )_ _[/bold blue]")
    console.print("[bold blue] /                 ~ -.[/bold blue]")
    console.print("[bold blue]|       DOCKER          |[/bold blue]")
    console.print("[bold blue] \\                 .-~~-.[/bold blue]")
    console.print("[bold blue]   ~- ._ _ _.-~       ~-.[/bold blue]")
    console.print("[bold white]Container-ready. Safe defaults enabled.[/bold white]")


@app.command()
def scan(file: Path, format: str = typer.Option("text", "--format")) -> None:
    """Recursively scan Python files and code cells in Jupyter notebooks."""
    if format not in {"text", "json"}:
        raise typer.BadParameter("format must be text or json")
    warnings: list[str] = []
    findings = scan_path(file, warnings=warnings)
    for warning in warnings:
        console.print(f"[yellow]{warning}[/yellow]")
    if format == "json":
        console.print_json(data=[item.as_dict() for item in findings])
    else:
        table = Table("Location", "Pattern", "Explanation", "Suggested action")
        for item in findings:
            action = "manual review" if item.finding.manual_fix else "vectorize with fastframe fix"
            table.add_row(item.location, item.finding.pattern, item.finding.message, action)
        console.print(table if findings else "No anti-patterns detected.")
    if findings:
        raise typer.Exit(1)


@app.command()
def fix(
    file: Path,
    output: Path | None = typer.Option(None, "-o", "--output"),
    diff: bool = typer.Option(False, "--diff", help="Print the diff without writing a file."),
    in_place: bool = typer.Option(False, "--in-place", help="Rewrite the input and keep a .bak copy."),
    no_verify: bool = typer.Option(False, "--no-verify", help="Skip equivalence verification (unsafe)."),
    verbose: bool = typer.Option(False, "--verbose", help="Show the full verification traceback."),
) -> None:
    """Write a deterministic rewrite, verifying it unless explicitly skipped."""
    if diff and (output or in_place):
        raise typer.BadParameter("--diff cannot be combined with -o/--output or --in-place")
    if output and in_place:
        raise typer.BadParameter("choose either -o/--output or --in-place")
    if not diff and not output and not in_place:
        raise typer.BadParameter("provide -o/--output or --in-place, or use --diff")
    if file.suffix == ".ipynb":
        console.print("[yellow]Notebook verification is not available; rewriting code cells in a copy.[/yellow]")
        if diff:
            raise typer.BadParameter("--diff is currently supported for Python files only")
        destination = file if in_place else output
        if destination is None:
            raise typer.BadParameter("notebook fixes require -o/--output or --in-place")
        if in_place:
            shutil.copy2(file, file.with_name(file.name + ".bak"))
        rewrite_path(file, destination)
        console.print(f"Wrote {destination}")
        return
    before = file.read_text(encoding="utf-8")
    after = rewrite(before, config=load_config(file))
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
                if verbose:
                    console.print(result.error)
                else:
                    match = re.search(r'File ".*?", line (\d+).*?\n.*?\n([A-Za-z_][\w.]*Error): (.*)', result.error, re.S)
                    if match:
                        console.print(f"{match.group(2)} at line {match.group(1)}: {match.group(3)}")
                    else:
                        console.print("VerificationError at line unknown: " + result.error.splitlines()[-1])
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


def _print_verification(result: VerificationResult) -> None:
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


@app.command("rules")
def rules() -> None:
    """List all built-in detection rules."""
    table = Table("Rule", "Title", "Explanation")
    for rule in RULES:
        table.add_row(rule.id, rule.title, rule.explanation)
    console.print(table)


@app.command()
def explain(rule: str) -> None:
    """Explain one rule with a representative before/after example."""
    selected = rule_by_id(rule)
    if selected is None:
        raise typer.BadParameter(f"unknown rule {rule}")
    examples = {
        "AP001": ('out = df.apply(lambda row: row["a"] + row["b"], axis=1)', 'out = df["a"] + df["b"]'),
        "AP002": ('out = df["a"].apply(lambda x: x * 2)', 'out = df["a"] * 2'),
        "AP003": ('for _, row in df.iterrows():\n    out.append(row["a"] + row["b"])', 'out.extend((df["a"] + df["b"]).tolist())'),
        "AP004": ('for chunk in chunks:\n    df = pd.concat([df, chunk])', '_parts = [df]\nfor chunk in chunks:\n    _parts.append(chunk)\ndf = pd.concat(_parts)'),
        "AP005": ('for value in values:\n    arr = np.append(arr, value)', '_parts = [arr]\nfor value in values:\n    _parts.append(np.atleast_1d(value))\narr = np.concatenate(_parts)'),
        "AP006": ('df["count"] = df["count"].astype("int64")', 'Manual review: pd.to_numeric(df["count"], downcast="integer")'),
    }
    before, after = examples[selected.id]
    console.print(f"[bold]{selected.id}: {selected.title}[/bold]\n{selected.explanation}")
    console.print("\nBefore:\n" + before + "\n\nAfter:\n" + after)


def main() -> None:
    app()
