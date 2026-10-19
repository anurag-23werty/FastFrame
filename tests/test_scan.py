import json

from typer.testing import CliRunner

from fastframe.cli import app
from fastframe.scan import rewrite_notebook, scan_path

runner = CliRunner()


def test_recursive_scan_and_json_exit_code(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "slow.py").write_text('out = df["a"].apply(lambda x: x * 2)\n')
    result = runner.invoke(app, ["scan", str(tmp_path), "--format", "json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload[0]["path"].endswith("slow.py")
    assert payload[0]["line"] == 1

    (nested / "clean.py").write_text("x = 1\n")
    assert runner.invoke(app, ["scan", str(nested / "clean.py")]).exit_code == 0


def test_notebook_code_cells_scan_and_copy_fix(tmp_path):
    source = tmp_path / "demo.ipynb"
    source.write_text(json.dumps({"cells": [
        {"cell_type": "markdown", "source": ["# title"]},
        {"cell_type": "code", "source": ['out = df["a"].apply(lambda x: x * 2)\n']},
    ]}))
    items = scan_path(source)
    assert items[0].cell == 2
    assert items[0].location.endswith(":cell 2 line 1")
    destination = tmp_path / "fixed.ipynb"
    rewrite_notebook(source, destination)
    notebook = json.loads(destination.read_text())
    assert "apply" not in "".join(notebook["cells"][1]["source"])
    assert notebook["cells"][0]["source"] == ["# title"]
    cli_destination = tmp_path / "cli-fixed.ipynb"
    result = runner.invoke(app, ["fix", str(source), "-o", str(cli_destination)])
    assert result.exit_code == 0
    assert cli_destination.exists()


def test_notebook_fix_preserves_suppressed_and_config_ignored_cells(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.fastframe]\nignore = ["AP002"]\n')
    source = tmp_path / "demo.ipynb"
    source.write_text(json.dumps({"cells": [
        {"cell_type": "code", "source": ['a = df["a"].apply(lambda x: x * 2)  # fastframe: ignore\n']},
        {"cell_type": "code", "source": ['b = df["b"].apply(lambda x: x * 2)\n']},
    ]}))
    destination = tmp_path / "fixed.ipynb"
    result = runner.invoke(app, ["fix", str(source), "-o", str(destination)])
    assert result.exit_code == 0
    notebook = json.loads(destination.read_text())
    assert "apply" in "".join(notebook["cells"][0]["source"])
    assert "apply" in "".join(notebook["cells"][1]["source"])


def test_notebook_magics_are_masked_and_restored(tmp_path):
    source = tmp_path / "magic.ipynb"
    source.write_text(json.dumps({"cells": [{"cell_type": "code", "source": [
        "%%time\n", "!pip install pandas\n", "%timeit result = df[\"a\"].apply(lambda x: x * 2)\n",
        "out = df[\"a\"].apply(lambda x: x * 2)\n",
    ]}]}))
    items = scan_path(source)
    assert [(item.finding.pattern, item.finding.line) for item in items] == [("AP002", 4)]
    destination = tmp_path / "fixed.ipynb"
    rewrite_notebook(source, destination)
    code = "".join(json.loads(destination.read_text())["cells"][0]["source"])
    assert code.splitlines()[:3] == ["%%time", "!pip install pandas", "%timeit result = df[\"a\"].apply(lambda x: x * 2)"]
    assert 'out = df["a"] * 2' in code


def test_notebook_unparseable_cell_is_skipped(tmp_path):
    source = tmp_path / "bad.ipynb"
    source.write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["if :\n", "  broken\n"]}]}))
    destination = tmp_path / "fixed.ipynb"
    rewrite_notebook(source, destination)
    assert json.loads(destination.read_text())["cells"][0]["source"] == ["if :\n", "  broken\n"]


def test_directory_scan_warns_and_continues_for_syntax_errors(tmp_path):
    (tmp_path / "bad.py").write_text("if :\n")
    (tmp_path / "good.py").write_text('out = df["a"].apply(lambda x: x * 2)\n')
    warnings = []
    items = scan_path(tmp_path, warnings=warnings)
    assert len(items) == 1
    assert warnings == [f"skipped {tmp_path / 'bad.py'}: syntax error at line 1"]


def test_directory_scan_excludes_vendor_and_configured_directories(tmp_path):
    for directory in [".venv", "venv", "site-packages", "node_modules", ".git", "build", "dist", "__pycache__", "generated"]:
        target = tmp_path / directory
        target.mkdir()
        (target / "slow.py").write_text('out = df["a"].apply(lambda x: x * 2)\n')
    (tmp_path / "pyproject.toml").write_text('[tool.fastframe]\nexclude = ["generated"]\n')
    assert scan_path(tmp_path) == []


def test_inline_suppression_and_pyproject_config(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.fastframe]\nselect = ["AP002"]\nignore = []\n')
    source = tmp_path / "source.py"
    source.write_text(
        'a = df["a"].apply(lambda x: x * 2)  # fastframe: ignore\n'
        'b = df["b"].apply(lambda x: x * 2)  # fastframe: ignore[AP002]\n'
        'c = df["c"].apply(lambda x: x * 2)\n'
    )
    items = scan_path(source)
    assert [item.finding.pattern for item in items] == ["AP002"]

    (tmp_path / "pyproject.toml").write_text('[tool.fastframe]\nselect = []\nignore = ["AP002"]\n')
    assert scan_path(source) == []


def test_rules_and_explain_commands():
    listed = runner.invoke(app, ["rules"])
    assert listed.exit_code == 0 and "AP003" in listed.stdout
    explained = runner.invoke(app, ["explain", "AP003"])
    assert explained.exit_code == 0
    assert "Before:" in explained.stdout and "After:" in explained.stdout
