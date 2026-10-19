"""FastFrame source analysis and safe, deterministic pandas rewrites."""

from .antipatterns import Finding, detect, detect_antipatterns, rewrite, rewrite_source
from .bench import BenchmarkResult, ScriptStats, bench, benchmark
from .verify import VariableComparison, VerificationResult, verify, verify_scripts

__all__ = [
    "Finding", "detect", "detect_antipatterns", "rewrite", "rewrite_source",
    "VerificationResult", "VariableComparison", "verify", "verify_scripts",
    "BenchmarkResult", "ScriptStats", "bench", "benchmark",
]
