"""Small, deterministic subprocess benchmark for FastFrame scripts."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

_CHILD = r'''
import io, runpy, sys, time, tracemalloc
from contextlib import redirect_stdout
tracemalloc.start()
started = time.perf_counter()
with redirect_stdout(io.StringIO()):
    runpy.run_path(sys.argv[1], run_name="__main__")
elapsed = time.perf_counter() - started
_, peak = tracemalloc.get_traced_memory()
print(f"{elapsed:.12g} {peak}")
'''


@dataclass
class ScriptStats:
    median_seconds: float
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


def _sample(path: Path, runs: int) -> ScriptStats:
    times, memories = [], []
    for _ in range(runs):
        proc = subprocess.run([sys.executable, "-c", _CHILD, str(path)], capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(f"{path}: {proc.stderr.strip() or proc.returncode}")
        try:
            elapsed, peak = proc.stdout.strip().split()
            times.append(float(elapsed)); memories.append(int(peak))
        except ValueError as exc:
            raise RuntimeError(f"{path}: malformed benchmark output") from exc
    return ScriptStats(statistics.median(times), max(memories), times, memories)


def benchmark(original: str | Path, rewritten: str | Path, *, runs: int = 5) -> BenchmarkResult:
    """Return median runtime and peak tracemalloc memory for each script."""
    if runs < 1:
        raise ValueError("runs must be at least 1")
    before, after = _sample(Path(original), runs), _sample(Path(rewritten), runs)
    savings = before.peak_memory_bytes - after.peak_memory_bytes
    return BenchmarkResult(before, after, before.median_seconds / after.median_seconds if after.median_seconds else float("inf"), savings, (savings / before.peak_memory_bytes * 100) if before.peak_memory_bytes else 0.0)


bench = benchmark


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="benchmark two FastFrame scripts")
    parser.add_argument("original"); parser.add_argument("rewritten"); parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args(argv)
    print(json.dumps(benchmark(args.original, args.rewritten, runs=args.runs).as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
