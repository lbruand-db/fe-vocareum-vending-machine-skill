"""§11 test 4: build ids and warnings for clean, dirty and unpushed builds; `which`; plus
`form` and `checklist`, which only need the repository."""

from __future__ import annotations

import json
import zipfile

from conftest import LAB, append_cell, commit, edit, git, run, vvm


def build(repo, capsys):
    rc = run(repo, "build")
    out = capsys.readouterr()
    info = json.loads((repo / "dist" / "BUILD_INFO.json").read_text()) if rc == 0 else None
    return rc, info, out


def test_clean_unpushed_build(repo, capsys):
    rc, info, out = build(repo, capsys)
    short = git(repo, "rev-parse", "--short=7", "HEAD")
    assert rc == 0
    assert info["build_id"] == f"0.1.0+g{short}"
    assert not info["dirty"] and not info["pushed"]
    assert "not on any remote branch" in out.err

    labs = zipfile.ZipFile(repo / "dist" / "hello-vocareum-labs.zip").namelist()
    assert "AGENDA.py" in labs and "Includes/_common.py" in labs
    assert "M01 - Basics/1.2 Lab - First Table.py" in labs
    assert not any(n.startswith(("setup/", "labs/")) for n in labs)

    setup = zipfile.ZipFile(repo / "dist" / "hello-vocareum-setup.zip").namelist()
    assert "setup/workspace_setup.py" in setup
    assert "labs/Source/en_us/notebooks/M01 - Basics/1.2 Lab - First Table.py" in setup
    assert not any(n.endswith(".md") for n in setup)

    with zipfile.ZipFile(repo / "dist" / "hello-vocareum-labs.zip") as z:
        version_info = z.read("Version Info.py").decode()
        common = z.read("Includes/_common.py").decode()
    assert "{{" not in version_info and info["build_id"] in version_info and info["commit_url"] in version_info
    assert f'COURSE_BUILD = "{info["build_id"]}"' in common


def test_dirty_build(repo, capsys):
    append_cell(repo, LAB, "x = 1")
    rc, info, out = build(repo, capsys)
    assert rc == 0
    assert info["build_id"].endswith(".dirty") and info["dirty"]
    assert "uncommitted changes" in out.err
    assert "Built from uncommitted changes" in zipfile.ZipFile(
        repo / "dist" / "hello-vocareum-labs.zip").read("Version Info.py").decode()


def test_untracked_outside_packaged_paths_is_clean(repo, capsys):
    (repo / "scratch.txt").write_text("notes")
    rc, info, _ = build(repo, capsys)
    assert rc == 0 and not info["dirty"]


def test_pushed_build(repo, tmp_path, capsys):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    rc, info, out = build(repo, capsys)
    assert rc == 0 and info["pushed"]
    assert "WARNING" not in out.err


def test_lint_errors_block_build(repo, capsys):
    append_cell(repo, LAB, 'spark.sql("CREATE CATALOG x")')
    rc, _, out = build(repo, capsys)
    assert rc == 1
    assert not (repo / "dist" / "BUILD_INFO.json").exists()
    assert "block the build" in out.err


def test_which(repo, capsys):
    short = git(repo, "rev-parse", "--short=7", "HEAD")
    (repo / "SPECS").mkdir()
    (repo / "SPECS" / "NOTES.md").write_text(f"# Notes\n\n## 2026-11-26 — vvm smoke 0.1.0+g{short}\n\n- result: PASS\n")
    assert run(repo, "which", f"0.1.0+g{short}") == 0
    out = capsys.readouterr().out
    assert git(repo, "rev-parse", "HEAD") in out
    assert "1 entry" in out and "result: PASS" in out


def test_which_unknown(repo, capsys):
    assert run(repo, "which", "0.1.0+gdeadbee") == 2
    assert run(repo, "which", "not-a-build") == 2


def test_form_full_and_warnings(repo, capsys):
    assert run(repo, "form") == 0
    out = capsys.readouterr()
    assert "| Workspace setup | Source | dist/hello-vocareum-setup.zip |" in out.out
    assert "not measured yet" in out.err


def test_form_timeout_check(repo, capsys):
    (repo / "SPECS").mkdir()
    (repo / "SPECS" / "NOTES.md").write_text("## smoke\n- setup_minutes: 20\n")
    run(repo, "form")
    assert "< 2 × last measured setup (20 min)" in capsys.readouterr().err


def test_form_diff_against_saved_config(repo, capsys):
    (repo / "vocareum").mkdir()
    (repo / "vocareum" / "config.json").write_text("{}\n")
    commit(repo, "save config.json")
    edit(repo, "course.toml", "setup_timeout_min = 30", "setup_timeout_min = 60")
    run(repo, "form")
    out = capsys.readouterr().out
    assert "| Workspace setup | Timeout (minutes) | 30 | 60 |" in out
    assert "Max Users" not in out


def test_checklist(repo, capsys):
    run(repo, "build")
    first = json.loads((repo / "dist" / "BUILD_INFO.json").read_text())["build_id"]
    (repo / "SPECS").mkdir()
    (repo / "SPECS" / "NOTES.md").write_text(f"## 2026-11-26 — Vocareum test {first}\n- all PASS\n")
    append_cell(repo, LAB, "y = 2")
    commit(repo)
    run(repo, "build")
    second = json.loads((repo / "dist" / "BUILD_INFO.json").read_text())["build_id"]
    assert run(repo, "checklist") == 0
    text = (repo / "SPECS" / f"CHECKLIST-{second}.md").read_text()
    assert f"last tested build `{first}`" in text
    assert "### 1.2 Lab — First Table — **new/changed**" in text
    assert "### 1.1 Lecture — Hello\n" in text
    assert "`hello.trips.trips` exist" in text
    assert "*Check your work*: PASS" in text
    assert run(repo, "checklist") == 2  # exists, no --force


def test_changed_lessons_shared(repo):
    base = git(repo, "rev-parse", "HEAD")
    edit(repo, "labs/Source/en_us/notebooks/Includes/_common.py", "# Common lesson setup", "# Common setup")
    commit(repo)
    lessons, shared = vvm.changed_lessons(vvm.Course(repo), base)
    assert shared and len(lessons) == 2


def test_last_tested_build_skips_dirty_and_current(repo):
    (repo / "SPECS").mkdir()
    (repo / "SPECS" / "NOTES.md").write_text(
        "## a — 0.1.0+gaaaaaaa\n## b — 0.1.0+gbbbbbbb.dirty\n## c — 0.2.0+gccccccc\n")
    course = vvm.Course(repo)
    assert vvm.last_tested_build(course) == "0.2.0+gccccccc"
    assert vvm.last_tested_build(course, exclude="0.2.0+gccccccc") == "0.1.0+gaaaaaaa"
