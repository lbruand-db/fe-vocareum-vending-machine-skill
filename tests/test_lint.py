"""§11 test 3: one failing and one passing case per lint rule (spec §7.4)."""

from __future__ import annotations

import pytest
from conftest import AGENDA, INCLUDES, LAB, LECTURE, append_cell, edit, git, vvm


def findings(repo, rule=None, severity="error"):
    out = vvm.lint(vvm.Course(repo))
    return [f for f in out if (rule is None or f.rule == rule) and (severity is None or f.severity == severity)]


def test_fixture_is_clean(repo):
    assert findings(repo, severity=None) == []


def _gpu(repo):
    append_cell(repo, LAB, 'cluster = {"node_type_id": "g4dn.xlarge"}')


FAILING = {
    "notebook-header": lambda r: (r / INCLUDES / "helper.py").write_text("print('not a notebook')\n"),
    "env-header": lambda r: edit(r, AGENDA, 'environment_version = "4"', 'environment_version = "5"'),
    "classroom-setup": lambda r: edit(r, LAB, "# MAGIC %run ../Includes/Classroom-Setup-1.2", ""),
    "check-your-work": lambda r: edit(r, LAB, 'finish("1.2"', 'print("1.2"'),
    "no-create-catalog": lambda r: append_cell(r, LAB, 'spark.sql("CREATE CATALOG IF NOT EXISTS mine")'),
    "no-gpu": _gpu,
    "no-runtime-download": lambda r: append_cell(r, LAB, "# MAGIC %pip install pandas"),
    "no-hardcoded-identity": lambda r: append_cell(r, LAB, 'owner = "jane.doe@acme.com"'),
    "agenda-links": lambda r: edit(r, AGENDA, "1.2 Lab - First Table)", "1.3 Lab - Missing)"),
    "pins": lambda r: edit(r, "course.toml", 'ref = "0123456789abcdef0123456789abcdef01234567"', 'ref = "main"'),
    "placeholders": lambda r: edit(r, "labs/Source/en_us/notebooks/Version Info.py", "{{built_on}}", "{{built_at}}"),
    "branding": lambda r: edit(r, LECTURE, "# 1.1 Lecture — Hello", "# 1.1 Lecture — Hello, from Databricks Academy"),
    "reference-material": lambda r: ((r / ".sources").mkdir(), (r / ".sources" / "x.md").write_text("x"),
                                     git(r, "add", "-f", ".sources/x.md")),
    "run-targets": lambda r: edit(r, f"{INCLUDES}/Classroom-Setup-1.2.py", "%run ./_common", "%run ./_missing"),
    "course-toml": lambda r: edit(r, "course.toml", 'notebook = "setup/00_data_load"', 'notebook = "setup/01_nope"'),
}


@pytest.mark.parametrize("rule", sorted(FAILING))
def test_rule_fails(repo, rule):
    FAILING[rule](repo)
    got = findings(repo, rule)
    assert got, f"expected a {rule} error; got {findings(repo, severity=None)}"


@pytest.mark.parametrize("code", [
    "# MAGIC %pip install git+https://github.com/example/lib@0123456",
    "# MAGIC %pip install --index-url https://pypi.example.com/simple lib",
    "# MAGIC %pip install -r requirements.txt",
    'df = pd.read_csv("https://example.com/data.csv")',
    'r = requests.get("https://raw.githubusercontent.com/x/y/main/z.json")',
    'm = AutoModel.from_pretrained("amazon/chronos-bolt-small")',
    "# MAGIC %sh wget https://example.com/x.zip",
])
def test_runtime_download_fails(repo, code):
    append_cell(repo, LAB, code)
    assert findings(repo, "no-runtime-download")


@pytest.mark.parametrize("code", [
    "# MAGIC %pip install -q -r /Volumes/hello/trips/assets/requirements.txt",
    "# MAGIC %pip install /Volumes/hello/trips/assets/wheels/helper_lib-1.0-py3-none-any.whl",
    "# MAGIC %pip install --no-index --find-links /Volumes/hello/trips/assets/wheels helper_lib",
    'm = AutoModel.from_pretrained("/Volumes/hello/trips/assets/models/chronos")',
    'r = urlopen(f"{host}/api/2.0/workspace/get-status")',
])
def test_runtime_download_passes(repo, code):
    append_cell(repo, LAB, code)
    assert not findings(repo, "no-runtime-download")


def test_markdown_is_not_code(repo):
    # The lecture already says "Never run CREATE CATALOG" in markdown; add a GPU mention too.
    edit(repo, LECTURE, "# MAGIC Never run", "# MAGIC No `GPU_1xA10` here. Never run")
    assert not findings(repo, "no-create-catalog")
    assert not findings(repo, "no-gpu")


def test_setup_may_create_catalog_and_download(repo):
    append_cell(repo, "setup/00_data_load.py", "# MAGIC %pip install datasetsforecast==0.0.8")
    assert not findings(repo)  # setup/workspace_setup already has CREATE CATALOG


def test_allowed_identities(repo):
    append_cell(repo, LAB, 'example = "someone@example.com"  # docs\nvoc = "vocuser12345@vocareum.com"')
    assert not findings(repo, "no-hardcoded-identity")


@pytest.mark.parametrize("code", [
    'host = "https://dbc-12345678-abcd.cloud.databricks.com"',
    # A fake token, assembled at runtime so no token-shaped literal sits in the source.
    'token = "' + "dapi" + "0123456789abcdef" * 2 + '"',
])
def test_hosts_and_tokens_fail(repo, code):
    append_cell(repo, LAB, code)
    assert findings(repo, "no-hardcoded-identity")


def test_waiver_with_reason(repo):
    _gpu(repo)
    edit(repo, LAB, "# MAGIC # 1.2 Lab", "# vvm: allow no-gpu — instructor-only cell\n# MAGIC # 1.2 Lab")
    assert not findings(repo, "no-gpu")


def test_waiver_without_reason_is_ignored(repo):
    _gpu(repo)
    edit(repo, LAB, "# MAGIC # 1.2 Lab", "# vvm: allow no-gpu\n# MAGIC # 1.2 Lab")
    assert findings(repo, "no-gpu")
    assert findings(repo, "waiver", severity="warning")


def test_pins_need_versions_md(repo):
    (repo / "setup" / "VERSIONS.md").unlink()
    assert findings(repo, "pins")


def test_lecture_needs_no_setup(repo):
    assert not [f for f in findings(repo) if LECTURE in f.path]


def test_setup_notebook_without_header_is_a_warning(repo):
    (repo / "setup" / "helpers.py").write_text("def f(): pass\n")
    assert not findings(repo, "notebook-header")
    assert findings(repo, "notebook-header", severity="warning")


def test_lint_exit_code(repo, capsys):
    from conftest import run
    assert run(repo, "lint") == 0
    append_cell(repo, LAB, 'spark.sql("CREATE CATALOG x")')
    assert run(repo, "lint") == 1


def test_link_to_module_folder(repo):
    edit(repo, AGENDA, "# MAGIC # Hello Vocareum", "# MAGIC # Hello Vocareum\n# MAGIC [Module 1]($./M01 - Basics)")
    assert not findings(repo, "agenda-links")


def test_setup_env_header_is_a_warning(repo):
    edit(repo, "setup/00_data_load.py", 'environment_version = "4"', 'environment_version = "3"')
    assert not findings(repo, "env-header")
    assert findings(repo, "env-header", severity="warning")
