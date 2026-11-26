#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["databricks-sdk==0.171.0"]
#
# [tool.uv]
# exclude-newer = "2026-11-27T00:00:00Z"
# ///
"""vvm — lint, build, test and ship a Vocareum Course Vending Machine course.

Run from a course repository (one with a `course.toml`):

    uv run <skill>/scripts/vvm.py <command> [options]

Local commands:     lint, build, which, form, checklist
Workspace commands: install, smoke, cleanup   (need a Databricks CLI profile)

See the skill's SKILL.md and SPECS/SPEC.md (§7) for the conventions it checks.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import random
import re
import shlex
import subprocess
import sys
import time
import tomllib
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

NOTEBOOK_HEADER = "# Databricks notebook source"
CELL_SEP = "# COMMAND ----------"
MAGIC = "# MAGIC"

# Paths whose uncommitted changes make a build "dirty" (spec §7.3).
PACKAGED_PATHS = ["setup", "labs", "pyproject.toml", "course.toml"]

BUILD_PLACEHOLDERS = {
    "course_name", "version_number", "build_id", "commit", "commit_url", "built_on", "dirty_note",
}
# Filled in at install time in per-user asset files (spec §7.5), not by the build.
ASSET_PLACEHOLDERS = {"workspace_url", "user_email"}

LESSON_RE = re.compile(
    r"^(?P<num>(?P<major>\d+)\.(?P<minor>\d+)) (?P<type>Lecture|Demo|Lab|Appendix) - (?P<title>.+)\.py$"
)
MODULE_RE = re.compile(r"^M\d+ - .+$")
BUILD_ID_RE = re.compile(r"(?P<version>[0-9][0-9A-Za-z.!_-]*)\+g(?P<short>[0-9a-f]{7,40})(?P<dirty>\.dirty)?")
SHARED_INCLUDES = {"_common.py", "_checks.py", "_user_assets.py"}
ASSET_KINDS = {"wheel", "tarball", "file", "skill-bundle"}
SMOKE_STATE = "vvm-smoke-state.json"
SETUP_TIMEOUT_MAX = 120


class VvmError(Exception):
    """A user-facing error: printed without a traceback."""


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- course


class Course:
    """A course repository: `course.toml` plus the layout of spec §6."""

    def __init__(self, root: Path, data: dict | None = None):
        """`data`: an already-parsed course.toml (e.g. from an older commit, for diffs)."""
        self.root = root.resolve()
        path = self.root / "course.toml"
        try:
            self.toml = data if data is not None else tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise VvmError(f"{path}: {e}") from e
        c = self.toml.get("course", {})
        missing = [k for k in ("name", "slug", "repo_url") if not c.get(k)]
        if missing:
            raise VvmError(f"course.toml: [course] is missing {', '.join(missing)}")
        self.name: str = c["name"]
        self.slug: str = c["slug"]
        self.repo_url: str = c["repo_url"].rstrip("/")
        self.locale: str = c.get("locale", "en_us")
        self.entry: str = c.get("entry", "AGENDA")
        self.branding: str = c.get("branding", "neutral")
        self.reference_dir: str = c.get("reference_dir", ".sources")
        self.environment_version = str(c.get("environment_version", "4"))

        d = self.toml.get("data", {})
        for k in ("catalog", "schema"):
            if not d.get(k):
                raise VvmError(f"course.toml: [data] is missing {k}")
        self.catalog: str = d["catalog"]
        self.schema: str = d["schema"]
        self.reference_schema: str = d.get("reference_schema", f"{self.schema}_reference")
        self.learner_schema: str = d.get("learner_schema", self.slug.replace("-", "_"))
        self.learner_group: str = d.get("learner_group", "account users")

        v = self.toml.get("vocareum", {})
        self.org: str = v.get("org", "Field Driven Enablement Labs")
        self.template: str = v.get("template", "Data Science")
        self.max_users: int = int(v.get("max_users_per_workspace", 50))
        self.lab_time_hours = v.get("lab_time_hours")
        self.setup_timeout_min: int = int(v.get("setup_timeout_min", 20))
        self.allow_lab_stop: bool = bool(v.get("allow_lab_stop", False))

        self.setup_steps: list[dict] = self.toml.get("setup", {}).get("steps", [])
        self.assets: list[dict] = self.toml.get("assets", [])
        self.user_assets: list[dict] = self.toml.get("user_assets", [])

    # Layout
    @property
    def labs_dir(self) -> Path:
        return self.root / "labs"

    @property
    def notebooks_dir(self) -> Path:
        return self.root / "labs" / "Source" / self.locale / "notebooks"

    @property
    def setup_dir(self) -> Path:
        return self.root / "setup"

    @property
    def dist_dir(self) -> Path:
        return self.root / "dist"

    @property
    def notes_path(self) -> Path:
        return self.root / "SPECS" / "NOTES.md"

    @property
    def source(self) -> str:
        return f"{self.catalog}.{self.schema}"

    @property
    def ident(self) -> str:
        return re.sub(r"[^a-z0-9_]", "_", self.slug.lower())

    def rel(self, p: Path) -> str:
        try:
            return str(p.resolve().relative_to(self.root))
        except ValueError:
            return str(p)

    # Files
    def _py_files(self, base: Path) -> list[Path]:
        if not base.exists():
            return []
        out = []
        for p in sorted(base.rglob("*.py")):
            parts = p.relative_to(self.root).parts
            if self.reference_dir in parts or "__pycache__" in parts:
                continue
            if any(part.startswith(".") for part in parts):
                continue
            out.append(p)
        return out

    @cached_property
    def candidate_files(self) -> list[Path]:
        """Every .py file that would be packaged if it is a notebook."""
        return self._py_files(self.notebooks_dir) + self._py_files(self.setup_dir)

    @cached_property
    def packaged_files(self) -> list[Path]:
        return [p for p in self.candidate_files if is_notebook(p)]

    def is_course_notebook(self, p: Path) -> bool:
        return self.notebooks_dir in p.parents

    @cached_property
    def lessons(self) -> list[Lesson]:
        out = []
        if not self.notebooks_dir.exists():
            return out
        for module in sorted(self.notebooks_dir.iterdir()):
            if not (module.is_dir() and MODULE_RE.match(module.name)):
                continue
            for p in sorted(module.iterdir()):
                m = LESSON_RE.match(p.name)
                if m and p.is_file():
                    out.append(Lesson(p, m["num"], m["type"], m["title"], module.name,
                                      (int(m["major"]), int(m["minor"]))))
        return sorted(out, key=lambda lesson: lesson.key)

    def includes(self, name: str) -> Path:
        return self.notebooks_dir / "Includes" / name


@dataclass
class Lesson:
    path: Path
    num: str
    type: str
    title: str
    module: str
    key: tuple[int, int]

    @property
    def label(self) -> str:
        return f"{self.num} {self.type} — {self.title}"

    @property
    def needs_setup(self) -> bool:
        return self.type in ("Demo", "Lab")


def find_course_root(start: Path) -> Path:
    for d in [start.resolve(), *start.resolve().parents]:
        if (d / "course.toml").exists():
            return d
    raise VvmError(f"no course.toml found in {start} or its parents — run from a course repository (or -C <dir>)")


def is_notebook(p: Path) -> bool:
    with p.open() as f:
        return f.readline().strip() == NOTEBOOK_HEADER


# --------------------------------------------------------------------------- git


def git(course: Course, *args: str) -> str | None:
    r = subprocess.run(["git", *args], cwd=course.root, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def project_version(course: Course, rev: str | None = None) -> str:
    if rev:
        text = git(course, "show", f"{rev}:pyproject.toml")
        if text is None:
            raise VvmError(f"no pyproject.toml at {rev}")
    else:
        p = course.root / "pyproject.toml"
        if not p.exists():
            raise VvmError("pyproject.toml not found — it carries the course version")
        text = p.read_text()
    version = tomllib.loads(text).get("project", {}).get("version")
    if not version:
        raise VvmError("pyproject.toml has no [project] version")
    return version


def build_info(course: Course) -> dict:
    """`build_id = <version>+g<short commit>[.dirty]` (spec §7.3)."""
    commit = git(course, "rev-parse", "HEAD")
    if not commit:
        raise VvmError("not a git repository with at least one commit — builds must be traceable to a commit")
    version = project_version(course)
    dirty = bool(git(course, "status", "--porcelain", "--", *PACKAGED_PATHS))
    pushed = bool(git(course, "branch", "-r", "--contains", "HEAD"))
    return {
        "course_name": course.name,
        "slug": course.slug,
        "version": version,
        "build_id": f"{version}+g{commit[:7]}" + (".dirty" if dirty else ""),
        "commit": commit,
        "commit_url": f"{course.repo_url}/commit/{commit}",
        "branch": git(course, "rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "dirty": dirty,
        "pushed": pushed,
        "built_on": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def render(text: str, info: dict) -> str:
    """Fill the build placeholders (spec §7.3); asset placeholders are left for install time."""
    if "{{" not in text:
        return text
    values = {
        "course_name": info["course_name"],
        "version_number": info["version"],
        "build_id": info["build_id"],
        "commit": info["commit"],
        "commit_url": info["commit_url"],
        "built_on": info["built_on"],
        "dirty_note": (
            "**Built from uncommitted changes** — this build does not match any commit exactly."
            if info["dirty"] else "Built from a clean checkout of the commit above."
        ),
    }
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def changed_files(course: Course, since: str) -> list[str]:
    out = git(course, "diff", "--name-only", f"{since}", "--", "labs", "setup")
    if out is None:
        raise VvmError(f"can't diff against {since!r} — not a known commit")
    return [line for line in out.splitlines() if line]


def changed_lessons(course: Course, since: str) -> tuple[list[Lesson], bool]:
    """Lessons whose own file or Classroom setup changed since `since` (a commit), plus
    whether something shared (setup/, shared Includes) changed — then every lesson is affected."""
    files = set(changed_files(course, since))
    inc = course.rel(course.notebooks_dir / "Includes")
    shared = any(f.startswith("setup/") for f in files) or any(
        f.startswith(inc + "/") and Path(f).name in SHARED_INCLUDES for f in files
    )
    if shared:
        return list(course.lessons), True
    out = []
    for lesson in course.lessons:
        own = {course.rel(lesson.path), f"{inc}/Classroom-Setup-{lesson.num}.py"}
        if own & files:
            out.append(lesson)
    return out, False


# --------------------------------------------------------------------------- notes


def notes_text(course: Course) -> str:
    return course.notes_path.read_text() if course.notes_path.exists() else ""


def notes_sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) for each `## ` section of NOTES.md."""
    sections, heading, body = [], None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections.append((heading, "\n".join(body)))
            heading, body = line[3:].strip(), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections.append((heading, "\n".join(body)))
    return sections


