import base64
import importlib
import json
import pickle
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from fastframe.antipatterns import detect
from fastframe.bench import BenchmarkResult, ScriptStats
from fastframe.verify import VerificationResult

bench = importlib.import_module("fastframe.bench")
verify = importlib.import_module("fastframe.verify")
report = importlib.import_module("fastframe.report")


@pytest.mark.parametrize("module,runner", [(bench, "_run_child"), (verify, "_run")])
def test_subprocess_timeout_is_actionable(module, runner, monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] > 0
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", timeout)
    arguments = (Path("script.py"), "program") if module is bench else (Path("script.py"), Path.cwd())
    with pytest.raises(RuntimeError, match="script.py: subprocess timed out"):
        getattr(module, runner)(*arguments)


@pytest.mark.parametrize("module,runner", [(bench, "_run_child"), (verify, "_run")])
@pytest.mark.parametrize("stderr", ["bad script", ""])
def test_subprocess_nonzero_exit_preserves_error(module, runner, stderr, monkeypatch):
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=7, stderr=stderr, stdout=""))
    arguments = (Path("script.py"), "program") if module is bench else (Path("script.py"), Path.cwd())
    with pytest.raises(RuntimeError, match="bad script" if stderr else "7"):
        getattr(module, runner)(*arguments)


@pytest.mark.parametrize("stdout", ["not valid base64", base64.b64encode(pickle.dumps([])).decode(), base64.b64encode(pickle.dumps({"values": {}})).decode()])
def test_verify_rejects_corrupted_child_protocol(stdout, monkeypatch):
    monkeypatch.setattr(verify.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr="", stdout=stdout))
    with pytest.raises(RuntimeError, match="could not decode child output"):
        verify._run(Path("script.py"), Path.cwd())


@pytest.mark.parametrize("left,right", [(pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [1]})), (pd.Series([1.0]), pd.Series([1.0])), (np.array([1.0, np.nan]), np.array([1.0, np.nan])), ([1, 2], [1, 2])])
def test_comparison_supports_all_documented_result_types(left, right):
    verify._compare(left, right, rtol=0, atol=0)


def test_comparison_rejects_type_and_numeric_mismatches():
    with pytest.raises(AssertionError, match="different types"):
        verify._compare([1], np.array([1]), rtol=0, atol=0)
    with pytest.raises(AssertionError):
        verify._compare(np.array([1.0]), np.array([1.01]), rtol=0, atol=0)
    verify._compare(np.array([1.0]), np.array([1.01]), rtol=0.1, atol=0)


@pytest.mark.parametrize("expected,actual,names,error", [({}, {}, None, "no matching"), ({"a": [1]}, {"a": [1]}, ["missing"], "missing variables: missing")])
def test_verification_no_results_or_unknown_explicit_names(expected, actual, names, error, monkeypatch):
    payloads = iter([{"values": expected, "stdout": ""}, {"values": actual, "stdout": ""}])
    monkeypatch.setattr(verify, "_run", lambda *_: next(payloads))
    result = verify.verify_scripts("a.py", "b.py", names=names)
    assert not result.passed and error in result.error


def test_verify_reports_missing_mismatched_and_stdout_results(monkeypatch):
    payloads = iter([{"values": {"missing": [1], "wrong": [1], "good": [3]}, "stdout": "before\n"}, {"values": {"extra": [2], "wrong": [2], "good": [3]}, "stdout": "after\n"}])
    monkeypatch.setattr(verify, "_run", lambda *_: next(payloads))
    result = verify.verify_scripts("a.py", "b.py")
    assert not result.passed and not result.stdout_match
    comparisons = {item.name: item for item in result.comparisons}
    assert comparisons["good"].passed
    assert comparisons["missing"].message == comparisons["extra"].message == "missing from one script"
    assert not comparisons["wrong"].passed and comparisons["wrong"].message
    assert result.variables == ["extra", "good", "missing", "wrong"]


def test_verify_selected_names_use_original_working_directory(tmp_path, monkeypatch):
    calls = []

    def run(path, cwd):
        calls.append((path, cwd))
        return {"values": {"good": [1], "ignored": [len(calls)]}, "stdout": ""}

    monkeypatch.setattr(verify, "_run", run)
    original, rewritten = tmp_path / "original.py", tmp_path / "other" / "rewritten.py"
    result = verify.verify_scripts(original, rewritten, names=["good"])
    assert result.passed and result.variables == ["good"]
    assert calls == [(original, tmp_path), (rewritten, tmp_path)]


