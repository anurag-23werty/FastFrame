from pathlib import Path

from fastframe.report import render_report


def test_report_contains_summary_badges_and_highlighted_diff(tmp_path):
    source = tmp_path / "small.py"
    source.write_text(
        "import numpy as np\n"
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})\n"
        "out = df.apply(lambda row: row['a'] + row['b'], axis=1)\n"
        "scaled = df['a'].apply(lambda x: x * 2)\n"
        "values = []\n"
        "for _, row in df.iterrows():\n    values.append(row['a'] + row['b'])\n"
        "combined = df.iloc[:0]\n"
        "for chunk in [df.iloc[:1], df.iloc[1:]]:\n    combined = pd.concat([combined, chunk])\n"
        "arr = np.array([], dtype=float)\n"
        "for value in [1.0, 2.0]:\n    arr = np.append(arr, value)\n"
        "wide = df['a'].astype('int64')\n"
    )
    output = render_report(source, tmp_path / "index.html", runs=1)
    document = output.read_text()
    assert "speedup" in document
    assert "original median" in document and "rewritten median" in document
    assert "peak memory change" in document
    assert "AP001" in document and "AP006" in document
    assert document.count("Equivalent outputs") >= 5
    assert "Timing" in document and "Memory" in document
    assert "badge pass" in document or "badge fail" in document
    assert "diff_add" in document or "diff_sub" in document or "diff_chg" in document