def last_setup_minutes(course: Course) -> float | None:
    found = re.findall(r"setup_minutes:\s*([\d.]+)", notes_text(course))
    return float(found[-1]) if found else None


def last_tested_build(course: Course, exclude: str | None = None) -> str | None:
    """The most recent build id recorded in NOTES.md, other than `exclude`."""
    ids = [m.group(0) for m in BUILD_ID_RE.finditer(notes_text(course))]
    ids = [i for i in ids if i != exclude and not i.endswith(".dirty")]
    return ids[-1] if ids else None


def resolve_build(course: Course, build_id: str) -> tuple[str, dict]:
    m = BUILD_ID_RE.fullmatch(build_id.strip())
    if not m:
        raise VvmError(f"{build_id!r} is not a build id (<version>+g<commit>[.dirty])")
    commit = git(course, "rev-parse", "--verify", "--quiet", f"{m['short']}^{{commit}}")
    if not commit:
        raise VvmError(f"commit {m['short']} not found in this repository (try git fetch)")
    return commit, m.groupdict()


# --------------------------------------------------------------------------- lint


@dataclass
class Finding:
    rule: str
    severity: str  # "error" | "warning"
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"{loc}: {self.severity} [{self.rule}] {self.message}"


@dataclass
class Line:
    no: int
    code: str  # MAGIC prefix stripped
    markdown: bool
    comment: bool  # a plain Python comment (not a MAGIC line)


@dataclass
class Notebook:
    path: Path
    text: str
    lines: list[Line] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> Notebook:
        text = path.read_text()
        nb = cls(path, text)
        in_md, cell_started = False, False
        for i, raw in enumerate(text.splitlines(), start=1):
            if raw.strip() == CELL_SEP:
                in_md, cell_started = False, False
                continue
            is_magic = raw.startswith(MAGIC)
            code = raw[len(MAGIC):].lstrip() if is_magic else raw
            comment = (not is_magic) and raw.lstrip().startswith("#")
            # A cell's type is set by its first line that isn't a plain comment — so the
            # notebook header and the `# /// script` block don't hide a `%md` cell.
            if not cell_started and raw.strip() and not comment:
                cell_started = True
                in_md = is_magic and code.startswith("%md")
            nb.lines.append(Line(i, code, in_md, comment))
        return nb

    def code_lines(self):
        """Executable lines: not markdown, not Python comments."""
        return (ln for ln in self.lines if not ln.markdown and not ln.comment)


WAIVER_RE = re.compile(r"vvm:\s*allow\s+([a-z0-9-]+)(?:\s*(?:—|–|--|-|:)\s*(\S.*))?")

