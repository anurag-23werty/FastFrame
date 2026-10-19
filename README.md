# FastFrame

FastFrame is an offline, deterministic analyzer for common slow pandas and
NumPy patterns. It detects source-level anti-patterns, rewrites supported
forms with LibCST, and verifies or benchmarks two scripts.

## Setup

Python 3.12 and `uv` are required. Dependencies are pinned by `uv.lock`.

```bash
uv sync --extra test
```

## Test

```bash
make test
```

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
docker run --rm fastframe
```

The CLI surface and HTML reporting are scheduled for the next implementation
step; the current commit contains the tested detection, rewrite, verification,
and benchmarking core.
