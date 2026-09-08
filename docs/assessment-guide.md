# Assessment and demonstration guide

Read [course-map.md](course-map.md) first. This example is reusable technical material; it leaves personal statements, real CI/deployment runs, permission, reviews and assessment decisions to people. [Release status](../RELEASE_STATUS.md) distinguishes executed checks from pending work.

## Freeze and separate the courses

The imported original-file manifest in [source-baseline.json](evidence/source-baseline.json) identifies the supplied archive contents. The current example includes improvements made after that import. The manifest alone does not meet YAMK283 T0 because T0 also requires a working repository/pipeline, passing build/validation and a permitted lab.

For course adoption:

1. Create the course-owned YAMK282 repository with its own issue backlog, protected default branch, reviewed changes and environment. Record the initial commit, source provenance and role agreement.
2. If YAMK283 uses this project's starting point, select a **passing** immutable version. Record its full commit, CI run, build/test result, artifact digest when available, configuration and known limitations. Name the frozen baseline before any assessed YAMK283 change.
3. Copy that exact version to a separate YAMK283 repository with its own backlog, environment, permission record and portfolio. Preserve the original source reference. Do not let YAMK283 changes alter YAMK282's frozen evidence.
4. Record security changes relative to the YAMK283 baseline, including personal commits/PRs and positive/adverse evidence. Already-present controls are starting conditions, not new personal work.
5. Maintain a baseline record with `source_repository`, `source_commit`, `source_ci_run`, `source_image_digest`, `target_repository`, `target_initial_commit`, `test_scope`, `known_gaps` and `recorded_by`. Leave unavailable values explicitly pending.

A Git tag can be moved; retain full commit IDs and restricted evidence links, and apply host protections appropriate to the course. No Git-host repositories, tags, student identities or cloud environments have been fabricated for this example.

## First reproducible demonstration

From the example root, the default container setup is an offline deterministic demonstration:

```bash
python tools/create_admin_secret.py
docker compose up --build -d
docker compose logs --tail=50 cyberwatch
```

Create the secret once; the command deliberately refuses to overwrite an existing token. On later runs keep the existing file. Restrict its filesystem access to the operator account. Even offline mode needs this token because the process binds the container network.

Open `http://127.0.0.1:8080` and show the explicit demo state, intelligence list, CVE/source evidence, `/health`, `/ready` and `/metrics`. Confirm `/api/v1/refresh` cannot initiate live ingestion in demo mode. Follow [deployment guide](../deploy/README.md) for exact live-mode, cluster, backup and stop commands. Keep demo and live databases separate; the application rejects incompatible mode reuse.

For native work, use the [README](../README.md) and [check runner](../tools/check.py). The local lab demonstration is useful evidence of behavior; it does not prove cloud deployment, hosted CI or live upstream freshness.

## YAMK282 P3 presentation

The supplied course's `yamk282.s07.m04.p3-loppuesittelyn-ohje` specifies an 8–12 minute group demonstration and 5–8 minute individual evidence segment, with the listed presentation date 2 December 2026. Confirm current arrangements in Moodle.

| Approximate group timing | Demonstration | Evidence to prepare |
|---|---|---|
| 0–2 min | Stakeholder need, scope and architectural choice | P0 charter, chosen platform versus alternative, personal responsibilities |
| 2–5 min | One backlog item → reviewed PR → build/test failure and correction → successful gate | Immutable issue/PR/commit/run links; explain where error stops delivery |
| 5–8 min | Selected digest → environment validation/diff → working deployment | Registry record, rendered IaC, rollout/readiness, separate environment parameters |
| 8–10 min | Logs/metrics, alert condition, recovery | Actual observed metric/trigger and measured restore/redeploy record |
| 10–12 min | Limitation, cost/ownership, improvement | Gap list, resource/expiry plan, a metric used to choose next action |

Individual segment: show an artifact you actually changed, explain the whole delivery chain and one alternative, demonstrate one relevant command/result, and describe the limits of your evidence. Include a 1–2 page DevOps adoption decision and the personal passport. A prerecorded verified run with immutable references is a useful fallback when the live environment is unavailable; label its time/version.

## YAMK283 P3 presentation

The supplied `yamk283.s10.m04.p3-loppuesittelyn-ohje` lists 9 December 2026. Show baseline identity before describing improvements.

1. Explain protected value, authorized scope, baseline and your own post-baseline change.
2. Trace one threat through likelihood/impact, chosen control, positive test, adverse test, finding decision, residual risk and owner.
3. Show at least three actual control types and four handled findings/control observations. Explain which failure blocks delivery and why another observation may be deferred under an explicit decision.
4. Explain least privilege, secret rotation and two platform decisions with actual validation. Use a denied action as evidence, not a screenshot of an administrator account.
5. Tie the SBOM/scan/provenance or signing design to the correct artifact, and explain their limits.
6. Show actual tabletop outcomes and how they changed the risk register and 3–6 month improvement plan.
7. Disclose AI assistance and independent validation, distinguish your own contribution, and present one personally reasoned residual-risk decision in the 1–2 page governance memo.

Do not manufacture a vulnerability, peer review, test result, approval or deployment to satisfy a checklist. A clear gap with an owner and evidence plan is better evidence management than a false completion claim.

## Evidence package

Use one [individual portfolio](evidence/templates/individual-portfolio.md) per person per course, one [run record](evidence/templates/run-record.md) per actual experiment, and real [peer/leadership records](evidence/templates/peer-and-leadership.md). Keep a small index linking requirement ID → claim → commit/digest → test/run → result → limitation → personal contribution. Redact secrets, people, private URLs and environment/account identifiers as required by the course. Retain evidence before deleting short-lived environments or CI artifacts.

At P2 freeze scope and list gaps instead of introducing a new tool. The supplied freeze date is 24 November 2026. Allocate time for the independent peer workshop, personal leadership response and oral explanation; working software alone does not complete those requirements.