EMAIL_RE = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
EMAIL_ALLOWED = re.compile(r"@example\.(com|org|net)$|^vocuser\d+@vocareum\.com$", re.I)
HOST_RES = [
    re.compile(r"\bdbc-[0-9a-f]{8}-[0-9a-f]{4}\b"),
    re.compile(r"\badb-\d{6,}\.\d+\b"),
    re.compile(r"\b[\w-]+\.cloud\.databricks\.com\b"),
    re.compile(r"\b[\w-]+\.azuredatabricks\.net\b"),
    re.compile(r"\b[\w.-]+\.gcp\.databricks\.com\b"),
    re.compile(r"\b[\w-]+\.databricksapps\.com\b"),
]
TOKEN_RES = [
    re.compile(r"\bdapi[0-9a-f]{32}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bgithub_pat_\w{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[\w-]{10,}"),
]
GPU_RES = [
    re.compile(r"\b(?:g4dn|g5|g5g|g6|g6e|gr6|p3|p3dn|p4d|p4de|p5|p5e)\.\d*x?large\b"),
    re.compile(r"\bhardware_accelerator\b"),
    re.compile(r"\bGPU_\w+"),
    re.compile(r"-gpu-ml-"),
    re.compile(r"\bStandard_N[CDV]\w*"),
    re.compile(r"\ba2-(?:high|ultra|mega)gpu\b"),
]
CREATE_CATALOG_RE = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?CATALOG\b|\bcatalogs\.create\(", re.I)
PIP_RE = re.compile(r"(?:^|[\s%!;])(?:python3?\s+-m\s+)?pip3?\s+install\s+(?P<args>.*)$")
URL_RE = re.compile(r"\bhttps?://[^\s'\"()]+")
FETCH_RE = re.compile(
    r"\b(?:urlopen|urlretrieve|requests\.(?:get|post|request)|httpx\.|curl\b|wget\b|git\s+clone|"
    r"read_csv|read_parquet|read_json|load_dataset)"
)
HUB_RE = re.compile(r"\b(?:from_pretrained|hf_hub_download|snapshot_download)\s*\(")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
LINK_RE = re.compile(r"\]\((\$[^)\n]+)\)")
RUN_RE = re.compile(r"^%run\s+(.+?)\s*$")
ENV_VERSION_RE = re.compile(r'^#\s*environment_version\s*=\s*"?([^"\s]+)"?\s*$')
ACADEMY_RE = re.compile(r"Databricks\s+Academy", re.I)
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
EXACT_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*(?:[a-z0-9.+-]*)$")

PIP_FLAGS = {"-q", "--quiet", "-U", "--upgrade", "--no-deps", "--force-reinstall", "--no-cache-dir",
             "--no-index", "--pre", "-qq", "--disable-pip-version-check", "--no-build-isolation"}
PIP_PATH_OPTS = {"-r", "--requirement", "-c", "--constraint", "-f", "--find-links"}
PIP_FORBIDDEN_OPTS = {"-i", "--index-url", "--extra-index-url", "-e", "--editable", "--trusted-host"}


class Linter:
    def __init__(self, course: Course):
        self.course = course
        self.findings: list[Finding] = []
        self._waivers: dict[Path, dict[str, str]] = {}
        self.notebook_stems = {p.with_suffix("").resolve() for p in course.packaged_files}
        # Folders that contain packaged notebooks: `$./M01 - …` links to a module folder are fine.
        self.notebook_dirs = {d for p in self.notebook_stems for d in p.parents}

    def add(self, rule, severity, path: Path | str, line, message):
        if isinstance(path, Path):
            if rule in self._waivers.get(path, {}):
                return
            path = self.course.rel(path)
        self.findings.append(Finding(rule, severity, path, line, message))

    def run(self) -> list[Finding]:
        c = self.course
        self.check_course_toml()
        self.check_reference_material()
        self.check_pins()
        lessons = {lesson.path.resolve(): lesson for lesson in c.lessons}
        for p in c.candidate_files:
            text = p.read_text()
            self._waivers[p] = self.parse_waivers(p, text)
            if not is_notebook(p):
                sev = "error" if c.is_course_notebook(p) else "warning"
                self.add("notebook-header", sev, p, 1,
                         f"first line must be '{NOTEBOOK_HEADER}' — the build skips this file")
                continue
            nb = Notebook.load(p)
            course_nb = c.is_course_notebook(p)
            self.check_env_header(nb)
            if course_nb:
                self.check_no_create_catalog(nb)
                self.check_no_runtime_download(nb)
                self.check_links(nb)
            self.check_run_targets(nb)
            self.check_no_gpu(nb)
            self.check_identity(nb)
            self.check_placeholders(nb)
            self.check_branding(nb)
            lesson = lessons.get(p.resolve())
            if lesson:
                self.check_lesson(nb, lesson)
        if not c.notebooks_dir.exists():
            self.add("course-toml", "error", c.rel(c.notebooks_dir), 0, "course notebooks folder not found")
        elif not (c.notebooks_dir / f"{c.entry}.py").exists():
            self.add("course-toml", "error", "course.toml", 0,
                     f"entry notebook {c.entry!r} not found in {c.rel(c.notebooks_dir)}")
        return sorted(self.findings, key=lambda f: (f.path, f.line, f.rule))

    def parse_waivers(self, path: Path, text: str) -> dict[str, str]:
        out = {}
        for i, line in enumerate(text.splitlines(), start=1):
            m = WAIVER_RE.search(line)
            if not m:
                continue
            if not m[2]:
                self.add("waiver", "warning", self.course.rel(path), i,
                         f"waiver for {m[1]!r} has no reason — write '# vvm: allow {m[1]} — <reason>'; ignored")
                continue
            out[m[1]] = m[2].strip()
        return out

    # --- course-level rules
    def check_course_toml(self):
        c = self.course
        for i, step in enumerate(c.setup_steps, start=1):
            name = step.get("name", f"#{i}")
            nb = step.get("notebook")
            if not nb:
                self.add("course-toml", "error", "course.toml", 0, f"setup step {name}: no notebook")
            elif not (c.root / f"{nb}.py").exists():
                self.add("course-toml", "error", "course.toml", 0, f"setup step {name}: notebook {nb} not found")
            if not step.get("outputs"):
                self.add("course-toml", "warning", "course.toml", 0,
                         f"setup step {name}: no outputs — it can't be skipped when already done")
            if step.get("target", "source") not in ("source", "reference"):
                self.add("course-toml", "error", "course.toml", 0,
                         f"setup step {name}: target must be 'source' or 'reference'")
        for ua in c.user_assets:
            for k in ("name", "staged", "dest"):
                if not ua.get(k):
                    self.add("course-toml", "error", "course.toml", 0, f"user_assets {ua.get('name', '?')}: missing {k}")

    def check_reference_material(self):
        c = self.course
        tracked = git(c, "ls-files", "--", c.reference_dir)
        if tracked:
            n = len(tracked.splitlines())
            self.add("reference-material", "error", c.reference_dir, 0,
                     f"{n} file(s) of reference material tracked by git — run: git rm -r --cached {c.reference_dir}")
        ref = c.root / c.reference_dir
        if ref.exists() and git(c, "check-ignore", "-q", c.reference_dir) is None:
            self.add("reference-material", "warning", c.reference_dir, 0,
                     "reference material is not git-ignored — add it to .gitignore")

    def check_pins(self):
        c = self.course
        versions = c.setup_dir / "VERSIONS.md"
        vtext = versions.read_text() if versions.exists() else None
        for a in c.assets:
            name = a.get("name", "?")
            if a.get("kind") not in ASSET_KINDS:
                self.add("pins", "error", "course.toml", 0,
                         f"asset {name}: kind must be one of {', '.join(sorted(ASSET_KINDS))}")
            pin = a.get("ref") or a.get("version") or a.get("sha256")
            if a.get("ref") and not SHA1_RE.match(a["ref"]):
                self.add("pins", "error", "course.toml", 0, f"asset {name}: ref must be a full 40-character commit")
            elif a.get("version") and not EXACT_VERSION_RE.match(str(a["version"])):
                self.add("pins", "error", "course.toml", 0, f"asset {name}: version must be exact (e.g. 1.2.3)")
            elif a.get("sha256") and not re.fullmatch(r"[0-9a-f]{64}", a["sha256"]):
                self.add("pins", "error", "course.toml", 0, f"asset {name}: sha256 must be 64 hex characters")
            elif not pin:
                self.add("pins", "error", "course.toml", 0, f"asset {name}: no pin (ref, version or sha256)")
            if vtext is None:
                self.add("pins", "error", c.rel(versions), 0, f"missing — asset {name} must be listed there")
            elif pin and (name not in vtext or str(pin) not in vtext):
                self.add("pins", "error", c.rel(versions), 0, f"asset {name} @ {pin} is not listed")

    # --- per-notebook rules
    def check_env_header(self, nb: Notebook):
        if "Includes" in nb.path.relative_to(self.course.root).parts:
            return  # %run targets inherit the caller's environment
        # Lessons and course notebooks must pin it; setup notebooks should (warning).
        sev = "error" if self.course.is_course_notebook(nb.path) else "warning"
        lines = nb.text.splitlines()[1:12]
        if not lines or lines[0].strip() != "# /// script":
            self.add("env-header", sev, nb.path, 2,
                     f"missing serverless environment header (# /// script … environment_version = "
                     f"\"{self.course.environment_version}\" … # ///) right after the first line")
            return
        for i, line in enumerate(lines[1:], start=3):
            if line.strip() == "# ///":
                break
            m = ENV_VERSION_RE.match(line.strip())
            if m:
                if m[1] != self.course.environment_version:
                    self.add("env-header", sev, nb.path, i,
                             f"environment_version {m[1]} ≠ course.toml {self.course.environment_version}")
                return
        self.add("env-header", sev, nb.path, 2, "environment header has no environment_version")

    def check_no_create_catalog(self, nb: Notebook):
        for ln in nb.code_lines():
            if CREATE_CATALOG_RE.search(ln.code):
                self.add("no-create-catalog", "error", nb.path, ln.no,
                         "learner notebooks must not create catalogs — they're dropped with the learner; "
                         "use ensure_schema()")

    def check_no_gpu(self, nb: Notebook):
        for ln in nb.code_lines():
            for r in GPU_RES:
                m = r.search(ln.code)
                if m:
                    self.add("no-gpu", "error", nb.path, ln.no,
                             f"GPU reference {m.group(0)!r} — no GPU on Vocareum; precompute in setup or drop")
                    break

    def check_no_runtime_download(self, nb: Notebook):
        for ln in nb.code_lines():
            m = PIP_RE.search(ln.code)
            if m:
                self._check_pip(nb, ln, m["args"])
                continue
            if HUB_RE.search(ln.code) and "/Volumes/" not in ln.code:
                self.add("no-runtime-download", "error", nb.path, ln.no,
                         "downloads a model from a hub at lesson time — stage it in /Volumes in setup")
                continue
            if URL_RE.search(ln.code) and FETCH_RE.search(ln.code):
                self.add("no-runtime-download", "error", nb.path, ln.no,
                         f"fetches {URL_RE.search(ln.code).group(0)} at lesson time — stage it in setup")

    def _check_pip(self, nb: Notebook, ln: Line, args: str):
        try:
            tokens = shlex.split(args, comments=True)
        except ValueError:
            tokens = args.split()
        problems, unverifiable, bare = [], [], []
        no_index = "--no-index" in tokens
        find_links_volume = False
        i = 0
        while i < len(tokens):
            t = tokens[i]
            opt, _, inline = t.partition("=") if t.startswith("--") else (t, "", "")
            if opt in PIP_FORBIDDEN_OPTS:
                problems.append(f"{opt} (another index or source)")
            elif opt in PIP_PATH_OPTS:
                value = inline or (tokens[i + 1] if i + 1 < len(tokens) else "")
                if not inline:
                    i += 1
                if value.startswith("/Volumes/"):
                    if opt in ("-f", "--find-links"):
                        find_links_volume = True
                elif "$" in value or "{" in value:
                    unverifiable.append(value)
                else:
                    problems.append(f"{opt} {value} (not under /Volumes/)")
            elif t in PIP_FLAGS or (t.startswith("-") and "://" not in t):
                pass
            elif "://" in t or t.startswith("git+"):
                problems.append(t)
            elif t.startswith("/Volumes/"):
                pass
            elif "$" in t or "{" in t:
                unverifiable.append(t)
            else:
                bare.append(t)
            i += 1
        if bare and not (no_index and find_links_volume):
            problems.append(f"{', '.join(bare)} from PyPI")
        if problems:
            self.add("no-runtime-download", "error", nb.path, ln.no,
                     "pip installs from the internet: " + "; ".join(problems)
                     + " — install only from /Volumes/… (staged by setup, pinned in VERSIONS.md)")
        elif unverifiable:
            self.add("no-runtime-download", "warning", nb.path, ln.no,
                     f"can't verify that {', '.join(unverifiable)} points to /Volumes/")

    def check_identity(self, nb: Notebook):
        for ln in nb.lines:
            for m in EMAIL_RE.finditer(ln.code):
                if not EMAIL_ALLOWED.search(m.group(0)):
                    self.add("no-hardcoded-identity", "error", nb.path, ln.no,
                             f"hard-coded email {m.group(0)} — use user_email")
            for r in HOST_RES:
                m = r.search(ln.code)
                if m:
                    self.add("no-hardcoded-identity", "error", nb.path, ln.no,
                             f"hard-coded workspace or app host {m.group(0)}")
            for r in TOKEN_RES:
                if r.search(ln.code):
                    self.add("no-hardcoded-identity", "error", nb.path, ln.no, "looks like a secret token")

    def check_placeholders(self, nb: Notebook):
        allowed = BUILD_PLACEHOLDERS | ASSET_PLACEHOLDERS
        for ln in nb.lines:
            for m in PLACEHOLDER_RE.finditer(ln.code):
                if m[1] not in allowed:
                    self.add("placeholders", "error", nb.path, ln.no,
                             f"unknown placeholder {{{{{m[1]}}}}} — known: {', '.join(sorted(allowed))}")

    def check_branding(self, nb: Notebook):
        if self.course.branding != "neutral":
            return
        for ln in nb.lines:
            if ACADEMY_RE.search(ln.code):
                self.add("branding", "error", nb.path, ln.no, "'Databricks Academy' in a neutral-branded course")

    def _resolves(self, base: Path, target: str) -> bool:
        p = (base / urllib.parse.unquote(target)).resolve()
        return p in self.notebook_stems or p.with_suffix("") in self.notebook_stems or p in self.notebook_dirs

    def check_links(self, nb: Notebook):
        for ln in nb.lines:
            for m in LINK_RE.finditer(ln.code):
                target = m[1][1:].split("#", 1)[0].strip()
                if not self._resolves(nb.path.parent, target):
                    self.add("agenda-links", "error", nb.path, ln.no,
                             f"link {m[1]} doesn't resolve to a packaged notebook")

    def check_run_targets(self, nb: Notebook):
        for ln in nb.code_lines():
            m = RUN_RE.match(ln.code.strip())
            if m:
                target = m[1].strip().strip('"\'')
                if not self._resolves(nb.path.parent, target):
                    self.add("run-targets", "error", nb.path, ln.no,
                             f"%run {target} doesn't resolve to a packaged notebook")

    def check_lesson(self, nb: Notebook, lesson: Lesson):
        runs = [(ln, RUN_RE.match(ln.code.strip())[1]) for ln in nb.code_lines() if RUN_RE.match(ln.code.strip())]
        setups = [(ln, t) for ln, t in runs if "Classroom-Setup-" in t]
        expected = f"Classroom-Setup-{lesson.num}"
        if lesson.needs_setup and not setups:
            self.add("classroom-setup", "error", nb.path, 0,
                     f"{lesson.type} must %run ../Includes/{expected} (cold start)")
        for ln, t in setups:
            if Path(t).name != expected:
                self.add("classroom-setup", "warning", nb.path, ln.no, f"runs {Path(t).name}, expected {expected}")
        if lesson.needs_setup:
            has_finish = any("finish(" in ln.code for ln in nb.code_lines())
            has_checks = any(t.endswith("_checks") for _, t in runs)
            if not has_finish:
                self.add("check-your-work", "error", nb.path, 0,
                         f"{lesson.type} must end with Check your work: %run ../Includes/_checks, then finish(...)")
            elif not has_checks:
                self.add("check-your-work", "error", nb.path, 0, "calls finish(...) without %run ../Includes/_checks")


def lint(course: Course) -> list[Finding]:
    return Linter(course).run()


def print_findings(findings: list[Finding]) -> tuple[int, int]:
    for f in findings:
        print(f, file=sys.stderr if f.severity == "error" else sys.stdout)
    errors = sum(f.severity == "error" for f in findings)
    return errors, len(findings) - errors


def cmd_lint(course: Course, args) -> int:
    errors, warnings = print_findings(lint(course))
    print(f"\nvvm lint: {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


# --------------------------------------------------------------------------- build


def archives(course: Course) -> dict[str, tuple[list[Path], Path]]:
    """name -> (files, root the archive paths are relative to) — spec §7.3."""
    course_nbs = [p for p in course.packaged_files if course.is_course_notebook(p)]
    setup_nbs = [p for p in course.packaged_files if course.setup_dir in p.parents]
    return {
        f"{course.slug}-labs.zip": (course_nbs, course.notebooks_dir),
        f"{course.slug}-setup.zip": (setup_nbs + course_nbs, course.root),
    }


def cmd_build(course: Course, args) -> int:
    findings = lint(course)
    errors, warnings = print_findings(findings)
    if errors:
        print(f"\nvvm build: {errors} lint error(s) block the build — fix them, or waive with "
              f"'# vvm: allow <rule> — <reason>'", file=sys.stderr)
        return 1
    info = build_info(course)
    course.dist_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, (files, root) in archives(course).items():
        if not files:
            raise VvmError(f"{name}: no notebooks to package")
        path = course.dist_dir / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                zf.writestr(str(p.relative_to(root)), render(p.read_text(), info))
        manifest[name] = {
            "files": [str(p.relative_to(root)) for p in files],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        print(f"Built dist/{name} ({len(files)} notebooks)")
    (course.dist_dir / "BUILD_INFO.json").write_text(json.dumps({**info, "archives": manifest}, indent=2) + "\n")
    print(f"\nBuild {info['build_id']} — commit {info['commit']} — dist/BUILD_INFO.json")
    if info["dirty"]:
        warn(f"uncommitted changes in {', '.join(PACKAGED_PATHS)}: this build can't be traced to a commit. "
             "Don't upload it — commit, push and rebuild.")
    elif not info["pushed"]:
        warn("commit not on any remote branch: the Version Info commit link won't resolve. "
             "Push before uploading.")
    return 0


# --------------------------------------------------------------------------- which


def cmd_which(course: Course, args) -> int:
    commit, parts = resolve_build(course, args.build_id)
    print(git(course, "log", "-1", "--format=commit %H%nauthor %an%ndate   %ad%n%n    %s", commit))
    version = project_version(course, commit)
    print()
    if version != parts["version"]:
        warn(f"pyproject.toml at {commit[:7]} says version {version}, not {parts['version']}")
    tags = git(course, "tag", "--points-at", commit)
    branches = git(course, "branch", "-a", "--contains", commit, "--format=%(refname:short)")
    print(f"tags:     {tags.replace(chr(10), ', ') if tags else '—'}")
    print(f"branches: {branches.replace(chr(10), ', ') if branches else '— (not on any branch: unpushed or rebased away)'}")
    print(f"link:     {course.repo_url}/commit/{commit}")
    if parts["dirty"]:
        warn("dirty build: built from uncommitted changes on top of this commit — the exact content is unknown")
    hits = [(h, b) for h, b in notes_sections(notes_text(course)) if args.build_id in h or args.build_id in b]
    print(f"\nSPECS/NOTES.md: {len(hits)} entr{'y' if len(hits) == 1 else 'ies'} for {args.build_id}")
    for h, b in hits:
        print(f"\n## {h}\n{b.strip()}")
    return 0


# --------------------------------------------------------------------------- form


def form_rows(course: Course) -> list[tuple[str, str, str, str]]:
    s = course.slug
    lab_time = f"{course.lab_time_hours} hours" if course.lab_time_hours else "≈ 2× learner time (set vocareum.lab_time_hours)"
    return [
        ("Basic", "Course Name", f"{course.name} – <purpose>", "Unique per Vocareum account"),
        ("Basic", "Max Users per Workspace", str(course.max_users),
         "Shared data loaded once per workspace; learners isolated by schema"),
        ("Basic", "Lab Time", lab_time, "Room to finish background jobs"),
        ("Basic", "Allow lab to be stopped", "On" if course.allow_lab_stop else "Off", "No lab-end hook to clean up"),
        ("Basic", "Vocareum Org", course.org, "Can't be moved later"),
        ("Basic", "Template", course.template, "The Genie Code template adds the Consumer entitlement"),
        ("Lab Content", "Mode", "Prepared archive / notebook", ""),
        ("Lab Content", "File", f"dist/{s}-labs.zip", ""),
        ("Lab Content", "Entry Notebook", course.entry, ""),
        ("Lab Content", "Top-Level Folder Name", "(blank)", "Defaults to the file name"),
        ("Workspace setup", "Enable workspace setup notebook", "On", "Loads shared data per workspace"),
        ("Workspace setup", "Source", f"dist/{s}-setup.zip", ""),
        ("Workspace setup", "Entry", "setup/workspace_setup", ""),
        ("Workspace setup", "Timeout (minutes)", str(course.setup_timeout_min),
         "Default 20 too short for data + reference runs; max 120"),
        ("User Resources", "User Catalog & Schema", "user-owned schema in dbacademy catalog (default)",
         "Lessons resolve `out` from ops.meta"),
        ("User Resources", "Manage Schema", "On", ""),
        ("User Resources", "Auto-create personal cluster", "Off", "Lessons run on serverless"),
        ("Data Sideload", "—", "(empty)", "workspace_setup loads the data"),
    ]


def form_warnings(course: Course) -> list[str]:
    out = []
    measured = last_setup_minutes(course)
    if course.setup_timeout_min > SETUP_TIMEOUT_MAX:
        out.append(f"setup_timeout_min {course.setup_timeout_min} is above the form's max of {SETUP_TIMEOUT_MAX}")
    if measured is None:
        out.append("setup time not measured yet — run `vvm smoke` so the timeout can be checked")
    elif course.setup_timeout_min < 2 * measured:
        out.append(f"setup_timeout_min {course.setup_timeout_min} < 2 × last measured setup "
                   f"({measured:g} min) — raise it (max {SETUP_TIMEOUT_MAX})")
    if course.template.lower().startswith("genie code"):
        out.append("template 'Genie Code' adds the Consumer entitlement, which may block notebooks and jobs — "
                   "use 'Data Science'")
    if course.allow_lab_stop:
        out.append("allow_lab_stop = true: there's no lab-end hook, so stopped labs leave learner resources running")
    if not course.lab_time_hours:
        out.append("vocareum.lab_time_hours not set")
    return out


def cmd_form(course: Course, args) -> int:
    config = course.root / "vocareum" / "config.json"
    if config.exists() and not args.full:
        return form_diff(course, config)
    print(f"# Course Vending Machine form — {course.name}\n")
    print("| Section | Field | Value | Reason |\n|---------|-------|-------|--------|")
    for row in form_rows(course):
        print("| " + " | ".join(row) + " |")
    print("\nThen: open View config.json, save it as vocareum/config.json, commit it. "
          "You click Create Course — vvm never does.")
    for w in form_warnings(course):
        warn(w)
    return 0


def form_diff(course: Course, config: Path) -> int:
    """Spec §8.1: compare with the course.toml of the commit that last saved config.json."""
    full = argparse.Namespace(full=True)
    rev = git(course, "log", "-1", "--format=%H", "--", course.rel(config))
    if not rev:
        warn("vocareum/config.json isn't committed — commit it, so later changes can be diffed. Full sheet:")
        return cmd_form(course, full)
    old_text = git(course, "show", f"{rev}:course.toml")
    if old_text is None:
        print(f"course.toml didn't exist at {rev[:7]}, when config.json was saved — full sheet:\n")
        return cmd_form(course, full)
    old = Course(course.root, data=tomllib.loads(old_text))
    old_rows = {(s, f): v for s, f, v, _ in form_rows(old)}
    changes = [(s, f, old_rows.get((s, f), "—"), v, r) for s, f, v, r in form_rows(course)
               if old_rows.get((s, f)) != v]
    print(f"Changes since vocareum/config.json was saved ({rev[:7]}):\n")
    if changes:
        print("| Section | Field | Was | Now | Reason |\n|---|---|---|---|---|")
        for s, f, was, now, r in changes:
            print(f"| {s} | {f} | {was} | {now} | {r} |")
    else:
        print("No form settings changed.")
    if changed_files(course, rev):
        print("\nUpload the new zips: lessons or setup changed since then.")
    print("\nAfter updating the course, save View config.json again and commit it.")
    for w in form_warnings(course):
        warn(w)
    return 0


# --------------------------------------------------------------------------- checklist


def lesson_features(course: Course, lesson: Lesson) -> dict:
    text = lesson.path.read_text()
    setup = course.includes(f"Classroom-Setup-{lesson.num}.py")
    setup_text = setup.read_text() if setup.exists() else ""
    return {
        "short_on_time": bool(re.search(r"Short on time\?", text)),
        "finish": "finish(" in text,
        "setup": setup.exists(),
        "user_assets": "ensure_user_assets(" in setup_text,
        "tables": re.findall(r"ensure_table\(\s*[\"']([\w]+)[\"']", setup_text),
    }


def cmd_checklist(course: Course, args) -> int:
    info_path = course.dist_dir / "BUILD_INFO.json"
    if info_path.exists():
        info = json.loads(info_path.read_text())
        current = build_info(course)
        if info["build_id"] != current["build_id"]:
            warn(f"dist/BUILD_INFO.json is {info['build_id']}, the working tree is {current['build_id']} — "
                 "checklist written for the built one; rebuild if that's not what you uploaded")
    else:
        warn("no dist/BUILD_INFO.json — run `vvm build` first; using the working tree's build id")
        info = build_info(course)
    bid = info["build_id"]
    if info.get("dirty"):
        warn("dirty build — a test of it can't be traced to a commit")

    last = args.since or last_tested_build(course, exclude=bid)
    changed, shared = [], False
    if last:
        try:
            commit = resolve_build(course, last)[0] if BUILD_ID_RE.fullmatch(last) else last
            changed, shared = changed_lessons(course, commit)
        except VvmError as e:
            warn(f"can't compare with {last}: {e}")
            last = None
    changed_set = {lesson.num for lesson in changed}

    out: list[str] = []
    w = out.append
    w(f"# Test checklist — {course.name} — build `{bid}`\n")
    w(f"Commit: {info['commit_url']}  ")
    w(f"Generated by `vvm checklist` on {dt.date.today().isoformat()}. "
      "Run it as a student on the Vocareum course; tick each item, note timings, and copy the results to "
      "`SPECS/NOTES.md` with the build id.\n")
    if last:
        w(f"Compared with the last tested build `{last}`: "
          + ("**shared setup or Includes changed — re-test every lesson.**" if shared
             else f"{len(changed)} lesson(s) new or changed, marked **new/changed**.") + "\n")
    else:
        w("No earlier tested build in `SPECS/NOTES.md` — test every lesson.\n")

    w("## 0. Before you start\n")
    w(f"- [ ] The course was created/updated from this build's zips: `{course.slug}-labs.zip` and "
      f"`{course.slug}-setup.zip`, `dist/BUILD_INFO.json` shows `{bid}`")
    w(f"- [ ] Workspace setup timeout is {course.setup_timeout_min} min; template {course.template}; "
      f"*Allow lab to be stopped* {'on' if course.allow_lab_stop else 'off'}\n")

    w("## 1. Workspace setup\n")
    w("- [ ] The workspace setup job succeeded — duration: ___ min")
    w("- [ ] Re-running it skips the completed steps")
    for step in course.setup_steps:
        schema = course.reference_schema if step.get("target") == "reference" else course.schema
        outs = ", ".join(f"`{course.catalog}.{schema}.{o}`" for o in step.get("outputs", []))
        w(f"- [ ] Step `{step.get('name')}`: {outs or '(no outputs declared)'} exist")
    for a in course.assets:
        w(f"- [ ] Asset `{a.get('name')}` staged in `/Volumes/{course.catalog}/{course.schema}/assets/`")
    w(f"- [ ] `SELECT * FROM {course.source}.course_build` shows `{bid}`\n")

    w("## 2. Student entry\n")
    w(f"- [ ] The lab opens on `{course.entry}`; every link in it opens the right lesson")
    w(f"- [ ] `Version Info` shows `{bid}`, and its commit link resolves\n")

    w("## 3. Lessons\n")
    first_assets = True
    for lesson in course.lessons:
        f = lesson_features(course, lesson)
        mark = " — **new/changed**" if (shared or lesson.num in changed_set or not last) and last else ""
        w(f"### {lesson.label}{mark}\n")
        if f["setup"]:
            w(f"- [ ] Classroom setup prints `Course build: {bid}` and `Your outputs (write): … "
              "[lab platform metadata]` (not `[workshop default]`)")
            if f["tables"]:
                w(f"- [ ] Inputs in place: {', '.join(f'`{t}`' for t in f['tables'])}")
            if f["user_assets"] and course.user_assets and first_assets:
                names = ", ".join(f"`{ua.get('name')}`" for ua in course.user_assets)
                w(f"- [ ] Per-user assets installed: {names}")
                first_assets = False
        if lesson.type == "Lecture" and not f["setup"]:
            w("- [ ] Renders; interactive cells work; links open")
        if f["short_on_time"]:
            w("- [ ] *Short on time?* puts the expected output in place")
        if f["finish"]:
            w("- [ ] *Check your work*: PASS")
        w("- [ ] Time taken: ___ min (note slow steps)\n")

    w("## 4. Cold start\n")
    later = [lesson.label for lesson in course.lessons if lesson.needs_setup][-2:]
    w("- [ ] In a new session, open the later lessons first ("
      + (", ".join(later) if later else "any lesson") + ") and run them: their Classroom setup puts "
      "the inputs in place\n")

    w("## 5. After the test\n")
    w("- [ ] List what learners left running (jobs, clusters, endpoints, experiments) — there's no lab-end "
      "hook; delete it")
    w(f"- [ ] Results and timings written to `SPECS/NOTES.md` under a heading with `{bid}`")
    w("- [ ] Unverified platform facts checked on this run moved to *Confirmed* in the skill's "
      "`references/known-gaps.md` (ops.meta keys, `account users` grants, staging from GitHub/PyPI, …)")

    path = course.root / "SPECS" / f"CHECKLIST-{bid}.md"
    if path.exists() and not args.force:
        raise VvmError(f"{course.rel(path)} exists — use --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    print(f"Wrote {course.rel(path)} ({len(course.lessons)} lessons"
          + (f", {len(changed)} new/changed" if last else "") + ")")
    return 0


# --------------------------------------------------------------------------- workspace


def workspace_client(profile: str | None):
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as e:  # run with plain python instead of uv
        raise VvmError("databricks-sdk not installed — run vvm with `uv run`") from e
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def do_install(course: Course, w, email: str | None, target: str | None) -> tuple[str, dict]:
    from databricks.sdk.service.workspace import ImportFormat, Language

    info = build_info(course)
    email = email or w.current_user.me().user_name
    target = (target or f"/Users/{email}/{course.slug}-vvm").rstrip("/")
    files = course.packaged_files
    print(f"Importing {len(files)} notebooks (build {info['build_id']}) -> {target}")
    made = set()
    for p in files:
        rel = p.relative_to(course.root).with_suffix("")
        ws_path = f"{target}/{rel.as_posix()}"
        parent = ws_path.rsplit("/", 1)[0]
        if parent not in made:
            w.workspace.mkdirs(parent)
            made.add(parent)
        content = base64.b64encode(render(p.read_text(), info).encode()).decode()
        w.workspace.import_(ws_path, content=content, format=ImportFormat.SOURCE,
                            language=Language.PYTHON, overwrite=True)
    print(f"Imported {len(files)} notebooks")
    return target, info


def cmd_install(course: Course, args) -> int:
    w = workspace_client(args.profile)
    do_install(course, w, args.email, args.target)
    return 0


def smoke_names(course: Course, args) -> dict:
    prefix = args.prefix or f"vvm_{course.ident}"
    return {
        "catalog": args.catalog,
        "schema": f"{prefix}_data",
        "reference_schema": f"{prefix}_reference",
        "user_schema": f"{prefix}_out",
    }


def cmd_smoke(course: Course, args) -> int:
    from databricks.sdk.service import jobs

    lessons = list(course.lessons)
    if args.changed_since:
        since = args.changed_since
        if since == "last":
            since = last_tested_build(course)
            if not since:
                raise VvmError("no tested build in SPECS/NOTES.md to compare with")
        commit = resolve_build(course, since)[0] if BUILD_ID_RE.fullmatch(since) else since
        lessons, shared = changed_lessons(course, commit)
        print(f"Changed since {since}: {'everything (shared setup/Includes)' if shared else len(lessons)} lesson(s)")
    if args.order == "reverse":
        lessons.reverse()
    elif args.order == "random":
        random.shuffle(lessons)

    names = smoke_names(course, args)
    w = workspace_client(args.profile)
    target, info = do_install(course, w, None, args.target)
    started = dt.datetime.now(dt.timezone.utc)
    state = {"started_at": started.isoformat(), "started_ms": int(started.timestamp() * 1000),
             "profile": args.profile, "target": target, "build_id": info["build_id"], **names}
    course.dist_dir.mkdir(exist_ok=True)
    (course.dist_dir / SMOKE_STATE).write_text(json.dumps(state, indent=2) + "\n")

    common = {"catalog": names["catalog"], "schema": names["schema"], "reference_schema": names["reference_schema"]}
    tasks, prev = [], None
    if not args.skip_setup:
        tasks.append(jobs.SubmitTask(
            task_key="workspace_setup",
            notebook_task=jobs.NotebookTask(
                notebook_path=f"{target}/setup/workspace_setup",
                base_parameters={**common, "learner_group": "", "force_reload": "false"}),
            timeout_seconds=SETUP_TIMEOUT_MAX * 60))
        prev = "workspace_setup"
    keys = {}
    for i, lesson in enumerate(lessons):
        key = f"lesson_{lesson.num.replace('.', '_')}"
        keys[key] = lesson
        rel = lesson.path.relative_to(course.root).with_suffix("").as_posix()
        tasks.append(jobs.SubmitTask(
            task_key=key,
            notebook_task=jobs.NotebookTask(
                notebook_path=f"{target}/{rel}",
                base_parameters={**common, "user_catalog": names["catalog"], "user_schema": names["user_schema"]}),
            depends_on=[jobs.TaskDependency(task_key=prev)] if prev else None,
            run_if=jobs.RunIf.ALL_DONE if prev else None,
            timeout_seconds=args.lesson_timeout_min * 60))
        prev = key
    if not tasks:
        print("Nothing to run.")
        return 0

    print(f"Submitting {len(tasks)} task(s), order: {args.order} — test schemas in {names['catalog']}: "
          f"{names['schema']}, {names['reference_schema']}, {names['user_schema']}")
    waiter = w.jobs.submit(run_name=f"vvm smoke {course.slug} {info['build_id']}", tasks=tasks)
    run_id = waiter.run_id if hasattr(waiter, "run_id") else waiter.response.run_id
    state["run_id"] = run_id
    (course.dist_dir / SMOKE_STATE).write_text(json.dumps(state, indent=2) + "\n")
    run = w.jobs.get_run(run_id)
    print(f"Run {run_id}: {run.run_page_url}")
    while True:
        run = w.jobs.get_run(run_id)
        life = run.state.life_cycle_state.value if run.state and run.state.life_cycle_state else "?"
        if life in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            break
        done = sum(1 for t in run.tasks or [] if t.state and t.state.life_cycle_state
                   and t.state.life_cycle_state.value in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"))
        print(f"  … {life}, {done}/{len(tasks)} tasks done", flush=True)
        time.sleep(30)

    results, setup_minutes = [], None
    for t in sorted(run.tasks or [], key=lambda t: t.start_time or 0):
        result = t.state.result_state.value if t.state and t.state.result_state else "?"
        minutes = round((t.execution_duration or 0) / 60000, 1)
        status, detail = ("PASS" if result == "SUCCESS" else "FAIL"), ""
        try:
            output = w.jobs.get_run_output(t.run_id)
            if output.notebook_output and output.notebook_output.result:
                payload = json.loads(output.notebook_output.result)
                status = payload.get("status", status)
                failed = [c["name"] for c in payload.get("checks", []) if not c.get("ok")]
                detail = ("failed: " + ", ".join(failed)) if failed else ""
            elif output.error:
                detail = output.error.splitlines()[0][:120]
        except Exception as e:  # output unavailable (task skipped, etc.)
            detail = detail or f"no output ({type(e).__name__})"
        if t.task_key == "workspace_setup":
            setup_minutes = minutes
            label = "workspace_setup"
            status = "PASS" if result == "SUCCESS" else "FAIL"
        else:
            label = keys[t.task_key].label
        results.append((label, status, minutes, t.run_id, detail))

    ok = all(s == "PASS" for _, s, *_ in results)
    print(f"\n{'Task':<60} {'Status':<6} {'Min':>5}  Detail")
    for label, status, minutes, _, detail in results:
        print(f"{label[:60]:<60} {status:<6} {minutes:>5}  {detail}")
    print(f"\nSmoke {info['build_id']}: {'PASS' if ok else 'FAIL'} — run {run.run_page_url}")

    entry = [f"\n## {started.date().isoformat()} — vvm smoke {info['build_id']}\n",
             f"- result: {'PASS' if ok else 'FAIL'} ({sum(s == 'PASS' for _, s, *_ in results)}/{len(results)})",
             f"- profile: `{args.profile or 'DEFAULT'}`, run id {run_id}, order {args.order}"
             + (f", changed since {args.changed_since}" if args.changed_since else "")]
    if setup_minutes is not None:
        entry.append(f"- setup_minutes: {setup_minutes}")
    entry += ["", "| Task | Status | Min | Detail |", "|------|--------|-----|--------|"]
    entry += [f"| {label} | {status} | {minutes} | {detail} |" for label, status, minutes, _, detail in results]
    course.notes_path.parent.mkdir(parents=True, exist_ok=True)
    with course.notes_path.open("a") as f:
        if not course.notes_path.stat().st_size:
            f.write("# Notes\n")
        f.write("\n".join(entry) + "\n")
    print(f"Recorded in {course.rel(course.notes_path)}. Next: vvm cleanup --dry-run")
    return 0 if ok else 1


def cmd_cleanup(course: Course, args) -> int:
    state_path = course.dist_dir / SMOKE_STATE
    if not state_path.exists():
        raise VvmError(f"no {course.rel(state_path)} — nothing recorded to clean up (run vvm smoke first)")
    state = json.loads(state_path.read_text())
    w = workspace_client(args.profile or state.get("profile"))
    me = w.current_user.me().user_name
    catalog = state["catalog"]
    plan: list[tuple[str, str, object]] = []  # (kind, name, delete thunk)

    for schema in (state["user_schema"], state["reference_schema"], state["schema"]):
        full = f"{catalog}.{schema}"
        try:
            w.schemas.get(full)
        except Exception:
            continue
        for m in w.registered_models.list(catalog_name=catalog, schema_name=schema):
            for v in w.model_versions.list(m.full_name):
                plan.append(("model version", f"{m.full_name} v{v.version}",
                             lambda n=m.full_name, ver=v.version: w.model_versions.delete(n, ver)))
            plan.append(("registered model", m.full_name, lambda n=m.full_name: w.registered_models.delete(n)))
        for v in w.volumes.list(catalog_name=catalog, schema_name=schema):
            plan.append(("volume", v.full_name, lambda n=v.full_name: w.volumes.delete(n)))
        for t in w.tables.list(catalog_name=catalog, schema_name=schema):
            plan.append(("table", t.full_name, lambda n=t.full_name: w.tables.delete(n)))
        plan.append(("schema", full, lambda n=full: w.schemas.delete(n, force=True)))

    target = state["target"]
    for e in w.experiments.search_experiments(filter=f"name LIKE '{target}%'"):
        plan.append(("experiment", e.name, lambda i=e.experiment_id: w.experiments.delete_experiment(i)))
    for j in w.jobs.list():
        if j.creator_user_name == me and (j.created_time or 0) >= state["started_ms"]:
            name = j.settings.name if j.settings else str(j.job_id)
            plan.append(("job", f"{name} ({j.job_id})", lambda i=j.job_id: w.jobs.delete(i)))
    try:
        w.workspace.get_status(target)
        plan.append(("folder", target, lambda: w.workspace.delete(target, recursive=True)))
    except Exception:
        pass

    print(f"Created by the smoke test of {state['build_id']} (started {state['started_at']}):")
    for kind, name, _ in plan:
        print(f"  {kind:<17} {name}")
    if not plan:
        print("  nothing left")
        return 0
    print(f"The catalog {catalog} itself is never deleted.")
    if args.dry_run:
        print("\nDry run — nothing deleted.")
        return 0
    if not args.yes:
        print("\nRe-run with --yes to delete these.", file=sys.stderr)
        return 1
    failed = 0
    for kind, name, delete in plan:
        try:
            delete()
            print(f"  deleted {kind} {name}")
        except Exception as e:
            failed += 1
            print(f"  FAILED  {kind} {name}: {e}", file=sys.stderr)
    if not failed:
        state_path.unlink()
    return 1 if failed else 0


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vvm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-C", "--course-dir", type=Path, default=Path.cwd(), help="course repository (default: cwd)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("lint", help="check the course against the platform rules (spec §7.4)")
    sub.add_parser("build", help="lint, then build dist/<slug>-{labs,setup}.zip and BUILD_INFO.json")
    s = sub.add_parser("which", help="trace a build id back to its commit and test notes")
    s.add_argument("build_id")
    s = sub.add_parser("form", help="print the Course Vending Machine form values (or what changed)")
    s.add_argument("--full", action="store_true", help="full sheet even when vocareum/config.json exists")
    s = sub.add_parser("checklist", help="write SPECS/CHECKLIST-<build_id>.md for a Vocareum test")
    s.add_argument("--since", help="build id or commit to compare with (default: last tested build in NOTES.md)")
    s.add_argument("--force", action="store_true", help="overwrite an existing checklist")

    def ws(parser):
        parser.add_argument("--profile", help="Databricks CLI profile (~/.databrickscfg)")
        parser.add_argument("--target", help="workspace folder (default: /Users/<me>/<slug>-vvm)")

    s = sub.add_parser("install", help="import the rendered notebooks into a dev workspace")
    ws(s)
    s.add_argument("--email", help="user whose home folder to import into (default: you)")
    s = sub.add_parser("smoke", help="install, run setup then each lesson as a serverless job, record results")
    ws(s)
    s.add_argument("--catalog", required=True, help="existing catalog for the test schemas (never created)")
    s.add_argument("--prefix", help="test schema prefix (default: vvm_<slug>)")
    s.add_argument("--order", choices=["reverse", "random", "forward"], default="reverse",
                   help="lesson order (default: reverse, to prove cold start)")
    s.add_argument("--changed-since", help="only lessons changed since a build id, commit, or 'last'")
    s.add_argument("--skip-setup", action="store_true", help="don't run workspace_setup (already done)")
    s.add_argument("--lesson-timeout-min", type=int, default=60)
    s = sub.add_parser("cleanup", help="delete what the last smoke test created (lists it first)")
    s.add_argument("--profile")
    s.add_argument("--dry-run", action="store_true", help="list only")
    s.add_argument("--yes", action="store_true", help="delete without asking again")

    args = p.parse_args(argv)
    commands = {"lint": cmd_lint, "build": cmd_build, "which": cmd_which, "form": cmd_form,
                "checklist": cmd_checklist, "install": cmd_install, "smoke": cmd_smoke, "cleanup": cmd_cleanup}
    try:
        course = Course(find_course_root(args.course_dir))
        return commands[args.command](course, args)
    except VvmError as e:
        print(f"vvm: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
