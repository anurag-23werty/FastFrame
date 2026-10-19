import importlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fastframe import detect, rewrite
from fastframe.cli import app
from fastframe.scan import ScanConfig, _suppressed, load_config, rewrite_path, scan_path
from fastframe.verify import VariableComparison, VerificationResult

runner = CliRunner()
ARITHMETIC = "out = df['a'].apply(lambda x: x * 2)\n"


@pytest.mark.parametrize("arguments", [[], ["--diff", "-o", "out.py"], ["--diff", "--in-place"], ["-o", "out.py", "--in-place"]])
def test_fix_rejects_conflicting_or_missing_destinations(tmp_path, arguments):
    source = tmp_path / "source.py"
    source.write_text(ARITHMETIC)
    result = runner.invoke(app, ["fix", str(source), *arguments])
    assert result.exit_code == 2
    assert source.read_text() == ARITHMETIC
    assert not source.with_suffix(".py.bak").exists()


def test_scan_modes_and_manual_advisory(tmp_path):
    source = tmp_path / "source.py"
    source.write_text(ARITHMETIC + "df.astype('object')\n")
    text = runner.invoke(app, ["scan", str(source)])
    assert text.exit_code == 1
    assert "AP002" in text.stdout and "manual review" in text.stdout
    machine = runner.invoke(app, ["scan", str(source), "--format", "json"])
    assert machine.exit_code == 1
    payload = json.loads(machine.stdout)
    assert [item["pattern"] for item in payload] == ["AP002", "AP006"]
    assert payload[1]["manual_fix"] is True
    invalid = runner.invoke(app, ["scan", str(source), "--format", "xml"])
    assert invalid.exit_code == 2
    source.write_text("result = [1]\n")
    assert "No anti-patterns" in runner.invoke(app, ["scan", str(source)]).stdout


def test_fix_failure_does_not_overwrite_or_leave_temporary_files(tmp_path, monkeypatch):
    cli = importlib.import_module("fastframe.cli")
    source, output = tmp_path / "source.py", tmp_path / "out.py"
    source.write_text(ARITHMETIC)
    output.write_text("keep existing output")
    monkeypatch.setattr(cli, "verify_scripts", lambda *_: VerificationResult(False, error="different values"))
    result = runner.invoke(app, ["fix", str(source), "-o", str(output)])
    assert result.exit_code == 1 and "different values" in result.stdout
    assert output.read_text() == "keep existing output"
    assert source.read_text() == ARITHMETIC
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.py", "source.py"]


def test_fix_verifier_exception_cleans_temporary_file(tmp_path, monkeypatch):
    cli = importlib.import_module("fastframe.cli")
    source = tmp_path / "source.py"
    source.write_text(ARITHMETIC)

    def broken_verifier(*_):
        raise RuntimeError("verifier failed unexpectedly")

    monkeypatch.setattr(cli, "verify_scripts", broken_verifier)
    result = runner.invoke(app, ["fix", str(source), "--in-place"])
    assert result.exit_code == 1
    assert source.read_text() == ARITHMETIC
    assert list(tmp_path.iterdir()) == [source]


def test_notebook_fix_in_place_and_diff_rejection(tmp_path):
    source = tmp_path / "source.ipynb"
    notebook = {"cells": [{"cell_type": "markdown", "source": ["# Keep this\n"]}, {"cell_type": "code", "source": [ARITHMETIC], "outputs": [], "metadata": {"tag": "keep"}}], "metadata": {"name": "example"}}
    original = json.dumps(notebook)
    source.write_text(original)
    rejected = runner.invoke(app, ["fix", str(source), "--diff"])
    assert rejected.exit_code == 2
    assert source.read_text() == original
    result = runner.invoke(app, ["fix", str(source), "--in-place"])
    assert result.exit_code == 0
    assert source.with_suffix(".ipynb.bak").read_text() == original
    updated = json.loads(source.read_text())
    assert updated["cells"][0] == notebook["cells"][0]
    assert updated["cells"][1]["metadata"] == {"tag": "keep"}
    assert updated["cells"][1]["source"] == ["out = df['a'] * 2\n"]


def test_verify_failure_output_and_exit_code(monkeypatch):
    cli = importlib.import_module("fastframe.cli")
    failure = VerificationResult(False, [VariableComparison("out", False, "values differ")], ["out"], stdout_match=False, error="execution issue")
    monkeypatch.setattr(cli, "verify_scripts", lambda *_: failure)
    result = runner.invoke(app, ["verify", "before.py", "after.py"])
    assert result.exit_code == 1
    for message in ["FAIL verification", "values differ", "stdout: FAIL", "execution issue"]:
        assert message in result.stdout
    result = runner.invoke(app, ["verify", "before.py", "after.py", "--json"])
    assert result.exit_code == 1 and json.loads(result.stdout)["passed"] is False


