from pathlib import Path

from fastframe.report import render_report


ROOT = Path(__file__).parents[1]


def test_report_contains_summary_badges_and_highlighted_diff(tmp_path):
    output = render_report(ROOT / "examples/sales_analysis_slow.py", tmp_path / "index.html", runs=1)
    document = output.read_text()
    assert "speedup" in document
    assert "original median" in document and "rewritten median" in document
    assert "peak memory change" in document
    assert "AP001" in document and "AP006" in document
    assert document.count("Equivalent outputs") >= 5
    assert "Timing" in document and "Memory" in document
    assert "badge pass" in document or "badge fail" in document
    assert "diff_add" in document or "diff_sub" in document or "diff_chg" in document
