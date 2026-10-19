# FastFrame

[![CI](https://github.com/anurag-23werty/FastFrame/actions/workflows/ci.yml/badge.svg)](https://github.com/anurag-23werty/FastFrame/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-94.34%25-brightgreen)](https://github.com/anurag-23werty/FastFrame/actions/workflows/ci.yml)

> FastFrame finds slow pandas/NumPy idioms, rewrites only safe patterns deterministically, and proves equivalence before reporting performance.

## Problem

Row-wise `apply`, `iterrows`, repeated DataFrame concatenation, and repeated
`np.append` hide vectorizable work behind Python loops or repeated allocation.
FastFrame scans Python files, directories, and notebook code cells; applies
conservative LibCST rewrites; executes both versions in subprocesses; and
compares their results and stdout. Runtime has no LLM or network dependency.

## Install

### uv

```bash
uv sync --locked --extra test
```

Real output from this repository:

```text
Resolved 31 packages in 29ms
Checked 30 packages in 13ms
```

### Docker

```bash
docker build -t fastframe:buildathon .
```

The image runs as non-root user `fastframe` and has `fastframe` as its
entrypoint. Run a scan with:

```bash
docker run --rm --network none fastframe:buildathon scan examples/sales_analysis_slow.py
```

Run the complete offline test command by overriding the CLI entrypoint:

```bash
docker run --rm --network none --entrypoint make fastframe:buildathon test
```

## Terminal demo

```text
$ uv run fastframe scan examples/sales_analysis_slow.py
┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Location             ┃ Pattern ┃ Explanation          ┃ Suggested action     ┃
┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ examples/sales_anal… │ AP001   │ row-wise             │ vectorize with       │
│                      │         │ DataFrame.apply      │ fastframe fix        │
│                      │         │ arithmetic           │                      │
│ examples/sales_anal… │ AP002   │ Series.apply         │ vectorize with       │
│                      │         │ arithmetic lambda    │ fastframe fix        │
│ examples/sales_anal… │ AP003   │ iterrows arithmetic  │ vectorize with       │
│                      │         │ append-to-list       │ fastframe fix        │
│ examples/sales_anal… │ AP004   │ growing DataFrame    │ vectorize with       │
│                      │         │ with concat/append   │ fastframe fix        │
│                      │         │ in a loop            │                      │
│ examples/sales_anal… │ AP005   │ growing NumPy array  │ vectorize with       │
│                      │         │ with np.append in a  │ fastframe fix        │
│                      │         │ loop                 │                      │
│ examples/sales_anal… │ AP006   │ downcastable         │ manual review        │
│                      │         │ object/int64/float64 │                      │
│                      │         │ column (manual       │                      │
│                      │         │ review)              │                      │
└──────────────────────┴─────────┴──────────────────────┴──────────────────────┘
EXIT_CODE=1

$ uv run fastframe fix examples/sales_analysis_slow.py -o build/sales_fast.py
Verification passed.
--- examples/sales_analysis_slow.py
+++ build/sales_fast.py
@@
-row_totals = work.apply(lambda row: row["units"] * row["price"], axis=1)
+row_totals = work["units"] * work["price"]
```

## CLI

### Scan

Scan a file, directory recursively, or notebook code cells:

```bash
uv run fastframe scan examples/sales_analysis_slow.py
uv run fastframe scan src --format json
```

`scan --format json` emits machine-readable findings and exits `1` when any
finding exists, otherwise `0`.

Inline suppressions are supported:

```python
out = df["a"].apply(lambda x: x * 2)  # fastframe: ignore
out = df["b"].apply(lambda x: x * 2)  # fastframe: ignore[AP002]
```

Project configuration lives in `pyproject.toml`:

```toml
[tool.fastframe]
select = ["AP001", "AP002"]
ignore = ["AP006"]
```

### Fix

Fix verifies by default and refuses to write if verification fails:

```bash
uv run fastframe fix examples/sales_analysis_slow.py -o build/sales_fast.py
uv run fastframe fix examples/sales_analysis_slow.py --diff
uv run fastframe fix examples/sales_analysis_slow.py --in-place
uv run fastframe fix examples/sales_analysis_slow.py -o build/sales_fast.py --no-verify
```

`--in-place` keeps `sales_analysis_slow.py.bak`. `--no-verify` prints a warning.
Notebook fixes write rewritten code cells to a copy; Markdown cells are kept.

### Verify

```bash
uv run fastframe verify examples/sales_analysis_slow.py build/sales_fast.py
uv run fastframe verify examples/sales_analysis_slow.py build/sales_fast.py --json
```

Real readable output:

```text
PASS verification
┏━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┓
┃ Variable     ┃ Status ┃ Details    ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━┩
│ amounts      │ PASS   │ equivalent │
│ combined     │ PASS   │ equivalent │
│ row_totals   │ PASS   │ equivalent │
│ scaled_units │ PASS   │ equivalent │
│ values       │ PASS   │ equivalent │
└──────────────┴────────┴────────────┘
stdout: PASS
```

Verification reports original variables missing from the rewritten script as
failures, compares captured stdout, uses the original script directory for
relative paths and `__file__`, and has a 60-second subprocess timeout.

### Bench

```bash
uv run fastframe bench examples/sales_analysis_slow.py build/sales_fast.py --runs 1
uv run fastframe bench examples/sales_analysis_slow.py build/sales_fast.py --runs 1 --json
```

Real output from one run on the 200k-row example:

```text
┏━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Script    ┃ Median  ┃ Minimum ┃ Peak memory      ┃
┡━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ Original  │ 0.2990s │ 0.2990s │ 22,755,587 bytes │
│ Rewritten │ 0.0226s │ 0.0226s │ 22,753,696 bytes │
└───────────┴─────────┴─────────┴──────────────────┘
Speedup: 13.22x
Peak memory saved: +1,891 bytes (+0.01%)
```

Timing and memory are measured in separate child runs. Imports happen before
timing, and each measurement path gets one warm-up run.

### Report, rules, and explain

```bash
uv run fastframe report examples/sales_analysis_slow.py --html docs/index.html --runs 1
uv run fastframe rules
uv run fastframe explain AP003
```

`report` writes a self-contained HTML report. `rules` lists every built-in
rule. `explain AP003` prints its explanation and representative before/after.

## Supported rules

### AP001 — row-wise DataFrame arithmetic

```python
# Before
out = df.apply(lambda row: row["a"] + row["b"], axis=1)
# After
out = df["a"] + df["b"]
```

### AP002 — arithmetic Series lambda

```python
# Before
out = df["a"].apply(lambda x: x * 2)
# After
out = df["a"] * 2
```

### AP003 — `iterrows()` arithmetic append

```python
# Before
for _, row in df.iterrows():
    out.append(row["a"] + row["b"])
# After
out.extend((df["a"] + df["b"]).tolist())
```

### AP004 — DataFrame concat growth

```python
# Before
for chunk in chunks:
    df = pd.concat([df, chunk], ignore_index=True)
# After
_fastframe_df_parts = [df]
for chunk in chunks:
    _fastframe_df_parts.append(chunk)
if len(_fastframe_df_parts) > 1:
    df = pd.concat(_fastframe_df_parts, ignore_index=True)
```

### AP005 — `np.append` growth

```python
# Before
for value in values:
    arr = np.append(arr, value)
# After
_fastframe_arr_parts = [arr]
for value in values:
    _fastframe_arr_parts.append(np.atleast_1d(value))
if len(_fastframe_arr_parts) > 1:
    arr = np.concatenate(_fastframe_arr_parts)
```

### AP006 — downcast advisory

```python
# Finding; not automatically rewritten
df["count"] = df["count"].astype("int64")
# Manual review suggestion
df["count"] = pd.to_numeric(df["count"], downcast="integer")
```

## Results: 200k-row example

`examples/sales_analysis_slow.py` creates 200,000 rows with seeded RNG
`np.random.default_rng(2026)`. The report applies one finding at a time and
uses one benchmark run for the following captured local results:

| Pattern | Speedup | Verification |
|---|---:|:---:|
| AP001 row-wise apply | 1.15× | PASS |
| AP002 Series apply | 1.00× | PASS |
| AP003 iterrows append | 2.65× | PASS |
| AP004 concat growth | 1.00× | PASS |
| AP005 `np.append` growth | 0.99× | PASS |
| AP006 downcast advisory | advisory only | manual review |

Benchmarks include subprocess execution and are machine/load dependent. The
HTML report contains the complete per-pattern timing, memory, code, diff, and
badge details.

## Safety guarantees

- Only a strict arithmetic whitelist is rewritten: string-literal parameter
  subscripts, permitted bare parameters, numeric constants, unary minus, and
  `+ - * / // ** %`.
- Calls involving `groupby`, `rolling`, `resample`, `expanding`, or `ewm` are
  never automatically rewritten.
- `pd.concat` rewrites require exactly `[target, piece]`.
- `np.append` rewrites require the target as the first argument and reject
  `axis`.
- `iterrows` rewrites require `_` as the index variable; index-dependent
  expressions are never rewritten.
- AP006 is always advisory because safe downcasting depends on values,
  nullability, precision, and downstream consumers.
- Rewrites preserve source formatting with LibCST and `fix` verifies before
  writing by default.

## Limitations & security

- `verify` and `bench` execute both supplied scripts with `runpy` in child
  processes. They are not a security sandbox.
- Do **not** run untrusted scripts with FastFrame. Use a container or another
  sandbox with restricted filesystem, network, CPU, and memory access.
- Verification compares matching top-level DataFrame, Series, ndarray, and
  list variables plus exact captured stdout. External side effects, databases,
  files, and network behavior are not equivalence guarantees.
- Benchmarks measure complete script execution after imports, not an isolated
  function microbenchmark.
- Unknown source shapes are reported only when recognized; no speculative
  rewrite is attempted.

## Tests and quality

```bash
make test
uv run --no-sync ruff check .
uv run --no-sync mypy
```

Real local result:

```text
82 passed
Required test coverage of 90% reached. Total coverage: 94.34%
```

GitHub Actions runs Ruff, mypy, coverage tests, Docker build, and the offline
Docker test on pushes and pull requests.

## Live demo

[Open the FastFrame GitHub Pages report](https://anurag-23werty.github.io/FastFrame/)
