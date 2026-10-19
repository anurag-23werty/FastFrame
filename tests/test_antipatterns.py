from fastframe import detect, rewrite


def test_rowwise_apply_is_detected_and_vectorized():
    source = 'out = df.apply(lambda row: row["a"] + row["b"], axis=1)\n'
    assert [f.pattern for f in detect(source)] == ["AP001"]
    assert rewrite(source) == 'out = df["a"] + df["b"]\n'


def test_series_apply_arithmetic_is_detected_and_vectorized():
    source = 'out = df["a"].apply(lambda value: value * 2)\n'
    assert [f.pattern for f in detect(source)] == ["AP002"]
    assert rewrite(source) == 'out = df["a"] * 2\n'


def test_iterrows_append_is_replaced_with_extend():
    source = 'for _, row in df.iterrows():\n    values.append(row["a"] + row["b"])\n'
    assert [f.pattern for f in detect(source)] == ["AP003"]
    assert rewrite(source) == 'values.extend((df["a"] + df["b"]).tolist())\n'


def test_unrelated_apply_is_unchanged():
    source = 'out = df.apply(func)\n'
    assert detect(source) == []
    assert rewrite(source) == source


def test_concat_growth_loop_is_collected_and_concatenated_once():
    source = "for chunk in chunks:\n    df = pd.concat([df, chunk], ignore_index=True)\n"
    assert [f.pattern for f in detect(source)] == ["AP004"]
    assert rewrite(source) == (
        "_fastframe_parts = [df]\n"
        "for chunk in chunks:\n"
        "    _fastframe_parts.append(chunk)\n"
        "df = pd.concat(_fastframe_parts, ignore_index=True)\n"
    )


def test_np_append_growth_loop_is_rewritten():
    source = "for value in values:\n    arr = np.append(arr, value)\n"
    assert [f.pattern for f in detect(source)] == ["AP005"]
    assert rewrite(source) == (
        "_fastframe_parts = [arr]\n"
        "for value in values:\n"
        "    _fastframe_parts.append(value)\n"
        "arr = np.concatenate(_fastframe_parts)\n"
    )


def test_downcastable_dtype_is_report_only_and_unchanged():
    source = 'df["count"] = df["count"].astype("int64")\n'
    findings = detect(source)
    assert [f.pattern for f in findings] == ["AP006"]
    assert findings[0].manual_fix is True
    assert findings[0].estimate_bytes == 4
    assert rewrite(source) == source
