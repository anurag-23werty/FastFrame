"""Execute and compare FastFrame example scripts in isolated subprocesses.

The child process uses :func:`runpy.run_path`, so scripts are tested exactly as
they would be run by Python while keeping their globals out of the test runner.
Only top-level pandas objects, NumPy arrays, and lists are returned.
"""

from __future__ import annotations

import argparse
import base64
import json
import pickle
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SUBPROCESS_TIMEOUT_SECONDS = 60


_CHILD = r'''
import base64, io, pickle, runpy, sys
from contextlib import redirect_stdout
import numpy as np
try:
    import pandas as pd
except ImportError:
    pd = None
stdout_buffer = io.StringIO()
with redirect_stdout(stdout_buffer):
    namespace = runpy.run_path(sys.argv[1], run_name="__main__")
def wanted(value):
    return isinstance(value, (list, np.ndarray)) or (pd is not None and isinstance(value, (pd.DataFrame, pd.Series)))
values = {k: v for k, v in namespace.items() if not k.startswith("_") and wanted(v)}
payload = {"values": values, "stdout": stdout_buffer.getvalue()}
sys.stdout.write(base64.b64encode(pickle.dumps(payload, protocol=4)).decode("ascii"))
'''


@dataclass
class VariableComparison:
    name: str
    passed: bool
    message: str = ""


@dataclass
class VerificationResult:
    passed: bool
    comparisons: List[VariableComparison] = field(default_factory=list)
    variables: List[str] = field(default_factory=list)
    stdout_original: str = ""
    stdout_rewritten: str = ""
    stdout_match: bool = True
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "variables": self.variables,
            "comparisons": [c.__dict__ for c in self.comparisons],
            "stdout_match": self.stdout_match,
            "stdout_original": self.stdout_original,
            "stdout_rewritten": self.stdout_rewritten,
            "error": self.error,
        }


def _run(path: Path, cwd: Path) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD, str(path)],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{path}: subprocess timed out after {SUBPROCESS_TIMEOUT_SECONDS}s") from exc
    if proc.returncode:
        detail = proc.stderr.strip() or f"child exited with status {proc.returncode}"
        raise RuntimeError(f"{path}: {detail}")
    try:
        payload = pickle.loads(base64.b64decode(proc.stdout))
        if not isinstance(payload, dict) or "values" not in payload or "stdout" not in payload:
            raise ValueError("child returned an invalid payload")
        return payload
    except Exception as exc:
        raise RuntimeError(f"{path}: could not decode child output: {exc}") from exc


def _compare(left: Any, right: Any, *, rtol: float, atol: float) -> None:
    import numpy as np
    try:
        import pandas as pd
    except ImportError:
        pd = None
    if pd is not None and isinstance(left, pd.DataFrame) and isinstance(right, pd.DataFrame):
        pd.testing.assert_frame_equal(left, right, check_exact=False, rtol=rtol, atol=atol)
    elif pd is not None and isinstance(left, pd.Series) and isinstance(right, pd.Series):
        pd.testing.assert_series_equal(left, right, check_exact=False, rtol=rtol, atol=atol)
    elif isinstance(left, np.ndarray) and isinstance(right, np.ndarray):
        np.testing.assert_allclose(left, right, rtol=rtol, atol=atol, equal_nan=True)
    elif isinstance(left, list) and isinstance(right, list):
        np.testing.assert_equal(left, right)
    else:
        raise AssertionError(f"different types ({type(left).__name__}, {type(right).__name__})")


def verify_scripts(original: str | Path, rewritten: str | Path, names: Optional[Iterable[str]] = None, *, rtol: float = 1e-7, atol: float = 1e-12) -> VerificationResult:
    """Run two scripts and compare matching top-level result variables."""
    try:
        original_path, rewritten_path = Path(original).resolve(), Path(rewritten).resolve()
        expected_payload = _run(original_path, original_path.parent)
        actual_payload = _run(rewritten_path, original_path.parent)
        expected, actual = expected_payload["values"], actual_payload["values"]
        stdout_original, stdout_rewritten = expected_payload["stdout"], actual_payload["stdout"]
        selected = set(names) if names is not None else set(expected) | set(actual)
        if names is not None:
            missing = selected - set(expected) - set(actual)
            if missing:
                raise RuntimeError("missing variables: " + ", ".join(sorted(missing)))
        comparisons = []
        for name in sorted(selected):
            if name not in expected or name not in actual:
                comparisons.append(VariableComparison(name, False, "missing from one script"))
                continue
            try:
                _compare(expected[name], actual[name], rtol=rtol, atol=atol)
                comparisons.append(VariableComparison(name, True))
            except AssertionError as exc:
                comparisons.append(VariableComparison(name, False, str(exc)))
        if not comparisons:
            raise RuntimeError("no matching DataFrame, Series, ndarray, or list variables")
        stdout_match = stdout_original == stdout_rewritten
        return VerificationResult(
            all(c.passed for c in comparisons) and stdout_match,
            comparisons,
            sorted(selected),
            stdout_original,
            stdout_rewritten,
            stdout_match,
        )
    except Exception as exc:
        return VerificationResult(False, error=str(exc))


verify = verify_scripts


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="verify two FastFrame scripts")
    parser.add_argument("original"); parser.add_argument("rewritten"); parser.add_argument("--name", action="append", dest="names")
    args = parser.parse_args(argv)
    result = verify_scripts(args.original, args.rewritten, args.names)
    print(json.dumps(result.as_dict(), indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
