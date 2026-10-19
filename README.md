# FastFrame

> **One-line pitch:** FastFrame finds slow pandas/NumPy idioms, rewrites the safe ones deterministically, and proves the result before reporting performance.

## The problem

Row-wise `apply`, `iterrows`, repeated concatenation, and repeated
`np.append` are easy to write and expensive to run. They hide vectorizable
work behind Python loops or repeatedly reallocate memory. FastFrame is a
small, offline-first CLI for finding those patterns in a Python script,
applying conservative LibCST transforms that preserve formatting, and
checking the rewritten script with real subprocess execution. There are no
runtime LLM calls.

## Terminal demo

The following is the GIF-style terminal sequence used in the demo:

```text
$ uv sync --locked --extra test
Resolved 21 packages

$ uv run fastframe scan examples/sales_analysis_slow.py
┏━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Pattern ┃ Line ┃ Explanation                                          ┃
┡━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ AP001   │ 13   │ row-wise DataFrame.apply arithmetic                  │
│ AP002   │ 14   │ Series.apply arithmetic lambda                       │
│ AP003   │ 17   │ iterrows arithmetic append-to-list                   │
│ AP004   │ 21   │ growing DataFrame with concat/append in a loop        │
│ AP005   │ 25   │ growing NumPy array with np.append in a loop          │
│ AP006   │ 28   │ downcastable object/int64/float64 column (manual...)  │
└─────────┴──────┴───────────────────────────────────────────────────────┘

$ uv run fastframe fix examples/sales_analysis_slow.py -o /tmp/sales_fast.py
--- examples/sales_analysis_slow.py
+++ /tmp/sales_fast.py
@@
-row_totals = df.apply(lambda row: row["units"] * row["price"], axis=1)
+row_totals = df["units"] * df["price"]

$ uv run fastframe verify examples/sales_analysis_slow.py /tmp/sales_fast.py
PASS: matching DataFrame, Series, ndarray, and list variables

$ uv run fastframe bench examples/sales_analysis_slow.py /tmp/sales_fast.py
speedup: 1.00x    peak memory saved: 0 bytes

$ uv run fastframe report examples/sales_analysis_slow.py --html docs/index.html
Wrote docs/index.html
```

## Install

### With Docker

Build the reproducible Python 3.12 image:

```bash
docker build -t fastframe:buildathon .
```

Run the CLI from the files copied into the image:

```bash
docker run --rm --network none fastframe:buildathon \
  scan examples/sales_analysis_slow.py
```

Run the complete offline test command:

```bash
docker run --rm --network none --entrypoint make fastframe:buildathon test
```

### With uv

Python 3.12 and `uv` are required. The lockfile pins application and test
dependencies:

```bash
uv sync --locked --extra test
```

After setup, all commands are local and do not need network access. Prefix
commands with `uv run`, or activate `.venv` first.

## CLI commands

All paths below are relative to the repository root.

### `scan`

List supported anti-patterns with line numbers and suggested actions:

```bash
uv run fastframe scan examples/sales_analysis_slow.py
```

### `fix`

Write a rewritten script and print a unified diff:

```bash
uv run fastframe fix examples/sales_analysis_slow.py -o build/sales_fast.py
```

### `verify`

Run both scripts in isolated subprocesses with `runpy`, then compare matching
top-level DataFrame, Series, ndarray, and list variables:

```bash
uv run fastframe verify examples/sales_analysis_slow.py build/sales_fast.py
```

The command exits non-zero on execution errors, missing matching variables, or
any comparison failure.

### `bench`

Measure median runtime and peak `tracemalloc` memory. Increase the sample
count for a steadier local measurement:

```bash
uv run fastframe bench examples/sales_analysis_slow.py build/sales_fast.py --runs 7
```

### `report`

Run scan, rewrite, verify, and benchmark, then write a self-contained HTML
report with summary metrics, before/after code, highlighted diffs, timings,
and per-pattern badges:

```bash
uv run fastframe report examples/sales_analysis_slow.py --html docs/index.html
```

