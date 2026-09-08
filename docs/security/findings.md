# Findings, gate decisions, and exceptions

The observations below are **worked source/configuration reviews**, not fabricated scanner findings or completed student assessments. Compare the imported source hashes in [source-baseline.json](../evidence/source-baseline.json) to the current files. Validate each observation against your own frozen T0 baseline: improvements already present at T0 cannot be claimed as your later YAMK283 changes. Current execution status is in [RELEASE_STATUS.md](../../RELEASE_STATUS.md).

| ID / source | Observation and impact | Decision / rationale | Implementation and required closure evidence | Owner role / status |
|---|---|---|---|---|
| F01 / original `src/config.rs` | Public binding could proceed without rejecting absent/weak administrator configuration at startup; a risky environment could look operational | Fix configuration boundary; prevent insecure live public configuration before serving | Strong public-bind token checks and secret-file support; positive/negative configuration tests, actual startup denial | Maintainer; implemented design, verify selected version/test result |
| F02 / original Compose/container settings | Runtime configuration lacked a complete explicit restricted execution profile; a compromised process could gain unnecessary filesystem/capability access | Fix the platform default instead of assuming the image alone confines the process | Non-root/restricted runtime, minimal writable locations/capabilities, policy checks; inspect rendered configuration and actual pod/container identity | Operator; platform finding, cluster/runtime verification pending |
| F03 / original delivery workflow | CI provided compile/static quality checks but no complete dependency/secret/IaC/image gate or traceable publication chain | Fix delivery checks and retain evidence by commit/digest; do not treat Clippy correctness as comprehensive security analysis | CI/security policy, negative fixtures, release workflow; actual failed/green run and digest evidence | Reviewer; implementation review and hosted runs required |
| F04 / original operating material | General advice to back up a database did not provide a verifiable, guarded backup/restore procedure for the sole durable volume | Fix recoverability; file-copy success is inadequate evidence of database consistency | Database-aware `tools/backup.py`, integrity/hash checks and failure tests; measured disposable restore | Operator; platform/recovery finding, actual exercise pending |
| F05 / original source destination policy | Scheme validation alone could not prevent a configured source or redirect reaching internal services | Fix application destination/redirect and resolved-address checks; retain independent egress validation as a deployment requirement | R07, application HTTP helper and adverse tests; cluster network enforcement and denied metadata/private-address tests | Maintainer + operator; code mitigation, runtime egress verification pending |
| F06 / inherited `RELEASE_STATUS.md` | Historical packaging checks could be read as validation of the modified example | Fix evidence wording; current claims must refer to actual runs and limitations | Current release-status evidence and explicit pending remote/human checks | Evidence owner; documentation correction |
| F07 / credential-bearing outbound redirects | An NVD custom `apiKey` header is not covered by the HTTP client's standard Authorization stripping and could be forwarded across an origin-changing redirect | Fix credentialed NVD/GitHub requests to keep scheme/host/port; reject HTTPS downgrade; retain ordinary public HTTPS feed/CDN redirects | Application redirect regression tests; agent checked the installed reqwest implementation; reproduce on the selected commit | Maintainer; code mitigation, test result in release status |

F02 and F04 offer two concrete platform observations for T4. Their file changes are useful worked examples; a student still needs reproducible before/after evidence and reasoned acceptance of residual risks. F01–F04 offer four distinct decisions for T3 without pretending that a scanner emitted them.

## Gate policy

The executable workflow determines what actually fails the build. Review its commands and policy files on the selected commit; the table below defines the intent to check during adoption.

| Check class | Blocking policy | Why / evidence |
|---|---|---|
| Format, compiler, lint/test, source/schema/browser validation | Any configured failure blocks the CI gate | A release that cannot build or violates a tested safety invariant is unsuitable for publication |
| Static/security and secret checks | Semgrep's checked-in rules fail TLS-verification bypass and shell invocation patterns; Trivy blocks configured HIGH/CRITICAL secret findings | These focused patterns plus Clippy are justified limited static coverage, not general Rust vulnerability detection; preserve redacted metadata, never the secret itself |
| Dependencies and image vulnerabilities | Trivy's configured HIGH/CRITICAL findings fail; inspect current report before proposing any exception | Record advisory ID, reachability, digest/lockfile version and compensating control; absence of results is not a clean scan |
| IaC/runtime policy | Prohibited privilege/configuration fails validation | Pair valid manifest with negative fixture and server dry-run; local policy does not prove cluster enforcement |
| Local DAST/smoke | Run only against the disposable demo target; smoke failures and configured ZAP FAIL rules block CI | Passive ZAP rules block missing CSP, no-sniff and anti-framing headers; other baseline warnings remain in reports under `-I`. This is limited passive assessment, not full active DAST |
| Publication | Publish only when required workflow gate succeeds and the explicit release context is authorized | Host protections and operator approvals must exist outside YAML where applicable |

Never convert a scanner crash, unavailable database or missing binary into “no findings.” Keep the run failed or mark the evidence unavailable. A known false positive is a narrow documented rule/file/advisory decision, not a blanket disablement of a tool.

## Finding/exception record

For an actual observation record ID, tool/manual source and version, commit/image digest, redacted evidence, affected component, severity plus reachability/business impact, related risk/control, decision (fix / false positive / accept risk / backlog / block), owner, deadline, verification and residual risk.

An exception additionally requires an accountable human approver, precise affected advisory/rule/resource, reason immediate fix is disproportionate, compensating control and its test, maximum expiry, review trigger, and release scope. No approved exceptions ship with this example. If the current tooling does not consume exception records, a prose record cannot override its failure; implement and review a narrow policy change before the next release.

Proposed working service targets: triage high findings within two working days, block known exploitable critical/high paths before public exposure, review lower-priority backlog monthly. These are local project targets, not invented course rules or contractual commitments.

## Safe demonstration of a blocked change

Use existing negative policy/unit-test fixtures in a disposable branch. Show that the specific adverse fixture triggers the intended failure while valid configuration passes. Link the failing run to its corrective commit and successful rerun. Do not commit a real secret, add a real vulnerable dependency, disable gates, or publish deliberately unsafe images simply to obtain evidence. Clearly label synthetic fixture findings as test fixtures.
