"""Generate a self-contained HTML anti-pattern report."""

from __future__ import annotations

import argparse
import difflib
import html
import tempfile
from pathlib import Path
from typing import List, Optional

from .antipatterns import Finding, detect, rewrite
from .bench import BenchmarkResult, benchmark
from .verify import VerificationResult, verify_scripts


def _badge(label: str, ok: bool) -> str:
    css = "pass" if ok else "fail"
    return f'<span class="badge {css}">{html.escape(label)}</span>'


def _code_block(text: str) -> str:
    return f"<pre><code>{html.escape(text)}</code></pre>"


def _diff(before: str, after: str) -> str:
    table = difflib.HtmlDiff(wrapcolumn=100).make_table(
        before.splitlines(), after.splitlines(), fromdesc="Before", todesc="After", context=True, numlines=3
    )
    return table


def _snippet(source: str, finding: Finding, radius: int = 2) -> str:
    lines = source.splitlines()
    start = max(0, finding.line - 1 - radius)
    end = min(len(lines), finding.line + radius)
    return "\n".join(lines[start:end]) + ("\n" if end else "")


def _metric(value: object, label: str) -> str:
    return f'<div class="metric"><strong>{html.escape(str(value))}</strong><span>{html.escape(label)}</span></div>'


def render_report(source_path: str | Path, output_path: str | Path, *, runs: int = 3) -> Path:
    source_path, output_path = Path(source_path), Path(output_path)
    source = source_path.read_text(encoding="utf-8")
    findings = detect(source)
    rewritten = rewrite(source)
    with tempfile.TemporaryDirectory(prefix="fastframe-report-") as temp:
        rewritten_path = Path(temp) / source_path.name
        rewritten_path.write_text(rewritten, encoding="utf-8")
        verification = verify_scripts(source_path, rewritten_path)
        metrics = benchmark(source_path, rewritten_path, runs=runs)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_page(source_path, source, rewritten, findings, verification, metrics), encoding="utf-8")
    return output_path


def _page(
    source_path: Path,
    source: str,
    rewritten: str,
    findings: List[Finding],
    verification: VerificationResult,
    metrics: BenchmarkResult,
) -> str:
    speed = f"{metrics.speedup:.2f}×"
    memory = f"{metrics.memory_savings_bytes:+,} bytes ({metrics.memory_savings_percent:+.1f}%)"
    rows = []
    for finding in findings:
        manual = finding.manual_fix
        status = "MANUAL REVIEW" if manual else ("PASS" if verification.passed else "FAIL")
        ok = manual or verification.passed
        before = _snippet(source, finding)
        after = _snippet(rewritten, finding)
        rows.append(
            f'''<article class="pattern">
              <div class="pattern-head"><h2>{html.escape(finding.pattern)} · {html.escape(finding.message)}</h2>{_badge(status, ok)}</div>
              <p class="meta">Line {finding.line}, column {finding.column} · Estimated saving: {finding.estimate_bytes if finding.estimate_bytes is not None else "n/a"} bytes/value</p>
              <div class="code-grid"><section><h3>Before</h3>{_code_block(before)}</section><section><h3>After</h3>{_code_block(after)}</section></div>
              <h3>Diff</h3>{_diff(before, after)}
            </article>'''
        )
    if not rows:
        rows.append('<article class="pattern"><h2>No anti-patterns detected</h2></article>')
    verification_text = "PASS" if verification.passed else f"FAIL: {verification.error or 'result mismatch'}"
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FastFrame report · {html.escape(source_path.name)}</title>
<style>
body{{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#202124;background:#f6f8fb;margin:0}}
main{{max-width:1180px;margin:0 auto;padding:32px 22px}} h1{{margin:0 0 4px}} h2{{font-size:18px;margin:0}} h3{{font-size:14px;color:#5f6368}}
.subtitle{{color:#5f6368;margin:0 0 24px}} .summary,.code-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.metric,.pattern{{background:#fff;border:1px solid #dfe3e8;border-radius:10px;padding:16px;box-shadow:0 1px 2px #0000000d}}
.metric strong{{display:block;font-size:23px}} .metric span{{color:#5f6368}} .pattern{{margin-top:18px}} .pattern-head{{display:flex;align-items:center;justify-content:space-between;gap:10px}}
.badge{{border-radius:999px;padding:4px 10px;font-weight:700;font-size:12px;white-space:nowrap}} .pass{{background:#e6f4ea;color:#137333}} .fail{{background:#fce8e6;color:#c5221f}}
.meta{{color:#5f6368;font-size:13px}} pre{{background:#202124;color:#f8f9fa;padding:12px;border-radius:6px;overflow:auto;min-height:42px}} code{{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}}
table.diff{{width:100%;font:12px ui-monospace,monospace;border-collapse:collapse;overflow:auto;display:block}} .diff_header{{background:#e8eaed}} td{{padding:2px 5px;white-space:pre-wrap;vertical-align:top}} .diff_add{{background:#ceead6}} .diff_sub{{background:#f7caca}} .diff_chg{{background:#fce8b2}}
</style></head><body><main>
<h1>FastFrame anti-pattern report</h1><p class="subtitle">{html.escape(source_path.name)} · deterministic rewrite and subprocess verification</p>
<section class="summary">{_metric(len(findings), "patterns detected")}{_metric(speed, "speedup")}{_metric(memory, "peak memory change")}{_metric(verification_text, "result verification")}</section>
{''.join(rows)}
</main></body></html>'''


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="create an HTML FastFrame anti-pattern report")
    parser.add_argument("source")
    parser.add_argument("--html", required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)
    render_report(args.source, args.html, runs=args.runs)
    print(f"wrote {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
