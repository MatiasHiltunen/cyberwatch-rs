# Project charter and improvement backlog

This is an example project plan for adaptation at P0. Role names below designate responsibilities, not people who have accepted them.

## Need, scope, and success

A small security team needs one place to inspect public advisories and distinguish corroborated CVE evidence from unverified reporting. The current operational problem is fragmented source checking and deployments whose working state cannot be reconstructed. The example combines a Rust API, embedded database, plain browser dashboard, and controlled delivery workflow.

Success means a reviewed change can be built, checked, packaged, deployed by immutable image digest, observed, and recovered in a bounded lab. The analyst can distinguish live public intelligence from the deterministic demonstration dataset. The security counterpart demonstrates that a risk leads to a control, an adverse test, a finding decision, and a measured follow-up.

Scope: one application replica, one persistent data volume, public source data, one primary platform, and a separate environment for each course. The reference main path is the alternative platform path using versioned Kubernetes/OpenShift configuration; CSC Rahti is an intended hosted option, subject to actual service access and cluster validation. Local Compose provides a safe rehearsal. Azure is a valid course choice but is not claimed as implemented by this project.

The environment is an educational intelligence dashboard, not a multi-tenant confidential incident system. Exclude sensitive case data, automated remediation, active scanning of external organizations, and high availability. Fetching public advisory feeds in live mode is distinct from vulnerability testing; assessment tests use demo mode and a local lab.

## Responsibilities and workflow

| Role to assign | Accountability | Review boundary |
|---|---|---|
| Service owner | Stakeholder value, scope, residual risk acceptance, environment cost and expiry | Approves changes affecting data use and accepted risk |
| Application maintainer | Parsers, API, deterministic tests, database behavior | Explains failure boundaries and adverse tests |
| Platform operator | Deployment, least privilege, secret provisioning, backup/restore and teardown | Verifies manifest effect in the chosen cluster |
| Security reviewer | Threats, scan interpretation, exception expiry, security tests | Challenges severity and validates control outcomes |
| Evidence owner | Immutable references, redaction, portfolio index | Ensures claims match actual evidence |

Students may combine roles; independent review still requires another person. At P0 record names, availability, decision rule, response time for reviews, conflict resolution, and how absent members demonstrate individual competence. Choose a protected default branch, short-lived change branches, an issue per observable outcome, and a reviewed PR. Every PR describes the problem, behavior, validation, operational effect, and evidence path. Do not claim repository protection is enabled merely because workflow YAML exists.

## Backlog

Implementation status is recorded in [release status](../RELEASE_STATUS.md); the entries below track adoption and evidence, not fabricated completed student work.

| ID | Course | Priority / owner role | Acceptance condition | Status |
|---|---|---|---|---|
| B01 | 282 P0/T1 | P0 / evidence owner | Course repository initialized; baseline commit and actual reviewed PR linked; individual workload/role recorded | Student action pending |
| B02 | 282 T1/T2 | P0 / maintainer | CI gate passes on selected commit; negative gate prevents publication; registry contains exact digest | Remote run pending |
| B03 | 282 T2/T3 | P0 / operator | Selected overlay validates, server dry-run succeeds, digest deployed, readiness observed, resource deletion/recreation shown | Environment action pending |
| B04 | 282 T4 | P0 / operator | Alert trigger observed; compatible database restore measured against RTO/RPO; incident follow-up recorded | Exercise pending |
| B05 | 283 T0 | P0 / evidence owner | Independent frozen baseline, passing baseline CI, authorized isolated environment, separate backlog | Student action pending |
| B06 | 283 T1/T3 | P0 / security reviewer | Verify R01/R03/R05 controls using positive and adverse cases; actual four observations classified with run links | Review/run pending |
| B07 | 283 T2/T4 | P0 / operator | Secret rotation and denial of excessive permissions demonstrated; two platform findings resolved/reasoned | Environment action pending |
| B08 | 283 T5 | P1 / maintainer | SBOM and dependency/image scan retained; exact digest attestation verified; trust limitations explained | Publication/run pending |
| B09 | 283 T6/T7 | P0 / service owner | Actual tabletop with decisions; risk register update; human review of AI work and allowed-use classification | Human action pending |
| B10 | Both P2/P3 | P0 / each student | Own evidence index, scope freeze, five decision analyses, passport, peer review and leadership response | Human action pending |

Top three security improvements are R01 (refresh/identity misuse), R03 (release integrity), and R05 (recoverability). They protect control, provenance, and retained evidence, respectively. Prioritize these over adding another dashboard panel or scanner.

## Three-to-six-month improvement plan

These are proposed targets; no service telemetry or completed months are implied.

| Time | Improvement and decision trigger | Owner role | Measurable outcome |
|---|---|---|---|
| 0–1 month | Deploy one isolated environment; complete real restore and denial tests; assign all risks | Operator + owner | One verified recovery; every high risk has a named owner and review date; 100% releases use digest |
| 1–3 months | Validate cluster egress restrictions for approved sources and DNS; automate bounded backup retention | Operator | Metadata/private address access denied in lab; daily backups and monthly restore evidence; RPO observed <=24 h |
| 1–3 months | Tune scanner gate using observed findings rather than disabling whole tools | Reviewer | No unowned high findings; zero expired exceptions; median triage <=2 working days |
| 3–6 months | Evaluate managed database/worker split only if measured demand or availability needs exceed one replica | Maintainer + owner | ADR compares total operating cost and recovery complexity against observed request/ingestion workload |
| 3–6 months | Practice compromised release and source poisoning tabletop; revise trust assumptions | Reviewer + owner | Detection-to-containment elapsed time measured; every exercise yields one implemented and verified improvement |

## Metrics, cost, and sustainability

Collect deployment frequency, change lead time (accepted change to successful rollout), change failure fraction (rollouts requiring rollback/intervention divided by all rollouts), and recovery time. Do not report zero failures as a percentage before any deployment. Store event time, commit, run, digest, environment, and outcome in a restricted evidence record. Compare medians and denominators before drawing conclusions.

A single replica and one database volume keep the instructional environment understandable and resource use bounded. Record actual platform quota, storage request, CPU/memory requests and limits, ownership label, and expiry before activation. Free educational capacity still has quotas and an opportunity cost; it is not an unlimited zero-cost production architecture. Avoid duplicate clusters for tooling practice, unnecessary refresh frequency, and unbounded logs/backups. Preserve sanitized evidence before teardown, then remove only the named course resources according to the deployment guide.

For P3, turn this into a personal 1–2 page adoption decision: stakeholder and bottleneck, role ownership, chosen flow/operating metric, cost and maintenance consequences, first deployment steps, alternatives rejected, and what measured result would change the decision.
