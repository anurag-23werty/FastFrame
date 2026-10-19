from fastframe import detect, rewrite

UNSAFE_CASES = [
    'df["a"].apply(lambda s: len(s) * 2);\n',
    'df["a"].apply(lambda x: math.sqrt(x) + 1);\n',
    'df["a"].apply(lambda x: x * 2 if x > 0 else 0);\n',
    'df.groupby("k")["v"].apply(lambda x: x - x.mean());\n',
    'df["a"].rolling(3).apply(lambda x: x * 2);\n',
    'for c in chunks:\n    df = pd.concat([c, df]);\n',
    'for f in files:\n    df = pd.concat([base, f]);\n',
    'for v in vals:\n    arr = np.append(base, v);\n',
    'for v in vals:\n    arr = np.append(arr, v, axis=0);\n',
    'for i, row in df.iterrows():\n    out.append(row["a"] * i)\n',
]


def test_unsafe_cases_are_never_rewritten_or_automatically_fitted():
    for source in UNSAFE_CASES:
        assert rewrite(source) == source
        findings = detect(source)
        assert all(f.manual_fix for f in findings), (source, findings)


def test_positions_use_each_duplicate_node_not_first_text_match():
    source = (
        'a = df["a"].apply(lambda x: x * 2)\n'
        'b = df["a"].apply(lambda x: x * 2)\n'
    )
    findings = detect(source)
    assert [(f.pattern, f.line, f.column) for f in findings] == [
        ("AP002", 1, 4),
        ("AP002", 2, 4),
    ]
