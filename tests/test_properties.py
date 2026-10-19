"""Bounded, reproducible equivalence checks without starting child interpreters."""

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from fastframe import detect, rewrite

property_check = settings(max_examples=35, derandomize=True, database=None, deadline=None)


@st.composite
def numeric_frames(draw, *, min_rows=0):
    size = draw(st.integers(min_value=min_rows, max_value=20))
    dtype = draw(st.sampled_from(["int64", "float64"]))
    rows = draw(st.lists(st.tuples(st.integers(-100, 100), st.integers(-100, 100)), min_size=size, max_size=size))
    values = np.asarray(rows, dtype=dtype).reshape(size, 2)
    if dtype == "float64":
        values /= 4  # Binary-exact fractions keep strict equality meaningful.
    index = pd.Index(draw(st.lists(st.integers(-5, 5), min_size=size, max_size=size)), name="sample")
    return pd.DataFrame(values, columns=["a", "b"], index=index)


def execute_pair(source, rule, make_namespace):
    assert [finding.pattern for finding in detect(source)] == [rule]
    optimized = rewrite(source)
    assert optimized != source
    assert rewrite(optimized) == optimized
    before, after = make_namespace(), make_namespace()
    exec(compile(source, "<original>", "exec"), before)
    exec(compile(optimized, "<rewritten>", "exec"), after)
    return before, after


@property_check
@given(numeric_frames(min_rows=1), st.sampled_from(["row['a'] + row['b']", "row['a'] - row['b']", "row['a'] * row['b']", "-(row['a'] + row['b'])", "(row['a'] + row['b']) / 2"]))
def test_ap001_row_apply_equivalence(frame, expression):
    before, after = execute_pair(f"out = df.apply(lambda row: {expression}, axis=1)\n", "AP001", lambda: {"df": frame.copy(deep=True)})
    pd.testing.assert_series_equal(before["out"], after["out"], check_exact=True)
    pd.testing.assert_frame_equal(before["df"], after["df"], check_exact=True)


@property_check
@given(numeric_frames(), st.sampled_from(["x + 3", "x - 2", "x * 2", "x / 2", "x ** 2", "x % 3", "x // 3", "-x"]))
def test_ap002_series_apply_equivalence(frame, expression):
    before, after = execute_pair(f"out = df['a'].apply(lambda x: {expression})\n", "AP002", lambda: {"df": frame.copy(deep=True)})
    pd.testing.assert_series_equal(before["out"], after["out"], check_exact=True)


@property_check
@given(numeric_frames(), st.sampled_from(["row['a'] + row['b']", "row['a'] * row['b']", "(row['a'] - row['b']) / 2"]))
def test_ap003_iterrows_equivalence_preserves_prefix_and_final_row(frame, expression):
    source = f"for _, row in df.iterrows():\n    out.append({expression})\n"
    before, after = execute_pair(source, "AP003", lambda: {"df": frame.copy(deep=True), "out": [7]})
    np.testing.assert_array_equal(np.asarray(before["out"]), np.asarray(after["out"]), strict=True)
    if len(frame):
        pd.testing.assert_series_equal(before["row"], after["row"], check_exact=True)
    else:
        assert "row" not in before and "row" not in after


@property_check
@given(numeric_frames(), st.integers(1, 4), st.booleans())
def test_ap004_concat_equivalence(frame, chunk_count, ignore_index):
    source = f"for chunk in chunks:\n    df = pd.concat([df, chunk], ignore_index={ignore_index})\n"
    chunks = [frame.iloc[i::chunk_count].copy() for i in range(chunk_count)]
    before, after = execute_pair(source, "AP004", lambda: {"pd": pd, "df": frame.copy(deep=True), "chunks": [chunk.copy() for chunk in chunks]})
    pd.testing.assert_frame_equal(before["df"], after["df"], check_exact=True)


def test_ap004_zero_iterations_preserves_original_index():
    frame = pd.DataFrame({"a": [1]}, index=pd.Index([42], name="sample"))
    source = "for chunk in chunks:\n    df = pd.concat([df, chunk], ignore_index=True)\n"
    before, after = execute_pair(source, "AP004", lambda: {"pd": pd, "df": frame.copy(), "chunks": []})
    pd.testing.assert_frame_equal(before["df"], after["df"], check_exact=True)


@property_check
@given(numeric_frames(), st.booleans())
def test_ap005_numpy_append_equivalence(frame, array_pieces):
    source = "for value in values:\n    arr = np.append(arr, value)\n"
    values = [np.array([value], dtype=frame["b"].dtype) if array_pieces else value for value in frame["b"]]
    before, after = execute_pair(source, "AP005", lambda: {"np": np, "arr": frame["a"].to_numpy(copy=True), "values": values})
    np.testing.assert_array_equal(before["arr"], after["arr"], strict=True)


@property_check
@given(numeric_frames(), st.sampled_from(["int64", "float64", "object"]))
def test_ap006_is_advisory_and_never_rewritten(frame, dtype):
    source = f"out = df.astype('{dtype}')\n"
    findings = detect(source)
    assert len(findings) == 1 and findings[0].pattern == "AP006"
    assert findings[0].manual_fix
    assert rewrite(source) == source
    before, after = {"df": frame.copy()}, {"df": frame.copy()}
    exec(source, before)
    exec(rewrite(source), after)
    pd.testing.assert_frame_equal(before["out"], after["out"], check_exact=True)
