# Manual `.cfg` route — reference only

> **As of:** 2026-10-16 (mmf-workshop `SPECS/VOCAREUM.md`, from go/vocareum-lab-development); compiled 2026-11-26.
> **The skill generates nothing for this route** (spec decision 7): no `.cfg`, no `lab_end` script. The only implementation, mmf-workshop's, has no recorded test on Vocareum. Read this when a course needs what the Vending Machine lacks — mostly a **lab-end hook** to clean up resources learners create.

## What it is

Building the course directly in Vocareum's admin UI instead of through the Course Vending Machine.

1. **Clone a template course** (*Clone by Copy*) rather than starting from scratch. For serverless-enabled workspaces the guidelines point to the **GenAI** org. Structure: Course → Assignment → Part; L&E usually makes one Assignment with one Part per lab, each Part with its own workspace configuration.
2. **Part settings:** Lab Type *Databricks*; users per workspace; Session Length (240 min standard); Time Budget (≤ 3× session length); **End Lab Behavior = Terminate** (with *Stop*, `lab_end` doesn't run); Timer and Readme button on; LTI on for Docebo, off for direct enrolment; Course Feedback on.
3. **Upload files** under *Configure Workspace → Files*:
   ```
   /voc/private/courseware/   # course .cfg + notebook archives (+ optional dbfs/, patches/)
   /voc/docs/README.md        # learner README, shown in the side pane
   /scripts/                  # .sh wrappers → /scripts/python/*.py
       workspace_init.py      #   on workspace creation (can be re-run)
       user_setup.py          #   on user creation
       lab_setup.py           #   on lab start
       lab_end.py             #   on End Lab / session expiry — reap resources here
   ```
4. **Never click "save image".** `/voc` is already persisted on NFS, and images use up the team's limited container slots.

## The `.cfg` file

A JSON file in the course folder, ending in `.cfg`. A *DBC object* is `{src, entry?, folder?, patch?}`, where `src` is an archive in the course folder (a `.zip` works).

| Key | Runs as | Receives | Use |
|-----|---------|----------|-----|
| `content` | — | — | The labs zip (`dist/<slug>-labs.zip`), `entry` = `AGENDA` |
| `workspace_setup` | admin (workspace + metastore) | `host`, `token` | `setup/workspace_setup` — same notebook as on the Vending Machine |
| `user_setup` | admin | `host`, `token`, `username` | `setup/user_setup` — per-user assets, as admin |
| `autograde` | admin | `host`, `token`, `username`, `table` | Out of scope (spec decision 6). Must write the `table` with `rubric VARCHAR(255)`, `score INT`, `feedback VARCHAR(255)` |
| `admin_cluster_config` | — | — | Cluster that runs the hooks above (DBR, node type, Spark confs, libraries) |
| `cluster_config` / `warehouse_config` | — | — | Managed per-user compute; not needed for serverless courses |
| `secrets`, `enable_dbfs`, `entry` | — | — | Rarely needed |

A `dbfs/` subfolder is copied into DBFS; `patches/` holds hotfix replacements for notebooks inside an archive.

## What carries over from a Vending Machine course

- The archives from `vvm build`, unchanged.
- `setup/workspace_setup` (hooks run on an admin cluster here, not serverless — check the DBR and Unity Catalog access mode for `/Volumes`).
- `setup/user_setup` — on this route it can run as the real `user_setup` hook.
- The learner README.

## What a `lab_end` script must do

Standard library only (it runs in Vocareum's container, not in Databricks). For the learner whose lab ended: cancel their active runs; delete the jobs, clusters and MLflow experiments they created; leave the platform to drop their catalog/schema. Called from the template's `lab_end.py`. **Open:** how the template's `lab_end.py` receives `host` / `token` / `username` — check in the cloned template.

## Examples (untested)

mmf-workshop at `de2c7c8`: `vocareum/courseware/mmf-workshop.cfg` and `vocareum/scripts/python/mmf_lab_end.py` — https://github.com/lbruand-db/mmf-workshop/tree/de2c7c8/vocareum

## When to revisit (→ generate `.cfg` + reaper in the skill)

- A real course needs `lab_end` and can be tested on a manually cloned course, or
- the Vending Machine owners decline to add a lab-end hook.
