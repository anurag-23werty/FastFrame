import json

from typer.testing import CliRunner

from fastframe.cli import app

runner = CliRunner()


def _script(path, body):
    path.write_text(body, encoding="utf-8")
    return path


def test_demo_shows_install_and_container_banner():
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "FASTFRAME" in result.stdout
    assert "pip install fastframe-pandas pandas numpy" in result.stdout
    assert "DOCKER" in result.stdout


def test_verify_has_readable_and_json_modes(tmp_path):
    left = _script(tmp_path / "left.py", "print('same')\nresult = [1, 2]\n")
    right = _script(tmp_path / "right.py", "print('same')\nresult = [1, 2]\n")
    readable = runner.invoke(app, ["verify", str(left), str(right)])
    assert readable.exit_code == 0
    assert "PASS verification" in readable.stdout
    machine = runner.invoke(app, ["verify", str(left), str(right), "--json"])
    assert machine.exit_code == 0
    assert json.loads(machine.stdout)["stdout_match"] is True


def test_bench_has_readable_and_json_modes(tmp_path):
    left = _script(tmp_path / "left.py", "result = [1, 2]\n")
    right = _script(tmp_path / "right.py", "result = [1, 2]\n")
    readable = runner.invoke(app, ["bench", str(left), str(right), "--runs", "1"])
    assert readable.exit_code == 0
    assert "Speedup:" in readable.stdout
    machine = runner.invoke(app, ["bench", str(left), str(right), "--runs", "1", "--json"])
    assert machine.exit_code == 0
    assert "min_seconds" in machine.stdout


def test_fix_verifies_diff_and_in_place_backup(tmp_path):
    source = _script(tmp_path / "source.py", "result = [1, 2]\n")
    output = tmp_path / "output.py"
    fixed = runner.invoke(app, ["fix", str(source), "-o", str(output)])
    assert fixed.exit_code == 0
    assert "Verification passed" in fixed.stdout
    assert output.read_text() == source.read_text()

    dry_run = runner.invoke(app, ["fix", str(source), "--diff"])
    assert dry_run.exit_code == 0
    assert not (tmp_path / "source.py.bak").exists()

    in_place = runner.invoke(app, ["fix", str(source), "--in-place"])
    assert in_place.exit_code == 0
    assert (tmp_path / "source.py.bak").exists()


def test_fix_no_verify_warns(tmp_path):
    source = _script(tmp_path / "source.py", "result = [1]\n")
    output = tmp_path / "output.py"
    result = runner.invoke(app, ["fix", str(source), "-o", str(output), "--no-verify"])
    assert result.exit_code == 0
    assert "verification skipped" in result.stdout


def test_fix_preserves_inline_suppressed_python_line(tmp_path):
    source = _script(tmp_path / "source.py", 'import pandas as pd\ndf = pd.DataFrame({"a": [1, 2]})\nout = df["a"].apply(lambda x: x * 2)  # fastframe: ignore\n')
    output = tmp_path / "output.py"
    result = runner.invoke(app, ["fix", str(source), "-o", str(output)])
    assert result.exit_code == 0, result.stdout
    assert output.read_text() == source.read_text()


def test_fix_preserves_pyproject_ignored_python_rule(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.fastframe]\nignore = ["AP002"]\n')
    source = _script(tmp_path / "source.py", 'import pandas as pd\ndf = pd.DataFrame({"a": [1, 2]})\nout = df["a"].apply(lambda x: x * 2)\n')
    output = tmp_path / "output.py"
    result = runner.invoke(app, ["fix", str(source), "-o", str(output)])
    assert result.exit_code == 0, result.stdout
    assert output.read_text() == source.read_text()


def test_fix_verification_failure_is_concise_unless_verbose(tmp_path):
    source = _script(tmp_path / "source.py", "result = [1]\n")
    output = tmp_path / "output.py"
    # A malformed rewritten candidate is easiest to exercise by making the
    # source itself fail; fix must not write and should summarize the traceback.
    source.write_text("result = missing_name\n")
    result = runner.invoke(app, ["fix", str(source), "-o", str(output)])
    assert result.exit_code == 1
    assert "NameError at line 1" in result.stdout
    assert "Traceback" not in result.stdout
    verbose = runner.invoke(app, ["fix", str(source), "-o", str(output), "--verbose"])
    assert verbose.exit_code == 1
    assert "Traceback" in verbose.stdout
