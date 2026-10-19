# FastFrame

FastFrame is an offline, deterministic analyzer for common slow pandas and
NumPy patterns. It detects source-level anti-patterns, rewrites supported
forms with LibCST, and verifies or benchmarks two scripts.

## Setup

Python 3.12 and `uv` are required. Dependencies are pinned by `uv.lock`.

```bash
uv sync --locked --extra test
```

## Test

```bash
make test
```

The test command is offline-safe after setup: it uses the already-installed
locked environment and does not resolve or download packages.

## Current core APIs

```python
from fastframe.detect import detect
from fastframe.rewrite import rewrite
from fastframe.verify import verify_scripts
from fastframe.bench import benchmark
```

All analysis and execution is local; no network or LLM calls are used.

## Docker

```bash
docker build -t fastframe .
docker run --rm --network none fastframe make test
```

The CLI supports `scan`, `fix`, `verify`, `bench`, and `report`; for example:

```bash
uv run fastframe report examples/sales_analysis_slow.py --html docs/index.html
```