## Supported anti-patterns

### 1. Row-wise DataFrame arithmetic

```python
# Before
out = df.apply(lambda row: row["a"] + row["b"], axis=1)

# After
out = df["a"] + df["b"]
```

### 2. Arithmetic Series lambda

```python
# Before
out = df["a"].apply(lambda value: value * 2)

# After
out = df["a"] * 2
```

### 3. `iterrows()` appending an arithmetic expression

```python
# Before
values = []
for _, row in df.iterrows():
    values.append(row["a"] + row["b"])

# After
values = []
values.extend((df["a"] + df["b"]).tolist())
```

### 4. Growing a DataFrame inside a loop

```python
# Before
for chunk in chunks:
    df = pd.concat([df, chunk], ignore_index=True)

# After
_fastframe_df_parts = [df]
for chunk in chunks:
    _fastframe_df_parts.append(chunk)
df = pd.concat(_fastframe_df_parts, ignore_index=True)
```

### 5. `np.append` inside a loop

```python
# Before
for value in values:
    arr = np.append(arr, value)

# After
_fastframe_arr_parts = [arr]
for value in values:
    _fastframe_arr_parts.append(np.atleast_1d(value))
arr = np.concatenate(_fastframe_arr_parts)
```

### 6. Downcastable dtypes (report-only)

```python
# Before / advisory finding
df["count"] = df["count"].astype("int64")

# Suggested manual review, not an automatic rewrite
df["count"] = pd.to_numeric(df["count"], downcast="integer")
```

AP006 is intentionally report-only because safe downcasting depends on actual
values, nullability, precision requirements, and downstream consumers.

## Example results

These are representative local measurements using three benchmark runs. The
benchmark launches each script in a fresh subprocess, so operating-system and
machine load can move the numbers. Positive memory saving means the rewritten
script used fewer traced bytes.

| Example comparison | Speedup | Peak memory saving | Verified |
|---|---:|---:|:---:|
| `examples/baseline.py` → `examples/vectorized.py` | 0.99× | 556 bytes (0.01%) | ✅ |
| `examples/sales_analysis_slow.py` → generated rewrite | 1.00× | 2,185 bytes (0.01%) | ✅ |

The small committed examples are correctness fixtures, not production-scale
performance claims. The report includes the actual timings measured on the
machine that generated it.

## Tests

Run the one supported test command:

```bash
make test
```

The same test command works inside the reproducible image without network
access:

```bash
docker run --rm --network none --entrypoint make fastframe:buildathon test
```

The image runs as the non-root `fastframe` user and defaults to the FastFrame
CLI. Override its entrypoint to run `make test`. Dependencies are installed at
build time; tests need no network or host virtual environment.

`make test` includes Hypothesis equivalence checks for the rewrite rules and
statement/branch coverage, enforcing a **90% minimum total coverage**. Quality
checks use the locked test dependencies:

```bash
uv run --no-sync ruff check .
uv run --no-sync mypy
```

GitHub Actions runs these checks, coverage tests, the Docker build, and the
network-disabled container test on pushes and pull requests.

## Limitations

- Rewrites are deliberately conservative and only cover the documented source
  shapes. Unrecognized code is left unchanged rather than guessed at.
- `AP006` is advisory only; FastFrame does not automatically change dtypes.
- Verification compares matching top-level DataFrame, Series, ndarray, and
  list variables. Side effects, external files, databases, and network calls
  are outside the verification model.
- Benchmarks preload pandas/NumPy, then time script execution without memory
  tracing. Memory is measured in separate child runs. Use a larger real workload
  and more runs before making performance decisions.
- Scripts must be safe to execute locally; `verify` and `bench` execute the
  supplied files.
- The current examples are intentionally small. They demonstrate behavior and
  deterministic rewrites, not a universal speedup guarantee.

## Live demo

The self-contained report is published from `docs/index.html` with GitHub
Pages:

**[Open the FastFrame live demo](https://anurag-23werty.github.io/FastFrame/)**
