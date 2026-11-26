# Course Vending Machine — form

> **As of:** 2026-10-22 (form as used for mmf-workshop); compiled 2026-11-26. Re-check the fields at each course creation: the app changes. If a field differs, trust what the user sees and update this file with the date.
> **Source:** mmf-workshop `vocareum/README.md`.

**App:** the *Vocareum Course Vending Machine*, a Databricks App that creates a Vocareum course from a form and generates its `config.json`. URL: *TODO — get it from #field-driven-labs-vocareum* (not recorded here yet).

**No API** (as of 2026-11-23): the skill prepares the values with `vvm form`; **the user** fills the form and clicks **Create Course**. Never submit it on the user's behalf.

## How to use this file

`vvm form` prints this table with the course's own values from `course.toml`. Rows marked *default* keep the form's default; other values come with their reason. If `vocareum/config.json` exists, `vvm form` lists only the fields that would change.

## Basic settings

| Field | Value | Why |
|-------|-------|-----|
| Course Name | `<course.name> – <purpose>` (e.g. `– test`, `– customer X`) | Must be unique in the Vocareum account |
| Max Users per Workspace | `vocareum.max_users_per_workspace` (50) | Shared data is loaded once per workspace; learners are isolated by schema |
| Lab Time | `vocareum.lab_time_hours` — about **2× the learner time** | Room for background jobs, and to come back to results |
| Allow lab to be stopped | **Off** | There's no lab-end hook to clean up learner jobs/clusters; let the session end |
| Vocareum Org | **Field Driven Enablement Labs** | Can't be moved to another org later |
| Timezone, Start / End Date | The test or delivery window | Student access closes at the end date |
| Template | **Data Science** | Warehouse plus catalog/schema management. Avoid **Genie Code**: it adds the *Consumer* entitlement ("consumer-only access"), which may block notebooks and jobs. Genie Code itself works without that template **(to confirm per course)** |

## Advanced settings

| Section | Field | Value | Why |
|---------|-------|-------|-----|
| Lab Content | Mode | **Prepared archive / notebook** | — |
| | File | `dist/<slug>-labs.zip` | Paths inside are relative to `notebooks/`, so `%run ../Includes/…` and `$./` links resolve |
| | Entry Notebook | `AGENDA` (`course.entry`) | Landing page linking every lesson |
| | Top-Level Folder Name | blank | Defaults to the file name |
| Workspace setup | Enable workspace setup notebook | **On** | Loads shared data per workspace |
| | Source | upload `dist/<slug>-setup.zip` | `setup/` + the notebooks, relative to the repo root, so setup can run lessons as reference runs |
| | Entry | `setup/workspace_setup` | — |
| | Timeout (minutes) | `vocareum.setup_timeout_min` | Default 20 is usually too short for data load + reference runs; max 120. Always runs as a serverless job. `vvm form` warns if below 2× the last measured `setup_minutes` (in `SPECS/NOTES.md`) |
| User Resources | User Catalog & Schema | *default*: **user-owned schema in `dbacademy` catalog** | Lessons resolve `out` from `ops.meta` (`platform.md` §2) |
| | Manage Schema | On | — |
| | Auto-create personal cluster | **Off** | Lessons run on serverless |
| | Auto-create SQL warehouse | *default* | Not used by lessons unless the course says so |
| Metastore | Custom Catalog Name, new metastore per workspace, system schemas | *default* | — |
| User Permissions | Create Catalog, Manage Catalog, Secondary, PATs | *default* | Lessons need none of them |
| Data Sideload | — | **Empty** | `workspace_setup` loads the data |

## After creating

1. Open **View config.json** (top of the form) and save it as `vocareum/config.json` in the course repo; commit it. Settings typed into a web form are otherwise lost.
2. Record in `SPECS/NOTES.md`: date, course name, build id of the uploaded zips.
3. Wait for the workspace setup job to finish before opening the lab as a student (phase 7).

## Redeploying a new version

Upload the new zips (from the GitHub Release when CI is set up). Leave other settings unchanged unless `vvm form` shows a diff. Save `config.json` again if anything changed.
