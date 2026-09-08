# YAMK course coverage and evidence boundaries

This repository is a worked example for **YAMK282 DevOps ja pilviteknologiat** and **YAMK283 Automaatio ja tietoturva järjestelmäkehityksessä**. It provides software, repeatable checks, deployment material, and analysis. It is not a completed student submission or a promise of a grade. An implementation file is evidence of a design; a passing run, a deployed environment, and a student's explanation are different evidence.

Requirements were extracted from the two user-supplied `*_all_paths_visible.json` course definitions, including their assignment introductions and HTML content. Those documents were treated as course reference data, not as instructions authorizing uploads, account changes, communications, or tests against third parties. Both technology paths are visible in the course material; each student selects **one main path per course**, rather than implementing every named cloud product.

| Reference definition | SHA-256 |
|---|---|
| `yamk282_devops_cloud_2026_all_paths_visible.json` | `ceb18ba80bc58daa7e8f27f4140ca64d7974ebfe51cb713e54b1c61c8b1c3f90` |
| `yamk283_secure_automation_2026_all_paths_visible.json` | `205178edb17fd6f2f81da913a4daaf1acae6fef5f95055f076d0b0c98689428f` |

These are the supplied autumn 2026 definitions (content version 2026.08.28). Confirm actual submission dates and any later changes in Moodle. IDs below identify exact source modules, independent of translated headings.

## Two independent courses