def test_report_cli_forwards_paths_and_run_count(monkeypatch, tmp_path):
    cli = importlib.import_module("fastframe.cli")
    calls = []

    def render(source, destination, *, runs):
        calls.append((source, destination, runs))
        return destination

    monkeypatch.setattr(cli, "render_report", render)
    output = tmp_path / "report.html"
    result = runner.invoke(app, ["report", "source.py", "--html", str(output), "--runs", "2"])
    assert result.exit_code == 0 and "Wrote" in result.stdout
    assert calls == [(Path("source.py"), output, 2)]
    assert runner.invoke(app, ["bench", "a.py", "b.py", "--runs", "0"]).exit_code == 2
    assert runner.invoke(app, ["report", "a.py", "--html", str(output), "--runs", "0"]).exit_code == 2


@pytest.mark.parametrize("rule", ["ap001", "AP002", "AP003", "AP004", "AP005", "AP006"])
def test_explain_all_rules_and_reject_unknown(rule):
    result = runner.invoke(app, ["explain", rule])
    assert result.exit_code == 0
    assert rule.upper() in result.stdout and "Before:" in result.stdout and "After:" in result.stdout
    assert runner.invoke(app, ["explain", "AP999"]).exit_code == 2


def test_config_nearest_project_takes_precedence_and_ignore_wins(tmp_path):
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[tool.fastframe]\nselect = ["AP001"]\n')
    source = child / "example.py"
    source.write_text(ARITHMETIC + "df.astype('int64')\n")
    assert load_config(source).select == frozenset({"AP001"})
    (child / "pyproject.toml").write_text('[tool.fastframe]\nselect = ["AP002", "AP006"]\nignore = ["AP006"]\n')
    assert [item.finding.pattern for item in scan_path(source)] == ["AP002"]
    (child / "pyproject.toml").write_text('[project]\nname = "nested"\n')
    assert load_config(source) == ScanConfig()
    assert len(scan_path(source)) == 2


def test_config_errors_are_not_silently_ignored(tmp_path):
    import tomllib

    (tmp_path / "pyproject.toml").write_text("not valid toml !!!")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_config(tmp_path)


def test_scanning_suppressions_and_unsupported_files(tmp_path):
    source = tmp_path / "source.py"
    source.write_text(ARITHMETIC.rstrip() + "  # FASTFRAME: ignore[AP001]\n" + ARITHMETIC.rstrip() + "  # fastframe: ignore[AP002, AP006]\n" + ARITHMETIC.rstrip() + "  # fastframe: ignore\n")
    findings = scan_path(source, ScanConfig())
    assert [item.finding.line for item in findings] == [1]
    finding = findings[0].finding
    assert not _suppressed("", finding)
    assert finding.kind == finding.pattern_id == "AP002"
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text(ARITHMETIC)
    assert scan_path(unsupported, ScanConfig()) == []
    destination = tmp_path / "nested" / "out.py"
    rewrite_path(source, destination)
    assert destination.read_text() == rewrite(source.read_text())


@pytest.mark.parametrize("dtype,saving", [("'object'", 8), ("'float64'", 4), ("{'a': 'object'}", 8), ("{'a': 'int64'}", 4), ("{'a': 'float64'}", 4)])
def test_downcast_advisories_support_dtype_mappings(dtype, saving):
    source = f"df.astype({dtype})\n"
    finding, = detect(source)
    assert finding.estimate_bytes == saving and finding.manual_fix
    assert rewrite(source) == source


def test_selective_rewrite_only_changes_requested_occurrence():
    source = ARITHMETIC * 2
    assert rewrite(source, pattern="AP002", occurrence=2) == ARITHMETIC + "out = df['a'] * 2\n"
    assert rewrite(source, pattern="AP001") == source
    assert rewrite(source, occurrence=3) == source
    with pytest.raises(ValueError, match="at least 1"):
        rewrite(source, occurrence=0)


def test_compatibility_imports_reexport_public_functions(monkeypatch):
    import fastframe

    # Importing submodules temporarily binds them on the parent package. Restore
    # the public function exports afterwards so this check cannot affect peers.
    monkeypatch.setattr(fastframe, "detect", detect)
    monkeypatch.setattr(fastframe, "rewrite", rewrite)
    assert importlib.import_module("fastframe.detect").detect is detect
    assert importlib.import_module("fastframe.rewrite").rewrite is rewrite
