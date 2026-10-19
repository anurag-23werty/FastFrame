"""Deterministic subprocess benchmarks with isolated timing and memory runs."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

SUBPROCESS_TIMEOUT_SECONDS = 60

# Imports happen before the clock starts. The child also suppresses script stdout
# so a user's print statements cannot corrupt the one-line measurement protocol.
_TIME_CHILD = r'''
import io, runpy, sys, time
from contextlib import redirect_stdout
import numpy as np
import pandas as pd
started = time.perf_counter()
with redirect_stdout(io.StringIO()):
    runpy.run_path(sys.argv[1], run_name="__main__")
print(f"{time.perf_counter() - started:.12g}")
'''

_MEMORY_CHILD = r'''
import io, runpy, sys, tracemalloc
from contextlib import redirect_stdout
import numpy as np
import pandas as pd
tracemalloc.start()
with redirect_stdout(io.StringIO()):
    runpy.run_path(sys.argv[1], run_name="__main__")
_, peak = tracemalloc.get_traced_memory()
print(peak)
'''


@dataclass
class ScriptStats:
    median_seconds: float
    min_seconds: float
    peak_memory_bytes: int
    samples_seconds: List[float]
    samples_memory_bytes: List[int]


@dataclass
class BenchmarkResult:
    original: ScriptStats
    rewritten: ScriptStats
    speedup: float
    memory_savings_bytes: int
    memory_savings_percent: float

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _run_child(path: Path, program: str) -> str:
    try:
        proc = subprocess.run(
            [sys.executable, "-c", program, str(path)],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{path}: subprocess timed out after {SUBPROCESS_TIMEOUT_SECONDS}s") from exc
    if proc.returncode:
        raise RuntimeError(f"{path}: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout.strip()


def _sample(path: Path, runs: int) -> ScriptStats:
    # Warm up both measurement paths once, separately from reported samples.
    _run_child(path, _TIME_CHILD)
    _run_child(path, _MEMORY_CHILD)
    times = [float(_run_child(path, _TIME_CHILD)) for _ in range(runs)]
    memories = [int(_run_child(path, _MEMORY_CHILD)) for _ in range(runs)]
    return ScriptStats(statistics.median(times), min(times), max(memories), times, memories)


def benchmark(original: str | Path, rewritten: str | Path, *, runs: int = 5) -> BenchmarkResult:
    """Return median/min runtime and peak tracemalloc memory for each script."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    before, after = _sample(Path(original), runs), _sample(Path(rewritten), runs)
    savings = before.peak_memory_bytes - after.peak_memory_bytes
    return BenchmarkResult(
        before,
        after,
        before.median_seconds / after.median_seconds if after.median_seconds else float("inf"),
        savings,
        (savings / before.peak_memory_bytes * 100) if before.peak_memory_bytes else 0.0,
    )


bench = benchmark


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="benchmark two FastFrame scripts")
    parser.add_argument("original")
    parser.add_argument("rewritten")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args(argv)
    print(json.dumps(benchmark(args.original, args.rewritten, runs=args.runs).as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
