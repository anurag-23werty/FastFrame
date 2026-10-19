"""Generate a self-contained HTML anti-pattern report."""

from __future__ import annotations

import argparse
import difflib
import html
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .antipatterns import Finding, detect, rewrite
from .bench import BenchmarkResult, benchmark
from .verify import VerificationResult, verify_scripts


@dataclass
class PatternResult:
    finding: Finding
    before: str
    after: str
    verification: VerificationResult | None
    metrics: BenchmarkResult | None


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


def _pattern_metrics(result: PatternResult) -> str:
    finding = result.finding
    if finding.manual_fix:
        badge = _badge("PASS · manual review", True)
        verification_text = "No code rewrite; advisory finding only"
    else:
        assert result.verification is not None and result.metrics is not None
        passed = result.verification.passed
        badge = _badge("PASS" if passed else "FAIL", passed)
        verification_text = "Equivalent outputs" if passed else (result.verification.error or "result mismatch")
    metrics = result.metrics
    if metrics is None:
        return f'''<div class="pattern-metrics">
      <div><strong>Verify</strong><span>{html.escape(verification_text)}</span></div>
      <div><strong>Speedup</strong><span>advisory only</span></div>
      <div><strong>Memory</strong><span>advisory only</span></div>
      <div class="status">{badge}</div>
    </div>'''
    return f'''<div class="pattern-metrics">
      <div><strong>Verify</strong><span>{html.escape(verification_text)}</span></div>
      <div><strong>Speedup</strong><span>{metrics.speedup:.2f}×</span></div>
      <div><strong>Memory</strong><span>{metrics.memory_savings_bytes:+,} bytes ({metrics.memory_savings_percent:+.1f}%)</span></div>
      <div><strong>Timing median</strong><span>{metrics.original.median_seconds:.4f}s → {metrics.rewritten.median_seconds:.4f}s</span></div>
      <div><strong>Timing min</strong><span>{metrics.original.min_seconds:.4f}s → {metrics.rewritten.min_seconds:.4f}s</span></div>
      <div class="status">{badge}</div>
    </div>'''


def _pattern_results(source_path: Path, source: str, findings: list[Finding], temp: Path, runs: int) -> list[PatternResult]:
    counts: dict[str, int] = {}
    results: list[PatternResult] = []
    for finding in findings:
        before = _snippet(source, finding)
        if finding.manual_fix:
            results.append(PatternResult(finding, before, before, None, None))
            continue
        counts[finding.pattern] = counts.get(finding.pattern, 0) + 1
        rewritten = rewrite(source, pattern=finding.pattern, occurrence=counts[finding.pattern])
        candidate = temp / f"{source_path.stem}-{finding.pattern.lower()}-{counts[finding.pattern]}{source_path.suffix}"
        candidate.write_text(rewritten, encoding="utf-8")
        results.append(
            PatternResult(
                finding,
                before,
                _snippet(rewritten, finding),
                verify_scripts(source_path, candidate),
                benchmark(source_path, candidate, runs=runs),
            )
        )
    return results


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
        patterns = _pattern_results(source_path, source, findings, Path(temp), runs)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_page(source_path, source, findings, patterns, verification, metrics), encoding="utf-8")
    return output_path


def _page(
    source_path: Path,
    source: str,
    findings: list[Finding],
    patterns: list[PatternResult],
    verification: VerificationResult,
    metrics: BenchmarkResult,
) -> str:
    speed = f"{metrics.speedup:.2f}×"
    memory = f"{metrics.memory_savings_bytes:+,} bytes ({metrics.memory_savings_percent:+.1f}%)"
    rows = []
    for pattern in patterns:
        finding = pattern.finding
        manual = finding.manual_fix
        pattern_verification = pattern.verification
        status = "MANUAL REVIEW" if manual else ("PASS" if pattern_verification and pattern_verification.passed else "FAIL")
        ok = manual or bool(pattern_verification and pattern_verification.passed)
        rows.append(
            f'''<article class="pattern">
              <div class="pattern-head"><h2>{html.escape(finding.pattern)} · {html.escape(finding.message)}</h2>{_badge(status, ok)}</div>
              <p class="meta">Line {finding.line}, column {finding.column} · Estimated saving: {finding.estimate_bytes if finding.estimate_bytes is not None else "n/a"} bytes/value</p>
              {_pattern_metrics(pattern)}
              <div class="code-grid"><section><h3>Before</h3>{_code_block(pattern.before)}</section><section><h3>After</h3>{_code_block(pattern.after)}</section></div>
              <h3>Diff</h3>{_diff(pattern.before, pattern.after)}
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
 .pattern-metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:14px 0}} .pattern-metrics>div{{background:#f6f8fb;border-radius:7px;padding:9px 10px}} .pattern-metrics strong,.pattern-metrics span{{display:block}} .pattern-metrics strong{{font-size:12px;color:#5f6368;text-transform:uppercase;letter-spacing:.04em}} .pattern-metrics span{{margin-top:3px;font-size:13px}} .pattern-metrics .status{{background:transparent;padding:0;display:flex;align-items:center;justify-content:flex-end}}
.badge{{border-radius:999px;padding:4px 10px;font-weight:700;font-size:12px;white-space:nowrap}} .pass{{background:#e6f4ea;color:#137333}} .fail{{background:#fce8e6;color:#c5221f}}
.meta{{color:#5f6368;font-size:13px}} pre{{background:#202124;color:#f8f9fa;padding:12px;border-radius:6px;overflow:auto;min-height:42px}} code{{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}}
table.diff{{width:100%;font:12px ui-monospace,monospace;border-collapse:collapse;overflow:auto;display:block}} .diff_header{{background:#e8eaed}} td{{padding:2px 5px;white-space:pre-wrap;vertical-align:top}} .diff_add{{background:#ceead6}} .diff_sub{{background:#f7caca}} .diff_chg{{background:#fce8b2}}
</style></head><body><main>
 <h1>FastFrame anti-pattern report</h1><p class="subtitle">{html.escape(source_path.name)} · deterministic rewrite and subprocess verification</p>
 <section class="summary">{_metric(len(findings), "patterns detected")}{_metric(f"{metrics.original.median_seconds:.4f}s", "original median")}{_metric(f"{metrics.rewritten.median_seconds:.4f}s", "rewritten median")}{_metric(speed, "speedup")}{_metric(memory, "peak memory change")}{_metric(verification_text, "result verification")}</section>
{''.join(rows)}
</main></body></html>'''


def main(argv: list[str] | None = None) -> int:
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
