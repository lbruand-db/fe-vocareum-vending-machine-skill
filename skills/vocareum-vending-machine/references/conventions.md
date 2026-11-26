# Course conventions

> **Source:** mmf-workshop at `de2c7c8` — `SPECS/RESTRUCTURE.md`, `labs/Source/en_us/notebooks/Includes/`, its lessons and learner README. Compiled 2026-11-26.

## 1. Layout and naming

```
labs/Source/en_us/notebooks/
├── AGENDA.py                          # landing notebook (Lab Content entry)
├── Version Info.py                    # build id, commit link, build time, dataset attributions
├── Includes/
│   ├── _common.py  _checks.py  [_user_assets.py]
│   ├── Classroom-Setup-x.y.py         # one per lesson that needs one
│   └── Print-Dataset-Copyrights.py
└── M0x - <Module>/x.y <Type> - <Title>.py
labs/Source/en_us/instructor/          # never packaged
labs/Source/en_us/voc/docs/README.md   # learner README (Vocareum side pane)
```

- **Lesson types:** *Lecture* (no compute, or light), *Demo* (instructor-led; can be the reference solution), *Lab* (the learner does it), *Appendix* (optional).
- **Numbers are permanent** once published, so links don't break. Gaps are fine (add 2.3 later).
- Every notebook is a Databricks source file: first line `# Databricks notebook source`, cells split by `# COMMAND ----------`, markdown as `# MAGIC %md`.

## 2. Notebook header

Right after the first line, pin the serverless environment (lint rule `env-header`, version from `course.toml`):

```python
# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "4"
# ///
```

## 3. Lesson skeleton

In this order (as in mmf-workshop's lessons):

1. **Title and overview** — what the learner will do, and what Databricks brings.
2. **Before you start: compute** — serverless; what to pick if asked.
3. **Learning objectives.**
4. **Classroom setup** — `%run ../Includes/Classroom-Setup-x.y`. Must come before any cell that reads or writes data.
5. **Lettered sections** — `A. …`, `B. …`; tasks for Labs.
6. **Short on time?** — wherever a step is slow (> ~2 min) or agent-driven: one cell that copies the expected result from `{reference}` in seconds (`copy_table`).
7. **Check your work** — `%run ../Includes/_checks`, then `finish("<x.y>", checks)`. Required in every Demo and Lab (lint rule `check-your-work`).
8. **Summary.**

## 4. Rules for lesson code

- **Cold start:** every lesson works when opened first, in any order. Its Classroom setup puts its inputs in place with `ensure_table(name, src)`.
- **Outputs only to `out`.** Shared data (`{source}`, `{reference}`) is read-only.
- **Never `CREATE CATALOG`** (lint `no-create-catalog`). `ensure_schema()` creates the learner's schema only.
- **No hard-coded** emails, catalogs, schemas or workspace URLs (lint `no-hardcoded-identity`) — use `source`, `reference`, `out`, `user_email`.
- **No downloads at lesson time** (lint `no-runtime-download`): `%pip install` only from `/Volumes/{catalog}/{schema}/assets/…` (staged by setup, pinned in `setup/VERSIONS.md`).
- **No GPU** (lint `no-gpu`).
- **Interactive widgets** are self-contained `displayHTML` (no CDN, no external fetch). Tested to render inside Databricks' sandboxed output iframe, light and dark mode.
- **Links** between notebooks use `$./…` relative paths and must resolve in the packaged zip (lint `agenda-links`).

## 5. The Includes contract

`Includes/_common.py` (run by every `Classroom-Setup-x.y`):

| Name | Meaning |
|------|---------|
| `source` | `{data.catalog}.{data.schema}` — shared, read-only data |
| `reference` | `{data.catalog}.{data.reference_schema}` — pre-computed results |
| `out` | the learner's own `catalog.schema`, resolved as in `platform.md` §2; printed with `[resolved_by]` |
| `user_email` | `current_user()` |
| `COURSE_BUILD` | `{{build_id}}`, filled by `vvm build`; printed as `Course build: …` |
| `ensure_schema()` | `CREATE SCHEMA IF NOT EXISTS {out}` — never a catalog |
| `copy_table(src, name)` | overwrite `{out}.{name}` from `src`; returns the row count |
| `ensure_table(name, src)` | keep the learner's own `{out}.{name}` if it has rows, else copy it from `src` |
| `ensure_user_assets()` | optional, from `_user_assets.py` (§7) |

Widgets: `catalog`, `schema`, `user_catalog`, `user_schema` — so pre-tests and setup reference runs can redirect everything.

`Includes/_checks.py`: `finish(lab, checks)` with `checks = [(name, ok, detail), …]` prints `[PASS]/[FAIL]` per item and the overall result, then exits the notebook with JSON — the same JSON `vvm smoke` reads:

```json
{"lab": "2.2", "status": "PASS", "checks": [{"name": "m5_train_data exists", "ok": true, "detail": "100 series"}]}
```

Keep the logic in plain functions that take `spark` / `dbutils` as arguments where practical, so `tests/` can unit-test them without a workspace (CI, spec §7.7).

## 6. Admin setup (`setup/`)

- `workspace_setup.py` runs the `[[setup.steps]]` from `course.toml` in order. **Every step is idempotent**: skipped when its `outputs` exist, unless the `force_reload` widget is true.
- Typical steps: create shared catalog/schema/volume → stage pinned assets in `/Volumes/{catalog}/{schema}/assets` → load data → reference runs (run a lesson with `user_catalog/user_schema` = `{reference}`) → `GRANT` read to `data.learner_group` → append a row to `{source}.course_build`.
- Exit JSON includes `build_id`.
- `VERSIONS.md` lists every pin: asset, pin, where it's set, where it's staged, and how to update it.
- `user_setup.py`: admin fallback that installs per-user assets for a list of emails (`force=True`).

## 7. Per-user assets (`Includes/_user_assets.py`)

For files that must sit in a learner's home folder (e.g. a Genie Code skill): declared in `[[user_assets]]`, staged by setup, installed by the learner's Classroom setup through the Workspace API with the learner's own credentials. Idempotent (version marker per asset), never fails the lesson (warn and point to `setup/user_setup`), reported in *Check your work* of the first lesson that needs it.

## 8. AGENDA, Version Info, learner README

- **AGENDA:** description, prerequisites, modules → lessons table with `$./` links and durations, requirements (serverless; what's pre-loaded).
- **Version Info:** `{{build_id}}`, `{{commit_url}}`, `{{built_on}}`, `{{dirty_note}}`; dataset attributions (`Print-Dataset-Copyrights`).
- **Learner README** (`voc/docs/README.md`): title and one-paragraph pitch; dataset and time (learner time vs lab session length); learning objectives; **How this lab works** (opens on AGENDA; where outputs go; shared data read-only; Classroom setup first; *Short on time?*; *Check your work*); one short block per module with steps and expected outputs; tips (serverless only, click **End Lab** when done).

## 9. Branding and reference material

- `branding = "neutral"`: no Databricks Academy logo, header, footer or name.
- A course used only for structure lives in `reference_dir` (git-ignored). Nothing from it is copied — no text, code, images or HTML exports. Reuse structure, naming and platform interfaces only.
