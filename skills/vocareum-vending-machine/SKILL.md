---
name: vocareum-vending-machine
description: Build, package, test and ship a hands-on Databricks course on Vocareum through the Course Vending Machine (the Databricks App that creates Vocareum courses). Use when the user wants to create a Vocareum course or lab, package notebooks for Vocareum, build the course zips, fill in the Course Vending Machine form, test or redeploy a Vocareum course version, or find which build is deployed on Vocareum. Not for FEVM (FE Vending Machine) requests such as deploying a demo workspace — that is the fevm skill.
---

# Vocareum Vending Machine courses

Takes a field engineer from "I have notebooks / a topic" to "a tested course running on Vocareum through the Course Vending Machine", and back again for each new version. Generalised from a working course (mmf-workshop); the platform facts it relies on are in `references/`.

**Not FEVM.** The *Course Vending Machine* creates Vocareum courses. The *FE Vending Machine* (FEVM, `fevm` skill) provisions Databricks workspaces. If the user's words could mean either, say which one you're doing. This skill may use FEVM only to get a dev workspace for pre-tests (phase 5).

## Tools

- `vvm` — the course CLI, a uv script in this skill: `uv run <this skill's base directory>/scripts/vvm.py <command>`, run from the course repo root. uv is the only prerequisite. Commands: `lint`, `build`, `which`, `install`, `smoke`, `cleanup`, `form`, `checklist`.
- `templates/` — the course layout, with `{{course.*}}` placeholders filled from `course.toml`.
- `course.toml` in the course repo is the single source of course settings. Read it first in every phase after intake.

## Phases

Each phase ends with a short report. Ask for explicit confirmation before anything outward-facing or hard to undo (see Guardrails).

| # | Phase | Do | Read |
|---|-------|----|------|
| 0 | **Intake** | One `AskUserQuestion` round, ≤ 4 questions, only what can't be inferred: course name; audience and learner time (→ Lab Time ≈ 2×); shared data (source, size, licence); long-running steps (→ reference runs); GPU / Apps / Genie Code / model serving / classic clusters (→ flag); **do learners create jobs, clusters, endpoints or other billable resources** (→ warn: no lab-end cleanup, see known gaps); per-user assets. Write `course.toml`. | `platform.md`, `known-gaps.md` |
| 1 | **Scaffold** | Generate the layout from `templates/`. *Adopt mode* (existing notebooks): move them to `M0x - <Module>/x.y <Type> - <Title>.py`, add the environment header, Classroom setup cell and a *Check your work* stub. Never delete originals without confirmation. | `conventions.md` |
| 2 | **Author** | Generate per-lesson `Classroom-Setup-x.y`, the AGENDA table and the learner README skeleton. The content is the author's. | `conventions.md` |
| 3 | **Admin setup** | Generate `setup/workspace_setup.py` from `[[setup.steps]]`: shared catalog/schema/volume → stage pinned assets → load data → reference runs → grants → record build. Every step idempotent, `force_reload` widget, exit JSON with `build_id`. | `platform.md` |
| 4 | **Lint and build** | `vvm lint`, then `vvm build`. Don't recommend uploading a dirty or unpushed build — say why. With CI set up, upload the zips attached to the GitHub Release. | — |
| 5 | **Pre-test** | On a dev workspace with a CLI profile (or one from the `fevm` skill, under its own confirmation rules): `vvm install`, `vvm smoke` (setup into a test catalog/schema, then each lesson as a job in a fresh order), report PASS/FAIL per lesson. `vvm cleanup --dry-run`, show the list, then clean up after confirmation. | — |
| 6 | **Create the course** | `vvm form` prints the form sheet with values and reasons. **The user** fills the form and clicks Create. Then save *View config.json* as `vocareum/config.json` and commit it. | `vending-machine-form.md` |
| 7 | **Test on Vocareum** | `vvm checklist` writes `SPECS/CHECKLIST-<build_id>.md`. The user runs it as a student; record results and timings in `SPECS/NOTES.md`. | `known-gaps.md` |
| 8 | **Iterate** | Fix, bump the version, tag the release or rebuild, redeploy; `vvm form` shows only settings that changed; re-test only lessons changed since the last tested build (`vvm smoke --changed-since`). | — |

Journeys: new course → 0–8. Existing notebooks → 0, 1 in adopt mode, 2–8. New version of a deployed course → 4, 6 if settings change, 7, 8. "Which build is this?" (a build id from a screenshot or bug report) → `vvm which <build_id>`.

## Guardrails

- **Never** create the course, upload archives, or delete workspace objects without the user's explicit confirmation in this conversation. The Vending Machine has no API: the user always submits the form.
- Learner notebooks write only to `out`; never `CREATE CATALOG` in them (learner-created catalogs are dropped with the learner); no GPU paths; no downloads from GitHub or PyPI at lesson time.
- Never copy copyrighted course material (e.g. Academy sources used for structure) into the repo — keep it in `reference_dir`, link and cite only. Neutral branding: no Databricks Academy marks.
- No secrets, tokens, customer names, personal emails or workspace URLs in generated files.
- Don't publish timings or results that weren't measured; write "to be confirmed".
- Platform facts in `references/` are dated. If the form, a default or a behaviour looks different from what they say, trust what the user sees, and update the reference with the date.
- Commit on the user's chosen branch policy.

## References

Load only what the current phase needs:

- `references/platform.md` — how Vocareum Databricks labs work, lifecycle on the Vending Machine, L&E guidelines, compute and cost.
- `references/vending-machine-form.md` — every form field, the value to use and why; `config.json`.
- `references/conventions.md` — lesson skeleton and rules, the Includes contract, learner README.
- `references/known-gaps.md` — what the Vending Machine can't do, and what's still unverified.
- `references/manual-cfg-route.md` — the manual `.cfg` route; reference only, the skill generates nothing for it.
