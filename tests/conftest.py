"""Shared fixtures: a throwaway git repository holding a copy of tests/fixtures/course."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "vocareum-vending-machine" / "scripts"))

import vvm  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "course"
LAB = "labs/Source/en_us/notebooks/M01 - Basics/1.2 Lab - First Table.py"
LECTURE = "labs/Source/en_us/notebooks/M01 - Basics/1.1 Lecture - Hello.py"
AGENDA = "labs/Source/en_us/notebooks/AGENDA.py"
INCLUDES = "labs/Source/en_us/notebooks/Includes"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
                 "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
                 "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def repo(tmp_path) -> Path:
    """The fixture course, committed on `main` in a fresh repository (no remote)."""
    dest = tmp_path / "course"
    shutil.copytree(FIXTURE, dest)
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "fixture")
    return dest


def edit(repo: Path, rel: str, old: str, new: str) -> None:
    p = repo / rel
    text = p.read_text()
    assert old in text, f"{old!r} not in {rel}"
    p.write_text(text.replace(old, new, 1))


def append_cell(repo: Path, rel: str, code: str) -> None:
    p = repo / rel
    p.write_text(p.read_text() + "\n# COMMAND ----------\n\n" + code + "\n")


def commit(repo: Path, msg: str = "change") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def run(repo: Path, *args: str) -> int:
    return vvm.main(["-C", str(repo), *args])
