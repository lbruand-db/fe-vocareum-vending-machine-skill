# Known gaps and unverified facts

> **As of:** 2026-11-26, from mmf-workshop (`vocareum/README.md` *Known gaps*, `SPECS/VOCAREUM.md` §9, `SPECS/NOTES.md`). Update this file from every Vocareum test run (phase 7): move items from *Unverified* to *Confirmed* with the date and build id, or correct them.

## 1. What the Course Vending Machine can't do

| Gap | Impact | What the skill does |
|-----|--------|---------------------|
| **No lab-end hook** | Jobs, clusters, endpoints and experiments a learner creates are not deleted when the lab ends; they keep costing | At intake, ask whether learners create billable resources; if yes, warn. Keep *Allow lab to be stopped* **off**; steer learners to serverless in the README; list leftovers after each test (`vvm cleanup --dry-run`). The manual route has `lab_end` (`manual-cfg-route.md`). Ask the app owners in #field-driven-labs-vocareum for a lab-end hook |
| **No per-user setup hook** | Files a learner needs in their home folder can't be installed by the platform | Install from each lesson's Classroom setup (`_user_assets.py`); `setup/user_setup` as admin fallback |
| **No API** | Course creation can't be scripted | `vvm form` prints the values; the user fills the form; `config.json` saved and diffed |
| **No autograde** | No grades back to an LMS | Out of scope; *Check your work* is learner feedback only |
| **Setup timeout max 120 min**, default 20 | Long data loads or reference runs fail the setup job | Idempotent steps (a re-run continues); measure setup time in pre-test; set the timeout from it |
| **Template *Genie Code* adds the *Consumer* entitlement** | May block notebooks and jobs ("consumer-only access") | Use the *Data Science* template |
| **No GPU** | GPU steps fail or are silently ignored | Precompute on CPU in setup, or drop; lint `no-gpu` |

## 2. Unverified — check on the first Vocareum run of a course

Each of these has a checklist item (`vvm checklist`), so the first test run settles it.

| # | Assumption | How the checklist checks it | If wrong |
|---|-----------|-----------------------------|----------|
| 1 | `ops.meta` keys are `catalog_name`, `schema_name`, `username`, in the `dbacademy` catalog | Classroom setup prints `[lab platform metadata]`, not `[workshop default]` | Outputs land in `{catalog}.{user}` — fix `_common` resolution and this file |
| 2 | `account users` covers Vocareum learners (for read grants) | A learner can `SELECT` from `{source}` | Grant to the right group; update `data.learner_group` |
| 3 | The serverless setup job can reach GitHub and PyPI to stage assets | Setup job succeeds; assets present in `/Volumes/{catalog}/{schema}/assets` | Upload assets to the volume from the author's machine; document it in `VERSIONS.md` |
| 4 | The `environment_version` notebook header is honoured on Vocareum | Lesson cells run with the expected library versions | Pin through `%pip install -r` from the volume instead |
| 5 | Learners can read staged assets in the volume | Per-user asset install succeeds | Add `READ VOLUME` grant in setup |
| 6 | Genie Code is enabled on Vending Machine workspaces (Data Science template), and its concurrency suffices for a full workspace | Genie Code panel opens; skill listed | Request enablement at go/lpt-general-request; lower *Max Users per Workspace* |
| 7 | What Vocareum cleans up at the end of a session for the `dbacademy` user schema | After the test, check whether the learner's schema still exists | Document; adjust the cleanup step |

## 3. Confirmed

| Fact | Date | Where observed |
|------|------|----------------|
| No GPU EC2 quota (`AWS_RESOURCE_QUOTA_EXCEEDED` on `g4dn.xlarge`); serverless GPU ignored | 2026-10-15 | Vocareum test workspace (mmf-workshop `SPECS/NOTES.md`) |
| Serverless compute enabled; `dbacademy` catalog with `ops.meta` present | 2026-10-15 | Same |
| `displayHTML` widgets render in the sandboxed output iframe, light and dark | 2026-10-18 | Dev workspace (not Vocareum) |

*(Add rows here as courses are tested — date, build id, course.)*