def test_sample_excludes_warmup_and_aggregates_independent_measurements(monkeypatch):
    responses = iter(["999", "99999", "3", "1", "2", "10", "30", "20"])
    programs = []

    def child(path, program):
        assert path == Path("script.py")
        programs.append(program)
        return next(responses)

    monkeypatch.setattr(bench, "_run_child", child)
    stats = bench._sample(Path("script.py"), 3)
    assert stats == ScriptStats(2.0, 1.0, 30, [3.0, 1.0, 2.0], [10, 30, 20])
    assert programs == [bench._TIME_CHILD, bench._MEMORY_CHILD, *[bench._TIME_CHILD] * 3, *[bench._MEMORY_CHILD] * 3]


def test_benchmark_rejects_no_runs_and_handles_zero_measurements(monkeypatch):
    with pytest.raises(ValueError, match="at least 1"):
        bench.benchmark("a.py", "b.py", runs=0)
    stats = iter([ScriptStats(1, 1, 0, [1], [0]), ScriptStats(0, 0, 5, [0], [5])])
    monkeypatch.setattr(bench, "_sample", lambda *_: next(stats))
    result = bench.benchmark("a.py", "b.py", runs=1)
    assert result.speedup == float("inf")
    assert result.memory_savings_bytes == -5 and result.memory_savings_percent == 0
    assert result.as_dict()["rewritten"]["samples_memory_bytes"] == [5]


def metrics():
    return BenchmarkResult(ScriptStats(2, 1, 20, [2], [20]), ScriptStats(1, 0.5, 10, [1], [10]), 2, 10, 50)


@pytest.mark.parametrize("passed,error", [(True, None), (False, "<script> error"), (False, None)])
def test_report_escapes_content_and_reports_failed_verification(tmp_path, monkeypatch, passed, error):
    source = tmp_path / "<source>.py"
    source.write_text("# <script>alert('x')</script>\n" + "out = df['a'].apply(lambda x: x * 2)\n" * 2 + "df.astype('object')\n")
    verification = VerificationResult(passed, error=error)
    candidate_sources = []

    def verify_candidate(original, candidate):
        assert original == source
        assert candidate.exists()
        candidate_sources.append((candidate, candidate.read_text()))
        return verification

    monkeypatch.setattr(report, "verify_scripts", verify_candidate)
    monkeypatch.setattr(report, "benchmark", lambda *_args, **kwargs: metrics())
    destination = tmp_path / "nested" / "report.html"
    assert report.render_report(source, destination, runs=1) == destination
    output = destination.read_text()
    assert "&lt;source&gt;.py" in output
    assert "<script>" not in output
    assert "MANUAL REVIEW" in output and "advisory only" in output
    assert "PASS" in output if passed else "FAIL" in output
    assert len(candidate_sources) == 3  # Complete rewrite, then each AP002 occurrence.
    assert [text.count(".apply(") for _, text in candidate_sources] == [0, 1, 1]
    assert candidate_sources[1][1] != candidate_sources[2][1]
    assert all(not path.exists() for path, _ in candidate_sources)
    if error:
        assert "&lt;script&gt; error" in output


def test_report_without_findings_and_empty_snippet():
    page = report._page(Path("empty.py"), "", [], [], VerificationResult(False), metrics())
    assert "No anti-patterns detected" in page
    assert "FAIL: result mismatch" in page
    finding = detect("out = df['a'].apply(lambda x: x + 1)\n")[0]
    assert report._snippet("", finding) == ""


def test_module_main_functions_forward_arguments_and_emit_json(monkeypatch, capsys):
    monkeypatch.setattr(verify, "verify_scripts", lambda original, rewritten, names: VerificationResult(names == ["out"]))
    assert verify.main(["a.py", "b.py", "--name", "out"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    assert verify.main(["a.py", "b.py"]) == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False
    calls = []

    def benchmark(original, rewritten, *, runs):
        calls.append((original, rewritten, runs))
        return metrics()

    monkeypatch.setattr(bench, "benchmark", benchmark)
    assert bench.main(["a.py", "b.py", "--runs", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["speedup"] == 2
    assert calls == [("a.py", "b.py", 2)]
    monkeypatch.setattr(report, "render_report", lambda original, destination, *, runs: calls.append((original, destination, runs)))
    assert report.main(["a.py", "--html", "out.html", "--runs", "4"]) == 0
    assert "wrote out.html" in capsys.readouterr().out
    assert calls[-1] == ("a.py", "out.html", 4)