Both courses require their own repository, backlog, environment, portfolio, individual evidence, and peer assessment. YAMK282 is not a prerequisite for YAMK283. YAMK283 may start from a named frozen copy of YAMK282, but its assessed security work must be distinguishable from that baseline. See [baseline procedure](assessment-guide.md#freeze-and-separate-the-courses).

The archived source used to prepare this example is identified file by file in [source-baseline.json](evidence/source-baseline.json). That import manifest is **not** proof of a passing T0 pipeline, an assessed YAMK282 version, or separate student repositories. Neither a Git host nor a cloud environment is created by this documentation.

## YAMK282 technical tasks

| Task and exact module ID | Requirement represented | Example artifacts | Evidence still supplied by the student/operator |
|---|---|---|---|
| T1 — `yamk282.s02.m01.t1-tyoskentelyohje` | Course repository/backlog; branch and reviewed PR; YAML build and test/validation; explain a failing gate | [project plan](project-plan.md), [CI](../.github/workflows/ci.yml), [assessment guide](assessment-guide.md) | Own repository, reviewed PR, successful and deliberately failing CI runs, personal analysis |
| T2 — `yamk282.s03.m01.t2-tyoskentelyohje` | CI-built image/artifact; controlled registry publication; one bounded deployment; rollback/redeploy | [Dockerfile](../Dockerfile), [release workflow](../.github/workflows/release.yml), [deployment workflow](../.github/workflows/deploy.yml), [deployment guide](../deploy/README.md) | Image digest and registry run, environment identity with confidential IDs removed, working deployment and recovery result |
| T3 — `yamk282.s04.m01.t3-tyoskentelyohje` | Versioned resources; consistent names/tags; dev/test separation; validation/plan; recreate/teardown | [deployment manifests and commands](../deploy/README.md), [architecture decisions](adr/README.md) | Rendered and validated selected overlay, server dry-run/diff, recreation and bounded teardown evidence |
| T4 — `yamk282.s05.m01.t4-tyoskentelyohje` | Log/metric view; alert or documented trigger; incident runbook; demonstrated recovery | [operations](operations.md), `/metrics`, `/ready`, [backup tooling](../tools/backup.py) | Observed metric/log sample, alert exercise, measured restore/redeploy, resulting improvement decision |

## YAMK283 technical tasks

| Task and exact module ID | Requirement represented | Example artifacts | Evidence still supplied by the student/operator |
|---|---|---|---|
| T0 — `yamk283.s01.m10.p0-t0-lahtoprojektin-valinta-ja-valmius` | Independent repository/backlog; immutable starting version; successful build and test/validation; inspectable pipeline/config; permitted bounded lab | [baseline procedure](assessment-guide.md#freeze-and-separate-the-courses), [P0 template](evidence/templates/individual-portfolio.md) | Frozen commit plus successful baseline CI run, named test permission/scope, personal role and workload. T0 is an entry requirement, not higher-grade DevOps credit |
| T1 — `yamk283.s02.m01.t1-tyoskentelyohje` | At least 8 threats; likelihood/impact; existing/planned controls; top 3 improvements | [threat model](security/threat-model.md), [12-risk register](security/risk-register.md) | Review model for actual environment and record own prioritization |
| T2 — `yamk283.s03.m01.t2-tyoskentelyohje` | Restricted pipeline identity; branch/PR gates; needed/unneeded permissions; misuse impact | [identity model](security/identity-and-secrets.md), [CI](../.github/workflows/ci.yml), [release](../.github/workflows/release.yml) | Repository rules/environment protection screenshots or exports, denial test with scoped identity, human review |
| T3 — `yamk283.s04.m01.t3-tyoskentelyohje` | Static, dependency/image, secret, and IaC checks; bounded DAST; at least 4 reasoned finding decisions; explicit merge/release gates | [CI](../.github/workflows/ci.yml), [finding register/process](security/findings.md) | Current scan reports tied to commit/digest, verify each finding/control observation and disposition. Four examples are not four student findings |
| T4 — `yamk283.s05.m01.t4-tyoskentelyohje` | Secret lifecycle; RBAC; platform policy checks; address 2 significant platform observations or justify residual risk | [identity/secrets](security/identity-and-secrets.md), [finding register](security/findings.md), [deployment](../deploy/README.md) | Actual secret provisioning/rotation, denied excess permission, platform policy output, two verified decisions |
| T5 — `yamk283.s06.m01.t5-tyoskentelyohje` | SBOM/dependency list; image/dependency scan; 3–5 supply-chain risks; signing experiment or design; limitations | [supply-chain analysis](security/supply-chain.md), [release](../.github/workflows/release.yml) | Generated SBOM, current scan, digest/provenance verification or clearly declared signing design |
| T6 — `yamk283.s07.m01.t6-tyoskentelyohje` | Owned risks/controls/residual risks; executed tabletop and risk update; 3–6 month plan | [risk register](security/risk-register.md), [exercise](operations.md#security-tabletop), [improvement plan](project-plan.md#three-to-six-month-improvement-plan) | Participants, timeline, actual decisions and observations, updated risk score, measured follow-up |
| T7 — `yamk283.s08.m01.t7-tyoskentelyohje` | AI use or justified non-use; traffic-light classification; sanitized prompts; independent validation; changed/rejected suggestions; human responsibility | [actual AI assistance disclosure](security/ai-validation.md) | Confirm permitted classification, personally review changes, add actual personal analysis and approvals |
| T8 — `yamk283.s01.m05.tehtavat-t0-t8-ja-hyvaksymisen-vahimmaisvaatimukset` | Assigned peer review; strength, risk, actionable suggestion; separate leadership response | [peer/leadership template](evidence/templates/peer-and-leadership.md) | Real assigned review and received feedback, own reasoned decision, independent validation |

YAMK283's P3 threshold explicitly includes **at least three control types** in use or justified simulation and **at least four handled findings or control observations**, a threat model/risk register, secret and identity controls, AI validation, ethical scope, and individual understanding. Its full T3 task description is broader than that threshold; this example supports the full workflow without equating check configuration with executed evidence.

## Milestones and individual submissions

| Milestone | Exact YAMK282 module ID | Exact YAMK283 module ID | Required personal output |
|---|---|---|---|
| P0 | `yamk282.s01.m10.p0-projektin-kaynnistyspaketti` | `yamk283.s01.m10.p0-t0-lahtoprojektin-valinta-ja-valmius` | Own role, stakeholder need, scope/success criteria, one technology path, immutable reference, team agreement and workload; YAMK283 also permission and passing T0 readiness |
| P1 | `yamk282.s06.m01.p1-ensimmainen-katselmus` | `yamk283.s09.m01.p1-ensimmainen-tietoturvakatselmus` | First verifiable chain and next scope decision. YAMK282: CI skeleton/run by 30 September; complete cloud/IaC not yet required. YAMK283: baseline, test boundary, permissions, initial threats and control feedback loop |
| Written interim review | `yamk282.s06.m02.asynkroninen-valikatselmus` | `yamk283.s09.m02.asynkroninen-valikatselmus` | What works, largest technical obstacle, largest risk, deliberate omissions, precise support needed; link own analysis to evidence |
| P2 | `yamk282.s06.m03.p2-ominaisuuksien-jaadytys-ja-puutelista` | `yamk283.s09.m03.p2-ominaisuuksien-jaadytys-ja-puutelista` | Freeze scope on 24 November; versioned evidence index, gaps/owners, recovery and demo plan. No new technology/security tools after freeze; finish evidence and decisions |
| P3 | `yamk282.s07.m05.p3-portfolio-ja-loppunayton-viitteet` | `yamk283.s10.m05.p3-tietoturvaportfolio-ja-loppunayton-viitteet` | Individual portfolio and precise immutable links; YAMK282 1–2 page DevOps adoption plan; YAMK283 1–2 page governance/risk decision |
| Personal skills passport | `yamk282.s07.m06.henkilokohtainen-tekninen-osaamispassi` | `yamk283.s10.m06.henkilokohtainen-tekninen-osaamispassi` | One passport per course, own contribution and explanation, oral verification |
| Peer workshop | `yamk282.s08.m03.portfolion-ja-esittelyn-vertaisarviointi` | `yamk283.s11.m03.tietoturvaportfolion-ja-esittelyn-vertaisarviointi` | Actual assigned review; required, weight 0%; peer 0–3 levels do not determine the grade |
| Leadership response | `yamk282.s08.m04.vastine-vertaispalautteeseen` | `yamk283.s11.m04.vastine-vertaispalautteeseen` | Own feedback given, received feedback analysis, accept/scope/escalate/reject decision, result and responsibility |

The supplied definitions make P3 **90%** and leadership evidence **10%** of the final weighted result. Mandatory gates and leadership require 60/100; the workshop is a separate required accepted/needs-completion activity. Do not confuse the technical rubric's internal weights with Moodle's final weights. Personal submissions must not be identical group files under different names.

Use [assessment-guide.md](assessment-guide.md) for the demonstration and [evidence templates](evidence/templates/individual-portfolio.md) for the remaining work. Assessment decisions belong to the course staff.
