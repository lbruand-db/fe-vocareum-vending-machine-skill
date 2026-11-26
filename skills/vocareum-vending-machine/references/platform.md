# Vocareum platform — Databricks labs

> **As of:** 2026-10-16 → 2026-10-22, from building mmf-workshop; compiled 2026-11-26.
> **Sources:** L&E Confluence — *Field-Driven Enablement Labs in Vocareum* (go/field-driven-enablement-labs), *Vocareum Lab Development Guidelines* (go/vocareum-lab-guidelines), *Lab Development on Vocareum* (go/vocareum-lab-development); mmf-workshop `SPECS/VOCAREUM.md`, `SPECS/NOTES.md`, `vocareum/README.md`. Help: #field-driven-labs-vocareum.
>
> Facts marked **(unverified)** come from the docs but haven't been observed on a Vocareum course yet. See `known-gaps.md`.

## 1. What Vocareum provides

Databricks Field Engineering runs labs as **Vocareum Cloud Labs — Databricks**: Vocareum provisions real Databricks workspaces and redirects learners into them.

| Fact | Consequence for a course |
|------|--------------------------|
| **AWS only** | AWS instance types; no Azure/GCP-specific features |
| **Shared workspaces**: up to *Max Users per Workspace* learners each; Vocareum opens another workspace when one is full | No per-learner workspace. Isolate learners by schema |
| **One metastore per workspace** | Shared data is loaded **per workspace** by the workspace setup hook — never by hand, never once globally |
| **Learners are workspace users, not admins**; nobody reaches the AWS or E2 account | All admin work (shared catalogs, grants, data load, staging) runs in the setup hook |
| Learners may create catalogs, but **any catalog a learner creates is dropped at their cleanup** | Learner notebooks never `CREATE CATALOG`: a learner-created shared catalog would take the shared data with it |
| Learners have `SELECT ON ANY FILE` | — |

## 2. Where a learner writes

The platform gives each learner a per-user location and publishes it in a metadata table **`<catalog>.ops.meta`** (key/value rows; keys `catalog_name`, `schema_name`, `username`) **(keys unverified)**. With the Vending Machine's default *User Resources* setting, that's a **user-owned schema in the `dbacademy` catalog**.

On the manual route, the docs describe instead a **managed catalog per user** named after the Vocareum username (`vocuser12345@vocareum.com` → `vocuser12345_vocareum_com`), with all privileges but no drop, dropped at user cleanup.

`Includes/_common` therefore resolves `out` in this order and prints which rule applied (`[resolved_by]`):

1. `user_catalog` / `user_schema` widgets (pre-tests, setup reference runs);
2. `ops.meta` for this user (current catalog, then `dbacademy`) → `[lab platform metadata]`;
3. a catalog named after the user → `[Vocareum managed catalog]`;
4. otherwise `{catalog}.{user}` → `[workshop default]` (instructor-led use outside Vocareum).

On Vocareum, a lesson printing `[workshop default]` is a bug to report.

## 3. Lifecycle on the Course Vending Machine

| Event | What runs | Notes |
|-------|-----------|-------|
| Course created (form submitted) | Vocareum course and its settings | `config.json` generated (*View config.json*) |
| Workspace provisioned | **Workspace setup** notebook from the setup archive, **once per workspace, as a serverless job** | Timeout default **20 min, max 120**. Runs as admin |
| Lab start | **Lab Content** archive imported into the learner's workspace folder (*Top-Level Folder Name*, default the file name); opens the *Entry Notebook* | — |
| Each lesson | The lesson's own `Classroom-Setup-x.y` (course code, not a platform hook) | Where per-user installs happen, since there's no per-user hook |
| Lab Time reached / End Lab | Vocareum ends the session | **No lab-end hook** — nothing cleans up learner-created jobs or clusters |

**Not available on the Vending Machine:** a per-user setup hook (`user_setup`), a lab-end hook (`lab_end`), autograde. All three exist on the manual route (`manual-cfg-route.md`).

## 4. L&E guidelines

**Do:**
- Keep cost down (Vocareum, AWS and DBU): **minimum** compute and data size; serverless.
- Share read-only data through Unity Catalog.
- Pre-create everything that isn't a learning objective (data, reference results, installs).
- Give learners a `README.md` with objectives, instructions and resources (shown in the Vocareum side pane).
- Shortcut slow tasks "like a cooking show": pre-computed results a cell can copy in seconds.
- Identify quotas and limits early (jobs, serverless, Genie Code concurrency per workspace).
- Set the session length thoughtfully; time budget **≤ 3× the session length**.
- Automate setup **and** termination.

**Don't:**
- Use **GPUs** — expensive and taken from customers.
- Use provisioned-throughput model serving.
- Use third-party resources (external APIs, code, libraries) where avoidable — stage pinned copies in a volume.
- Use private-preview features that need workspace-level enablement without an API. Request enablement at go/lpt-general-request if unavoidable.

## 5. Compute

- **Serverless** notebooks and jobs: enabled, and the default for lessons. Pin the environment with the notebook header (`environment_version`, see `conventions.md`).
- **No GPU** (observed 2026-10-15 on a Vocareum workspace): classic `g4dn.xlarge` fails with `AWS_RESOURCE_QUOTA_EXCEEDED` (no GPU EC2 quota), and serverless GPU (`hardware_accelerator`) is silently ignored. Consistent with the guidelines — don't ask for quota. Precompute GPU results on CPU in setup, or drop the step.
- Cluster policies on the observed workspace: Personal Compute, Power User, Shared, Job, Legacy Shared. Learners *can* create clusters — steer them to serverless in the README.

## 6. Genie Code

- Needs a Premium or Enterprise workspace; pay-as-you-go with a free monthly allowance per user.
- Skills must sit at exact paths in the learner's home: `/Users/{user}/.assistant/skills/` (bundle contents flat) and `/Users/{user}/.assistant_instructions.md`. The leading dots matter.
- **(unverified)** Enabled on every Vending Machine template, and concurrency limits for a full workspace.
- The *Genie Code* template adds the *Consumer* entitlement — use *Data Science* (see `vending-machine-form.md`).

## 7. Cost

What learners leave running dominates cost. One-off setup cost per workspace (data load, reference runs) is split across its learners. mmf-workshop estimated ~$2–4 per learner for serverless notebooks and jobs on 100 series (estimate, not measured on Vocareum), plus Vocareum and AWS platform costs.
