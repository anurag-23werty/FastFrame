from pathlib import Path

from fastframe.bench import benchmark
from fastframe.verify import verify_scripts


ROOT = Path(__file__).parents[1]


def test_verify_examples_collects_matching_lists():
    result = verify_scripts(ROOT / "examples/baseline.py", ROOT / "examples/vectorized.py")
    assert result.passed
    assert result.variables == ["result", "values"]


def test_verify_reports_differences(tmp_path):
    left = tmp_path / "left.py"
    right = tmp_path / "right.py"
    left.write_text("result = [1, 2, 3]\n")
    right.write_text("result = [1, 2, 4]\n")
    result = verify_scripts(left, right)
    assert not result.passed
    assert result.comparisons[0].name == "result"


def test_verify_and_bench_ignore_script_stdout(tmp_path):
    left = tmp_path / "left.py"
    right = tmp_path / "right.py"
    left.write_text("print('left noise')\nresult = [1, 2, 3]\n")
    right.write_text("print('right noise')\nresult = [1, 2, 3]\n")
    assert verify_scripts(left, right).passed
    assert benchmark(left, right, runs=1).speedup > 0


def test_benchmark_has_configurable_samples_and_metrics():
    result = benchmark(ROOT / "examples/baseline.py", ROOT / "examples/vectorized.py", runs=2)
    assert len(result.original.samples_seconds) == 2
    assert result.original.median_seconds > 0
    assert result.original.min_seconds <= result.original.median_seconds
    assert result.original.peak_memory_bytes > 0
    assert result.speedup > 0
