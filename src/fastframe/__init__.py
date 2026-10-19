"""FastFrame source analysis and safe, deterministic pandas rewrites."""

from .antipatterns import Finding, detect, detect_antipatterns, rewrite, rewrite_source
from .verify import VerificationResult, VariableComparison, verify, verify_scripts
from .bench import BenchmarkResult, ScriptStats, bench, benchmark

__all__ = [
    "Finding", "detect", "detect_antipatterns", "rewrite", "rewrite_source",
    "VerificationResult", "VariableComparison", "verify", "verify_scripts",
    "BenchmarkResult", "ScriptStats", "bench", "benchmark",
]
