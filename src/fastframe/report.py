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
        if finding.manual_fix:
            before = _snippet(source, finding)
            results.append(PatternResult(finding, before, before, None, None))
            continue
        counts[finding.pattern] = counts.get(finding.pattern, 0) + 1
        focused_path = source_path.parent / "patterns" / f"{finding.pattern.lower()}.py"
        focused_source_path = focused_path if focused_path.exists() else source_path
        focused_source = focused_source_path.read_text(encoding="utf-8")
        focused_findings = detect(focused_source)
        focused_finding = next((item for item in focused_findings if item.pattern == finding.pattern), finding)
        before = _snippet(focused_source, focused_finding)
        rewritten = rewrite(focused_source, pattern=finding.pattern, occurrence=counts[finding.pattern])
        candidate = temp / f"{focused_source_path.stem}-{finding.pattern.lower()}-{counts[finding.pattern]}{focused_source_path.suffix}"
        candidate.write_text(rewritten, encoding="utf-8")
        results.append(
            PatternResult(
                focused_finding,
                before,
                _snippet(rewritten, focused_finding),
                verify_scripts(focused_source_path, candidate),
                benchmark(focused_source_path, candidate, runs=runs),
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
 body{{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#202124;background:linear-gradient(135deg,#f7f9fc 0%,#eef4ff 50%,#f8f5ff 100%);margin:0}}
 main{{max-width:1180px;margin:0 auto;padding:32px 22px}} h1{{margin:0 0 4px;color:#172554}} h2{{font-size:18px;margin:0}} h3{{font-size:14px;color:#5f6368}}
 .subtitle{{color:#5f6368;margin:0 0 12px}} .hero-tags{{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 24px}} .hero-tag{{border-radius:999px;padding:4px 10px;font-size:12px;font-weight:700;color:#fff;background:#2563eb}} .hero-tag:nth-child(2){{background:#7c3aed}} .hero-tag:nth-child(3){{background:#059669}} .hero-tag:nth-child(4){{background:#ea580c}}
 .summary,.code-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
 .metric,.pattern{{background:#fff;border:1px solid #dbe3f0;border-radius:12px;padding:16px;box-shadow:0 8px 24px #1e3a8a12}}
 .quickstart{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:0 0 18px}} .quickstart-card{{background:#172554;color:#eff6ff;border-radius:12px;padding:14px 16px}} .quickstart-card h2{{font-size:15px;margin:0 0 7px}} .quickstart-card code{{display:block;color:#bfdbfe;font-size:12px;white-space:pre-wrap}}
 .metric strong{{display:block;font-size:23px}} .metric span{{color:#5f6368}} .pattern{{margin-top:18px}} .pattern-head{{display:flex;align-items:center;justify-content:space-between;gap:10px}}
 .pattern-metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:14px 0}} .pattern-metrics>div{{background:#f6f8fb;border-radius:7px;padding:9px 10px}} .pattern-metrics strong,.pattern-metrics span{{display:block}} .pattern-metrics strong{{font-size:12px;color:#5f6368;text-transform:uppercase;letter-spacing:.04em}} .pattern-metrics span{{margin-top:3px;font-size:13px}} .pattern-metrics .status{{background:transparent;padding:0;display:flex;align-items:center;justify-content:flex-end}}
.badge{{border-radius:999px;padding:4px 10px;font-weight:700;font-size:12px;white-space:nowrap}} .pass{{background:#e6f4ea;color:#137333}} .fail{{background:#fce8e6;color:#c5221f}}
.meta{{color:#5f6368;font-size:13px}} pre{{background:#202124;color:#f8f9fa;padding:12px;border-radius:6px;overflow:auto;min-height:42px}} code{{font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}}
table.diff{{width:100%;font:12px ui-monospace,monospace;border-collapse:collapse;overflow:auto;display:block}} .diff_header{{background:#e8eaed}} td{{padding:2px 5px;white-space:pre-wrap;vertical-align:top}} .diff_add{{background:#ceead6}} .diff_sub{{background:#f7caca}} .diff_chg{{background:#fce8b2}}
 </style></head><body><main>
 <h1>FastFrame anti-pattern report</h1><p class="subtitle">{html.escape(source_path.name)} · deterministic rewrite and subprocess verification</p><div class="hero-tags"><span class="hero-tag">Pandas</span><span class="hero-tag">NumPy</span><span class="hero-tag">Safe rewrites</span><span class="hero-tag">Benchmarked</span></div><section class="quickstart"><div class="quickstart-card"><h2>🐼 Install from PyPI</h2><code>python -m pip install fastframe-pandas pandas numpy
 fastframe scan my_script.py</code></div><div class="quickstart-card"><h2>🐳 Run with Docker</h2><code>docker build -t fastframe:latest .
 docker run --rm --network none -v "$PWD":/workspace -w /workspace fastframe:latest scan my_script.py</code></div></section>
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
