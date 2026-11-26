# SPEC — Vocareum Vending Machine course skill

| | |
|---|---|
| **Status** | Draft — 2026-11-23, revised 2026-11-26; all decisions (§12) taken |
| **Skill name** | `vocareum-vending-machine` |
| **What** | A Claude Code skill that takes a field engineer from "I have notebooks / a topic" to "a tested course running on Vocareum through the Course Vending Machine" — and back again for each new version |
| **Generalised from** | [`lbruand-db/mmf-workshop`](https://github.com/lbruand-db/mmf-workshop) at `de2c7c8` (2026-10-22): its build CLI, admin setup notebooks, lesson includes, Vocareum README, notes and test checklist |
| **Users** | Databricks field engineers (SA, DSA, SSA) building hands-on labs for customers or enablement in the *Field Driven Enablement Labs* Vocareum org |
| **Platform docs** | go/field-driven-enablement-labs, go/vocareum-lab-guidelines, go/vocareum-lab-development; help in #field-driven-labs-vocareum |

## 1. Goal and outcomes

Building the MMF workshop took about a week, most of it spent rediscovering how the Vocareum platform behaves: where learners may write, which hooks exist, what the setup job's timeout is, how to tell which build is deployed. None of that is MMF-specific. The skill packages it so the next course starts from a working skeleton and a known-good checklist.

With the skill, a user can:
1. **Scaffold** a course repository with the layout, includes and admin setup that work on Vocareum (§6).
2. **Author** lessons that follow the conventions: classroom setup, cold start, *Short on time?*, *Check your work* (§7.2).
3. **Lint** the course against the platform's rules before uploading (§7.4): no `CREATE CATALOG` in learner notebooks, no GPU, no runtime downloads, links that resolve, …
4. **Build** traceable archives (`<version>+g<commit>[.dirty]`) for the Vending Machine form (§7.3).
5. **Pre-test** on a dev workspace without Vocareum (`install`, smoke-run the lessons as jobs).
6. **Create the course** in the Vending Machine with the right form values, and version the generated `config.json` (§8).
7. **Test on Vocareum** with a checklist generated from the course's own lessons (§9), and record the results.
8. **Ship a new version**: rebuild, redeploy, re-test only what changed.

## 2. Background

### 2.1 The platform

- **Vocareum Cloud Labs — Databricks.** Vocareum provisions real Databricks workspaces (AWS only) and redirects learners into them. Workspaces are **shared** up to *Max Users per Workspace*; Vocareum opens another one when full. One metastore per workspace, so shared data is loaded **per workspace** by a setup hook, never by hand.
- **Learners are workspace users, not admins.** Each gets a per-user location (default: a user-owned schema in the `dbacademy` catalog; the platform publishes it in `<catalog>.ops.meta` with keys `catalog_name`, `schema_name`, `username`). Any catalog a learner creates is dropped at their cleanup — learner notebooks must never create catalogs.
- **The Course Vending Machine** is a Databricks App that creates a Vocareum course from a form and generates its `config.json` (*View config.json*). Its URL is recorded in the skill's `references/vending-machine-form.md` (originally noted in mmf-workshop `SPECS/NOTES.md`), so the skill doesn't depend on another repo. It offers:
  - **Lab Content**: a prepared archive (`.zip` of source notebooks) + entry notebook;
  - **Workspace setup**: an archive + entry notebook, run **once per workspace as a serverless job**, timeout 20 min by default, max 120;
  - **User Resources**: user catalog/schema mode, *Manage Schema*, auto-created personal cluster / SQL warehouse;
  - Templates (*Data Science*, *Genie Code*, …), org, dates, lab time, *Allow lab to be stopped*.
  - **No per-user hook and no lab-end hook** (unlike the manual `.cfg` route, which has `user_setup` and `lab_end.py`).
- **The manual route** (go/vocareum-lab-development): clone a template course, upload a `.cfg` + archives to `/voc/private/courseware/`, the learner README to `/voc/docs/README.md`, scripts to `/scripts/python/`. Never "save image". Documented by the skill, not generated (§8.3).
- **L&E guidelines:** minimum compute and data; shared read-only data in Unity Catalog; pre-create everything that isn't a learning objective; a learner `README.md`; shortcut slow tasks "like a cooking show"; **no GPUs**, no provisioned throughput serving, avoid third-party downloads and private-preview features that need enablement without an API; budget ≤ 3× the session length; automate setup and termination.

### 2.2 What mmf-workshop learned — and what generalises

| Problem met in mmf-workshop | Solution there | Generalised by the skill as |
|-----------------------------|----------------|------------------------------|
| Where does a learner write? Platform metadata keys were unverified | `Includes/_common` resolves `out` in order: widgets → `ops.meta` → Vocareum managed catalog → `{catalog}.{user}`; prints `[resolved_by]` | `_common` template, unchanged logic, course-specific names from `course.toml` |
| Learners can't create catalogs; a learner-created shared catalog would be dropped with them | `ensure_schema()` only; lint forbids `CREATE CATALOG` under `labs/` | Same helper + lint rule `no-create-catalog` |
| Lessons must work when entered cold, in any order | `Classroom-Setup-x.y` per lesson; `ensure_table(name, src)` copies reference results when the learner's own are missing | Template + generator per lesson |
| Long jobs (forecasts: 10–20 min) | Pre-computed reference results in `{catalog}.{schema}_reference`; *Short on time?* cells copy them in seconds | "Reference run" step in `workspace_setup`; *Short on time?* cell template |
| Learner feedback without grading | `Includes/_checks.finish()` prints PASS/FAIL and exits with JSON | Template; the same JSON drives the smoke test |
| No GPU on Vocareum (no EC2 quota, serverless GPU off, and forbidden) | Foundation-model results pre-computed on CPU in setup | Lint rule `no-gpu`; guidance: precompute or drop |
| Learner notebooks shouldn't download code from GitHub/PyPI | `workspace_setup` stages pinned wheels and assets in `/Volumes/{catalog}/{schema}/assets`; lessons `%pip install -r` from there; `setup/VERSIONS.md` | "Stage assets" step + `VERSIONS.md` template; lint rule `no-runtime-download` |
| Setup timeout: default 20 min too short | Timeout 120; every setup step skips when its output exists (`force_reload` widget) | Idempotent step pattern; form value derived from measured setup time |
| No per-user hook in the Vending Machine | Per-user install (the Genie Code skill) moved into each lesson's Classroom setup; `user_setup` kept as admin fallback | Optional "per-user asset" pattern: idempotent, version-marked, never fails the lesson |
| No lab-end hook: learner-created jobs/clusters leak | *Allow lab to be stopped* off; `mmf_lab_end.py` kept for the `.cfg` route; manual check after tests | Same; intake warning when learners create billable resources, pointing to the manual route doc (§8.3); leftovers listed by `vvm cleanup --dry-run` |
| Learners need read access to shared data | `GRANT … TO 'account users'` in setup | Grant step from `course.toml` |
| Which build is deployed? | `build_id` in `Version Info`, printed by every Classroom setup, a row in `{source}.course_build` per setup run, `dist/BUILD_INFO.json`; warnings if dirty or unpushed | Built into the build command (§7.3) |
| *Genie Code* template adds the *Consumer* entitlement, which may block notebooks/jobs | Use *Data Science* | Default in the form sheet, with the reason |
| Settings typed into a web form are lost | Save *View config.json* as `vocareum/config.json` | Step in §8, and `vvm form` diffs against it |
| Copyrighted reference course used for structure | `.sources/` git-ignored; build fails if tracked | `reference_dir` in `course.toml`, same check |
| "Not Academy" | Neutral branding, no Academy marks | `branding = "neutral"` default |
| Serverless environment | `# /// script … environment_version = "4"` header on each notebook | Header template; lint rule `env-header` |

## 3. Scope

**In:** scaffolding, conventions, templates, build/lint/install CLI, CI workflows and release artifacts (§7.7), form values and `config.json` versioning, test checklist generation, dev-workspace smoke tests, redeploy workflow, a reference doc for the manual `.cfg` route (§8.3).

**Out:** writing the course content itself (the skill scaffolds and checks; the author or another session writes lessons); grading/autograde (supported by the `.cfg` route, not by the Vending Machine form — decided: out); LTI/Docebo; course translation; generating `.cfg` files or `lab_end` scripts for the manual route (§8.3); creating Vocareum orgs or accounts; GPU courses.

## 4. Triggers and user journeys

The skill description should trigger on: "create a Vocareum course", "vending machine course", "package my notebooks for Vocareum", "Course Vending Machine", "build the course zips", "what do I fill in the vending machine form", "test checklist for the new course version", "which build is deployed on Vocareum".

It must **not** trigger on FEVM requests ("deploy a demo workspace") — the FE Vending Machine (FEVM) provisions Databricks workspaces and is a different product. The skill may *use* FEVM (via the `fevm` skill) to get a dev workspace for pre-tests (§7.5), and should say so when the names could be confused.

| Journey | Starts from | Phases (§5) |
|---------|-------------|-------------|
| A. New course from scratch | A topic, a dataset | 0 → 8 |
| B. Convert existing notebooks / a demo repo | A folder of notebooks | 0, 1 (adopt mode), 2 → 8 |
| C. New version of a deployed course | A repo already scaffolded | 4, 6 (if settings change), 7, 8 |
| D. "Which build is this?" / triage a learner report | A build id from a screenshot | §7.3 lookup |

## 5. Workflow

Each phase ends with a short report and, where something outward-facing or hard to undo happens, an explicit confirmation from the user.

**0. Intake.** Ask only what can't be inferred (one `AskUserQuestion` round, ≤ 4 questions): course name; audience and length (drives *Lab Time*, ≈ 2× learner time); shared data (source, size, licence/attribution); does a lesson need a long-running step (→ reference run); does any lesson need GPU, Apps, Genie Code, model serving, classic clusters (→ flag against guidelines/known gaps); do learners create jobs, clusters, endpoints or other billable resources (→ warn: no lab-end cleanup on the Vending Machine, §8.3); per-user assets (e.g. a Genie Code skill). Write the answers to `course.toml` (§7.1).

**1. Scaffold.** Generate the repo layout (§6) from templates, filling names from `course.toml`. *Adopt mode* (journey B): move existing notebooks into `M0x - …/x.y <Type> - <Title>.py`, add the environment header, the Classroom setup cell and a *Check your work* stub to each; never delete the originals without confirmation.

**2. Author.** Conventions for every lesson (§7.2). The skill can generate the per-lesson `Classroom-Setup-x.y` from the lesson's declared inputs, the AGENDA table from the folder tree, and the learner README skeleton. Content is the author's.

**3. Admin setup.** Generate `setup/workspace_setup.py` from steps declared in `course.toml`: create shared catalog/schema/volume → stage pinned assets → load data → reference runs → grants → record build. Every step idempotent; `force_reload` widget; exit JSON with `build_id`.

**4. Build and lint.** `vvm lint` then `vvm build` (§7.3–7.4). Refuse to recommend uploading a dirty or unpushed build; say why. When CI is set up (§7.7), the zips to upload are the ones attached to the GitHub Release.

**5. Pre-test on a dev workspace.** `vvm install --profile <p>` imports rendered notebooks; `vvm smoke --profile <p>` runs `workspace_setup` into a test catalog/schema, then each lesson as a serverless job task (in a fresh order, to prove cold start), and collects the `_checks` JSON. Report PASS/FAIL per lesson with run URLs, and append a dated entry to `SPECS/NOTES.md` with the build id and `setup_minutes: <n>` (the measured `workspace_setup` duration, read by `vvm form`, §8.1). Then `vvm cleanup` removes what the test created (tables, volumes, registered models — versions first —, experiments, jobs, folders), after listing it.

**6. Create the course in the Vending Machine.** Produce the form sheet (§8.1) with values and reasons. The Vending Machine has no API (as of 2026-11-23), so the user fills the form from the sheet and **clicks Create**. Then save *View config.json* as `vocareum/config.json` and commit it.

**7. Test on Vocareum.** Generate `SPECS/CHECKLIST-<build_id>.md` (§9) from the course: admin setup, student entry, then one block per lesson from its declared outputs and checks, then cold-start and cleanup. The user runs it as a student; the skill records the results and timings in `SPECS/NOTES.md`.

**8. Iterate.** Fix, bump the version, tag the release (§7.7) or rebuild locally, redeploy (upload new zips; settings unchanged unless `config.json` diff says otherwise), re-test only the lessons whose files changed since the last tested build (`git diff <last_build_commit>..HEAD -- labs setup`).

## 6. Generated course layout

```
<course>/
├── course.toml                         # single source of course settings (§7.1)
├── pyproject.toml                      # version only — the `vvm` CLI ships with the skill (§7.3)
├── README.md                           # for authors: build, test, deploy
├── .github/workflows/                  # check.yml, release.yml (§7.7)
├── tests/test_includes.py              # unit tests for the Includes helpers (§7.7)
├── labs/Source/en_us/
│   ├── notebooks/                      # → <slug>-labs.zip, entry AGENDA
│   │   ├── AGENDA.py                   # description, prerequisites, modules → lessons table ($./ links), requirements
│   │   ├── Version Info.py             # {{build_id}}, {{commit_url}}, {{built_on}}, {{dirty_note}}; dataset attributions
│   │   ├── Includes/
│   │   │   ├── _common.py              # source / reference / out resolution, ensure_schema, copy_table, ensure_table, COURSE_BUILD
│   │   │   ├── _checks.py              # finish(lab, checks) → PASS/FAIL + JSON exit
│   │   │   ├── _user_assets.py         # optional: idempotent per-user install (pattern of mmf's _skill)
│   │   │   ├── Classroom-Setup-x.y.py  # one per lesson
│   │   │   └── Print-Dataset-Copyrights.py
│   │   └── M0x - <Module>/x.y <Lecture|Demo|Lab|Appendix> - <Title>.py
│   ├── instructor/                     # never packaged
│   └── voc/docs/README.md              # learner instructions (Vocareum side pane)
├── setup/                              # → <slug>-setup.zip (with the notebooks), entry setup/workspace_setup
│   ├── workspace_setup.py
│   ├── user_setup.py                   # admin fallback for per-user assets
│   ├── 0x_<step>.py                    # data load, reference runs
│   └── VERSIONS.md                     # every pin, where it is set, where it is staged
├── vocareum/
│   ├── README.md                       # form values, what runs when, test, known gaps
│   └── config.json                     # saved from the Vending Machine after creation
├── SPECS/NOTES.md                      # dated test log: build id, workspace, results, timings
└── dist/                               # build output, git-ignored
```

Lesson numbers are fixed once published so links don't break; gaps are allowed.

## 7. Components

### 7.1 `course.toml`

One file replaces the constants hard-coded in mmf-workshop's `cli.py` and setup widgets.

```toml
[course]
name = "Many-Model Forecasting with Genie Code"
slug = "mmf-workshop"                  # archive names, top-level folder
repo_url = "https://github.com/lbruand-db/mmf-workshop"
locale = "en_us"
entry = "AGENDA"
branding = "neutral"                   # never Academy marks
reference_dir = ".sources"             # git-ignored, never packaged
environment_version = "4"

[data]
catalog = "mmf"                        # shared, created by workspace_setup
schema = "m5"                          # read-only for learners
reference_schema = "m5_reference"      # pre-computed results
learner_schema = "mmf"                 # schema inside the learner's catalog when not given by ops.meta
learner_group = "account users"

[[setup.steps]]                        # run in order by workspace_setup; each skipped when `outputs` exist
name = "data_load"
notebook = "setup/00_data_load"
outputs = ["daily_train_100", "m5_static_features"]
timeout_min = 60

[[setup.steps]]
name = "reference_run"
notebook = "labs/Source/en_us/notebooks/M03 - Running Forecasts at Scale/3.2 Demo - MMF with mmf_sa"
target = "reference"                   # writes to {catalog}.{reference_schema}
outputs = ["m5_evaluation_output", "m5_scoring_output"]

[[assets]]                             # staged in /Volumes/{catalog}/{schema}/assets by workspace_setup
name = "mmf_sa"
kind = "wheel"                         # wheel | tarball | file | skill-bundle
source = "https://github.com/databricks-industry-solutions/many-model-forecasting"
ref = "322ef91b7002067f9f7c7c37e5ca3e9e8abb28b4"

[[user_assets]]                        # optional; installed per learner by Classroom setup (§7.5)
name = "genie_code_skill"
staged = "skills/mmf"                  # folder in /Volumes/{catalog}/{schema}/assets/, staged by workspace_setup
dest = ".assistant/skills/mmf"         # relative to /Users/{me}/
templated = ["SKILL.md"]               # {{workspace_url}} / {{user_email}} filled at install
keep_user_edits = true

[vocareum]
org = "Field Driven Enablement Labs"
template = "Data Science"
max_users_per_workspace = 50
lab_time_hours = 4
setup_timeout_min = 120                # checked by `vvm form` against 2× the last measured setup time, max 120 (§8.1)
allow_lab_stop = false

[tooling]
skill_ref = "<commit>"                 # skill version CI checks out to run vvm (§7.7); set by the scaffold
```

Names used in this spec: `{source}` = `{data.catalog}.{data.schema}` (shared, read-only data, and the `course_build` table); `{reference}` = `{data.catalog}.{data.reference_schema}`; `out` = the learner's own catalog.schema, resolved at runtime by `_common` (§2.2).

### 7.2 Lesson conventions

Skeleton (from mmf-workshop `SPECS/RESTRUCTURE.md`): title and overview → *Before you start: compute* → learning objectives → *Classroom setup* (`%run ../Includes/Classroom-Setup-x.y`) → lettered sections → *Short on time?* (where a step is slow or agent-driven) → *Check your work* (`%run ../Includes/_checks`, `finish(...)`) → summary.

Rules: every lesson can be entered cold; outputs only to `out`; shared data read-only; no hard-coded emails, catalogs or workspace URLs; no `%pip install` from the internet (staged requirements only); interactive widgets self-contained (`displayHTML`, no CDN). Lesson types: Lecture (no compute or light), Demo (instructor-led, can be the reference solution), Lab (learner does it), Appendix (optional).

### 7.3 Build — `vvm build`

Generalises `mmf_workshop/cli.py`:
- Fail if `reference_dir` is tracked by git.
- Validate that every packaged `.py` starts with `# Databricks notebook source`; skip and warn otherwise.
- Render `{{…}}` placeholders: `course_name`, `version_number`, `build_id`, `commit`, `commit_url`, `built_on`, `dirty_note`.
- `build_id = <pyproject version>+g<short commit>[.dirty]`, dirty from `git status --porcelain -- setup labs pyproject.toml course.toml`.
- Write `dist/<slug>-labs.zip` (paths relative to `notebooks/`, so `%run ../Includes/…` and `$./` links resolve) and `dist/<slug>-setup.zip` (`setup/` + notebooks, paths relative to the repo root, so setup can `dbutils.notebook.run` lessons as reference runs). `instructor/` is never packaged.
- Write `dist/BUILD_INFO.json`; warn if dirty or the commit isn't on a remote branch.
- `vvm which <build_id>` (journey D): resolve the commit, show `git log -1`, and the NOTES entry for that build.

Other commands: `vvm smoke --changed-since <ref>` restricts the run to lessons whose files changed (§5 phase 8); `vvm install --profile <p> [--email <e>]` (render to a temp dir, import with the SDK's `workspace.import_(format=SOURCE)`), `vvm smoke`, `vvm cleanup [--dry-run]`, `vvm form` (§8.1), `vvm checklist` (§9).

**Packaging (decided):** the CLI ships inside the skill as a single-file [uv script](https://docs.astral.sh/uv/guides/scripts/) — `scripts/vvm.py` with a PEP 723 header (`requires-python = ">=3.11"` for `tomllib`, pinned `dependencies`, `[tool.uv] exclude-newer` for reproducible resolution) — always run as `uv run <skill>/scripts/vvm.py <command>`. uv is the only prerequisite: it fetches Python and the dependencies on first run, so a course repo doesn't depend on a published package and the course `pyproject.toml` only carries the version. Dependencies stay few: `databricks-sdk` for the workspace commands (`install`, `smoke`, `cleanup`; auth from `~/.databrickscfg` profiles, as the CLI does); everything else (zip, git, lint) uses the standard library.

### 7.4 Lint — `vvm lint`

| Rule | Checks | Why |
|------|--------|-----|
| `notebook-header` | First line `# Databricks notebook source` | Otherwise not imported as a notebook |
| `env-header` | `# /// script` block with `environment_version` = `course.toml` | Serverless environment pinned |
| `classroom-setup` | Every lesson `%run`s its `Classroom-Setup-x.y`, and that file exists | Cold start |
| `check-your-work` | Every Demo/Lab calls `finish(` | Feedback + smoke test |
| `no-create-catalog` | No `CREATE CATALOG` under `labs/` | Learner-created catalogs are dropped at their cleanup |
| `no-gpu` | No GPU node types, `hardware_accelerator`, `GPU_` in packaged notebooks | Guidelines; no quota |
| `no-runtime-download` | Under `labs/`, every `%pip install` / `pip install` installs only from `/Volumes/…` (`-r /Volumes/…/requirements.txt` or a wheel path there); flagged: bare package names, `git+`, `http(s)://`, `--index-url` / `--extra-index-url`. Also flagged: `urlopen`, `requests.get`, `curl`, `wget` to non-workspace hosts | Guidelines; reproducibility |
| `no-hardcoded-identity` | No emails, `dbc-…` / `adb-…` hosts, tokens | Shared workspaces; secrets |
| `agenda-links` | Every `$./…` link in AGENDA and lessons resolves to a packaged notebook | Broken links are the first thing students hit |
| `pins` | Every asset in `course.toml` has a full commit/version, and appears in `VERSIONS.md` | Traceability |
| `placeholders` | `{{…}}` used only from the known set | Render completeness |
| `branding` | No "Databricks Academy" strings/logos when `branding = "neutral"` | Course rule |
| `reference-material` | Nothing under `reference_dir` packaged or tracked | Copyright |

Errors block `build`; warnings are printed. Each rule can be waived per file with a comment `# vvm: allow <rule> — <reason>`.

### 7.5 Per-user assets — `Includes/_user_assets.py`

The Vending Machine has no per-user hook, so anything that must sit in a learner's home folder is installed by the learner's own Classroom setup. Generalised from mmf-workshop's `_skill.py` (Genie Code skill installer):

- **Declared** in `course.toml`, one `[[user_assets]]` entry each: `name`, `staged` (a folder in `/Volumes/{catalog}/{schema}/assets/`, staged by `workspace_setup`), `dest` (relative to `/Users/{me}/`, e.g. `.assistant/skills/`), `templated` (files whose `{{workspace_url}}` / `{{user_email}}` are filled in at install), `keep_user_edits` (don't overwrite a file the learner wrote themselves).
- **Installed** through the Workspace API with the learner's notebook credentials (`ensure_user_assets()` in `_common`), idempotent: a version marker per asset (the staged `VERSION`) makes re-runs a no-op until the staged version changes.
- **Never fails the lesson:** on error it prints a warning and points to `setup/user_setup`, which installs the same assets as admin for a list of emails (`force=True`).
- **Checked:** the lesson that first needs the asset reports it in *Check your work*; the checklist (§9) has an item per asset.
- Genie Code skills are the first case (paths `/Users/{me}/.assistant/skills/` and `/Users/{me}/.assistant_instructions.md`; the leading dots matter). Other cases: starter files or sample configs a lesson expects in the learner's home folder.

### 7.6 Pre-test workspace

Default: a dev workspace the user already has a CLI profile for (mmf-workshop used e2-demo-field-eng). If none, offer to get one through the `fevm` skill — with that skill's own confirmation rules. Pre-tests write to a test catalog/schema passed through widgets (`user_catalog`, `user_schema`, `catalog`, `schema`), never to the course's real names on a shared workspace.

### 7.7 CI/CD

New, not generalised: mmf-workshop has no CI (at `de2c7c8`: no `.github/`, no tests). Deployment stays manual — the Vending Machine has no API (§12 decision 3) — so CI's job is to make sure that what the user uploads is lint-clean, built from a clean pushed commit, and recorded as a release.

| Stage | Trigger | Runs | Credentials |
|-------|---------|------|-------------|
| **check** | every push and PR | `vvm lint`, `vvm build`, unit tests (`tests/`); upload `dist/` as a workflow artifact | none |
| **release** | tag `v<version>` | fail if the tag ≠ `pyproject.toml` version; warn if `SPECS/NOTES.md` has no passing smoke entry for this commit; `vvm build` (clean checkout, so no `.dirty`); `vvm checklist`; `vvm form` diff against `vocareum/config.json`; GitHub Release with `<slug>-labs.zip`, `<slug>-setup.zip`, `BUILD_INFO.json`, `CHECKLIST-<build_id>.md`, the form diff in the notes | `GITHUB_TOKEN` only |
| **deploy** | manual | the user uploads the release's zips in the Vending Machine, saves `config.json`, runs the checklist (§5 phases 6–7) | — |

- **Getting `vvm` in CI.** The CLI lives in the skill repo (decision 2), so workflows check out the skill at the commit pinned in `course.toml` (`[tooling] skill_ref`, written by the scaffold) and run `uv run <skill>/scripts/vvm.py …`. uv comes from `astral-sh/setup-uv`; every action is pinned to a commit SHA.
- **Unit tests** (`tests/`, run with `uv run --with pytest pytest`): `_checks.finish()` output and exit JSON; `_common`'s `out` resolution order with fake widgets / `ops.meta` rows. To make this possible, the templates keep their logic in plain functions that receive `spark` / `dbutils` as arguments; the notebook cells only wire them up.
- **Smoke stays local** (decision 9): CI has no Databricks credentials. The author runs `vvm smoke` (optionally `--changed-since <last tested build>`) with their own CLI profile before tagging; it writes the result to `SPECS/NOTES.md`, which is committed and which the release workflow checks.
- **Generated by the scaffold** (§6): `.github/workflows/{check,release}.yml` and `tests/test_includes.py`.
- **The skill repo itself** has its own `check` workflow running §11 tests 3–4 (lint fixtures, build cases) on every push.

## 8. Creating the course

### 8.1 Form sheet — `vvm form`

Prints the Vending Machine fields with values from `course.toml` and the reason for each non-default value:

| Section | Field | Value (default) | Reason |
|---------|-------|-----------------|--------|
| Basic | Course Name | `<name> – <purpose>` | Unique per Vocareum account |
| | Max Users per Workspace | 50 | Shared data loaded once per workspace; learners isolated by schema |
| | Lab Time | ≈ 2× learner time | Room to finish background jobs |
| | Allow lab to be stopped | Off | No lab-end hook to clean up |
| | Vocareum Org | Field Driven Enablement Labs | Can't be moved later |
| | Template | Data Science | *Genie Code* template adds *Consumer* entitlement |
| Lab Content | Mode / File / Entry | Prepared archive / `dist/<slug>-labs.zip` / `AGENDA` | |
| Workspace setup | Enabled / Source / Entry / Timeout | On / `dist/<slug>-setup.zip` / `setup/workspace_setup` / `vocareum.setup_timeout_min` | Default 20 min too short for data + reference runs. `vvm form` warns if the value is below 2× the last measured setup time (`setup_minutes` in the latest `SPECS/NOTES.md` entry, written by `vvm smoke`), or above the 120 max |
| User Resources | Catalog & Schema / Manage Schema / personal cluster | user-owned schema in `dbacademy` / On / Off | Lessons resolve `out` from `ops.meta`; serverless |
| Data Sideload | — | Empty | `workspace_setup` loads data |

If `vocareum/config.json` exists, `vvm form` diffs the would-be settings against it and lists only the changes (journey C).

### 8.2 Confirmation

Creating a course is outward-facing (it provisions workspaces and costs money). The skill never clicks *Create Course* or uploads on its own; it prepares, the user confirms and submits.

### 8.3 Manual `.cfg` route — reference only

Decided (§12 decision 7): the skill **documents** the manual route but generates nothing for it — no `.cfg`, no `lab_end` reaper. The only implementation (mmf-workshop, 2026-10-16) has no recorded test on Vocareum (its `NOTES.md`: "Not tested on a workspace yet"), and the skill doesn't ship untested code.

`references/manual-cfg-route.md` covers: what the route is (clone a template course by copy; Course → Assignment → Part); the `.cfg` keys (`content`, `workspace_setup`, `user_setup`, `autograde`, `admin_cluster_config`, `cluster_config` / `warehouse_config`) and who runs them with which parameters; the hook scripts (`workspace_init`, `user_setup`, `lab_setup`, `lab_end`); upload paths (`.cfg` + archives to `/voc/private/courseware/`, README to `/voc/docs/README.md`, scripts to `/scripts/python/`); Part settings (End Lab Behavior *Terminate*, otherwise `lab_end` doesn't run); never save an image; and what a `lab_end` reaper must do (cancel runs, delete the learner's jobs, clusters, experiments). Dated, sourced from go/vocareum-lab-development and mmf-workshop `SPECS/VOCAREUM.md`, with mmf-workshop's untested `.cfg` and `mmf_lab_end.py` linked as examples.

What carries over unchanged: the archives from `vvm build`, `setup/workspace_setup`, and `setup/user_setup` (generated anyway as the per-user admin fallback, §7.5).

**When the skill points to it:** at intake (§5 phase 0), if learners create jobs, clusters or other billable resources, the skill warns that the Vending Machine has no lab-end hook to clean them up, recommends keeping *Allow lab to be stopped* off and steering learners to serverless, and mentions the manual route as the only way to get a `lab_end` hook.

**Revisit (→ generate `.cfg` + reaper)** when a real course needs `lab_end` and can be tested on a manually cloned course, or when the Vending Machine owners decline to add a lab-end hook (§13).

## 9. Test checklist — `vvm checklist`

Generated per build into `SPECS/CHECKLIST-<build_id>.md`, in the order a run goes (pattern of mmf-workshop's `CHECKLIST.md`):

0. **Before you start** — course created from this build's zips (`dist/BUILD_INFO.json` shown), setup timeout set.
1. **Workspace setup** — job succeeds; re-run skips completed steps; every `outputs` table and staged asset exists; `SELECT * FROM {source}.course_build` shows this build.
2. **Student entry** — lab opens on `AGENDA`; every link works; `Version Info` shows this build and its commit link resolves.
3. **Per lesson** (one block each, from the lesson file): Classroom setup prints `Course build: <id>` and an output location tagged `[lab platform metadata]` (not `[workshop default]`); per-user assets installed; the lesson's declared outputs; *Short on time?* works; *Check your work* PASS; timing to record for slow steps. Lessons changed since the last tested build are marked **new/changed**.
4. **Cold start** — open the later lessons first in a new session.
5. **After the test** — leftovers (jobs, clusters) listed for cleanup; results and timings written to `SPECS/NOTES.md` with the build id.

## 10. Skill files

```
fe-vocareum-vending-machine-skill/
├── SPECS/SPEC.md                       # this file
├── skills/vocareum-vending-machine/
│   ├── SKILL.md                        # triggers, the 9 phases, guardrails, when to read which reference
│   ├── references/
│   │   ├── platform.md                 # §2.1 facts, hooks, limits — dated, with sources
│   │   ├── vending-machine-form.md     # app URL, §8.1 fields, with screenshots if allowed — dated
│   │   ├── conventions.md              # §7.2 lesson skeleton and rules
│   │   ├── known-gaps.md               # no user / lab-end hook, Consumer entitlement, ops.meta keys, …
│   │   └── manual-cfg-route.md         # §8.3 — reference only, nothing generated
│   ├── templates/                      # files of §6 with {{course.*}} placeholders
│   └── scripts/vvm.py                  # uv script: build, lint, install, smoke, cleanup, form, checklist, which
├── evals/                              # §11
├── .github/workflows/check.yml         # §11 tests 3–4 on every push (§7.7)
└── README.md
```

**Distribution (decided):** a standalone repo for now — users clone it and link `skills/vocareum-vending-machine/` into `~/.claude/skills/` (or a project's `.claude/skills/`). The layout already matches a plugin's `skills/` folder, so moving to the FE Vibe marketplace later means adding a plugin manifest, not restructuring.

`SKILL.md` stays short (progressive disclosure): the phases and guardrails inline, the rest loaded from `references/` when the phase needs it.

**Guardrails stated in `SKILL.md`:**
- Never create the course, upload archives or delete workspace objects without explicit confirmation in the conversation.
- Never put learner outputs outside `out`, never create catalogs in learner notebooks, never add GPU paths.
- Never copy copyrighted course material (e.g. Academy sources used for structure) into the repo; link and cite only.
- No secrets, tokens or customer names in generated files.
- Don't publish timings or results that weren't measured; mark them "to be confirmed".
- Commit on the user's chosen branch policy (mmf-workshop works on `main`).

## 11. Test plan for the skill

1. **Reproduce mmf-workshop:** run phases 0–4 in adopt mode on a copy of mmf-workshop at `de2c7c8`; the generated includes, setup and build must be functionally equivalent (same archive file lists, same placeholders filled, lint clean). Diff and explain every difference.
2. **Toy course end to end:** "Hello Vocareum" — one shared table (`samples.nyctaxi.trips` copied), one Lecture, one Lab with a reference run and *Short on time?*. Phases 0–8 on a dev workspace and a real Vending Machine course; record time from intake to a passing checklist.
3. **Lint fixtures:** one failing and one passing notebook per rule in §7.4.
4. **Build:** clean, dirty and unpushed cases produce the right `build_id` and warnings; `vvm which` resolves a build id.
5. **Smoke:** lessons run in reverse order on a fresh test schema all PASS; `cleanup --dry-run` lists exactly what was created.
6. **Trigger evals:** prompts that should trigger (§4) and near-misses that should not ("deploy an FEVM workspace", "create a Databricks Academy course on dbacademy").

## 12. Decisions

| # | Topic | Decision (2026-11-23) |
|---|-------|-----------------------|
| 1 | Skill name | **`vocareum-vending-machine`**, matching the repo. Because "Vending Machine" also names FEVM, `SKILL.md` and the trigger evals must keep the two apart (§4, §11 test 6) |
| 2 | CLI distribution | **Inside the skill**: `scripts/vvm.py` as a uv script (PEP 723 header, pinned deps), run with `uv run`; uv is the only prerequisite (revised 2026-11-26, was "standard library only") |
| 3 | Vending Machine form | **No API to date** — the skill prints the form sheet and the user fills it. Asked in #field-driven-labs-vocareum; revisit if an API appears. Browser automation not planned |
| 4 | Distribution | **Standalone repo** now; FE Vibe marketplace plugin later (layout already compatible) |
| 5 | Per-user assets | **Generalised** into `_user_assets.py` (§7.5) |
| 6 | Grading | **Out** |
| 7 | Primary target | **Vending Machine only; manual `.cfg` route as a reference doc** (2026-11-26) — `references/manual-cfg-route.md`, no `.cfg` or reaper generated; the skill points to it when learners create billable resources (§8.3). Rejected: dropping it entirely (loses the only answer to lab-end cleanup); generating `.cfg` + reaper (no recorded test on Vocareum); supporting both routes fully (double the build and test work for no current user) |
| 8 | CI platform | **GitHub Actions** (2026-11-26) — workflow templates; the stages are plain `vvm` commands, so another CI can call them the same way |
| 9 | Smoke in CI | **No** (2026-11-26) — a service principal on the FE dev workspaces isn't considered feasible, so CI never holds Databricks credentials. `vvm smoke` runs from the author's machine; its `SPECS/NOTES.md` entry is what the release workflow checks |
| 10 | Release record | **GitHub Releases** (2026-11-26) — one release per version holds the exact zips uploaded to Vocareum, with `BUILD_INFO.json` and the checklist |

## 13. Risks and open questions

| Risk / question | Mitigation |
|-----------------|------------|
| The Vending Machine form or defaults change | `references/vending-machine-form.md` dated; `vvm form` diffs against the saved `config.json`; re-check at each course creation |
| `ops.meta` keys, `account users` coverage, Genie Code availability unverified on every template | Checklist item 3 reports `[resolved_by]`; known-gaps file updated from each test |
| Setup job can't reach GitHub/PyPI from serverless | Stage once; document the fallback (upload assets to the volume from the author's machine) |
| No lab-end hook → learner resources leak and cost | *Allow lab to be stopped* off; learner README steers to serverless; checklist cleanup step; ask the app owners for a lab-end hook |
| Over-generalising from one course | Test 2 with a toy course of a different shape before v1 |
| Skill confused with FEVM | Trigger evals (test 6); explicit note in `SKILL.md` |
| A release tagged without a smoke run (smoke is local only) | Release workflow warns when `SPECS/NOTES.md` has no passing smoke entry for the tagged commit; the Vocareum checklist (§9) is still required |

## 14. References

- mmf-workshop (`de2c7c8`): `src/mmf_workshop/cli.py`, `setup/workspace_setup.py`, `setup/user_setup.py`, `setup/VERSIONS.md`, `labs/Source/en_us/notebooks/Includes/{_common,_checks,_skill}.py`, `Version Info.py`, `AGENDA.py`, `labs/Source/en_us/voc/docs/README.md`, `vocareum/README.md`, `vocareum/courseware/mmf-workshop.cfg`, `vocareum/scripts/python/mmf_lab_end.py`, `SPECS/VOCAREUM.md`, `SPECS/RESTRUCTURE.md`, `SPECS/NOTES.md`, `SPECS/CHECKLIST.md`
- L&E: go/field-driven-enablement-labs, go/vocareum-lab-guidelines, go/vocareum-lab-development, go/lpt-general-request; #field-driven-labs-vocareum
- Claude Code skills and plugins: https://docs.claude.com/en/docs/claude-code/skills
- Databricks: serverless notebook environments, Unity Catalog volumes and grants, Databricks SDK for Python (`WorkspaceClient`: workspace import, jobs, UC objects)
- uv: running scripts with inline metadata, https://docs.astral.sh/uv/guides/scripts/
