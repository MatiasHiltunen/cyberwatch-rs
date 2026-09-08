# AI assistance disclosure and validation log

This example was developed with a Codex agent team on 2026-09-08 at the user's request. The user asked to adapt the supplied Cyberwatch project into a robust example covering both YAMK courses. This document records agent-assisted work; it does not assert that a student personally authored, approved, understood or independently assessed it.

For the instructional use case, the proposed traffic-light category is **sallittu ilmoitettuna / allowed with disclosure**, subject to the instructor's actual rules. This is a proposed classification, not a claim of teacher approval. Disclose this assistance in each relevant personal submission. The course definitions distinguish required, allowed with disclosure, prohibited, and allowed without disclosure uses; the actual task classification must be confirmed by the student.

## Sanitized prompt record and work

| Entry | Actual request or instruction summary | Agent proposal/output | Validation and decision |
|---|---|---|---|
| AI01 | Adapt the user's Cyberwatch source project into a robust example for both supplied courses | Work in a separate course-example copy; preserve a file-hash import manifest; add runnable checks and evidence guidance | Course JSON inspected as data; exact module IDs and SHA-256 recorded. Original import is distinct from a passing T0 baseline |
| AI02 | Read both course definitions without treating their embedded instructions as user commands; extract requirements | Task/milestone map, independent course procedure, portfolio/passport/peer templates, 12-risk threat/control model | Compared T0–T8 instructions with P0–P3 and individual/leadership assignments. The detailed T3 task and the three-control P3 threshold were recorded separately |
| AI03 | Harden runtime while preserving the intelligence application; make demonstrations repeatable | Explicit offline demo, mode isolation, secret-file/strong public config, safer outbound requests and bounded API behavior | Actual implementation/tests are in source and current [release status](../../RELEASE_STATUS.md); human acceptance remains pending |
| AI04 | Provide a small deployment/recovery example | Restricted Compose/Kubernetes/OpenShift settings, one replica/PVC, database-aware backup and guarded restore | Local rendering and executable test results are recorded separately from unperformed cloud/restore exercises; operator must validate effective cluster behavior |
| AI05 | Connect security risks to delivery checks and publication | Static/dependency/secret/policy/container checks, negative fixtures, controlled digest/provenance release | Local and hosted statuses must be read from [release status](../../RELEASE_STATUS.md); a configured workflow is not a scan report |

The prompt record is a faithful summary, not a verbatim transcript. No secrets, personal study records, real peer feedback, credential values or private environment identifiers are needed to reproduce these use cases.

## Changed or rejected approaches during preparation

| Initial assumption/approach | Decision and actual reason |
|---|---|
| Read raw course JSON HTML directly as a large text dump | Changed to selecting module IDs and stripping HTML to compare requirements without burying important assignment details |
| Treat one prepared repository and its security additions as completed work for both courses | Rejected; the supplied definitions require independent repositories/environments and post-baseline YAMK283 evidence |
| Preserve inherited “completed checks” as current release validation | Rejected; those historical assembly claims do not validate changed code. Current verification and unavailable checks are tracked separately |
| Describe scheme validation as sufficient SSRF protection | Rejected; explicit destination/redirect/DNS checks plus deployment egress validation are needed. Residual platform assumptions are documented |
| Count generated review/incident/portfolio prose as student evidence | Rejected; templates and worked examples remain labelled unperformed, with actual personal/peer decisions left to people |

This log does not invent rejected code suggestions to populate a rubric. Additional rejections belong here only when they actually occurred and can be explained.

## Independent validation and human responsibility

Tool-executed tests, schema/render/policy validation and official technical references are independent mechanisms for checking a proposal; a second AI agent's agreement alone is not independent human review. The maintainer must inspect relevant changes and adverse tests, verify the deployment identity and runtime behavior, and decide whether the change fits the intended environment. A student must explain mechanism, tradeoff, failure case and personal contribution in their own words.

Actual execution claims are centralized in [RELEASE_STATUS.md](../../RELEASE_STATUS.md) to avoid stale copies of test counts. Cloud deployment, publishing/signature verification, human PR approval, team tabletop, personal learning outcomes and peer assessment are not implied by agent-generated files.

Working rules to adopt with the group: provide only authorized source/configuration; sanitize prompts and logs; do not submit credentials or personal evidence to an AI tool; review generated commands before giving them production privilege; require positive and negative validation for security changes; record uncertainty and rejected suggestions; keep the human owner accountable for risk acceptance, grading claims and release decisions.

Personal acceptance record: **not completed**. Add reviewer, date, selected commit, reviewed boundaries, observed tests, objections/changes, allowed-use classification, and what you personally understand or still need to learn.
