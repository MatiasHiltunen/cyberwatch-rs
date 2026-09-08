# Risk register and control map

Working example dated 2026-09-08. Scores are design judgments for an isolated educational deployment, not measured frequencies or organizational risk acceptance. Likelihood (L): 1 unusual, 2 plausible, 3 expected under exposed conditions. Impact (I): 1 local nuisance, 2 interrupted service or polluted data, 3 compromise/loss affecting the service or delivery chain. Score=L×I; 6–9 high, 3–4 medium, 1–2 low. Residual scores are **conditional estimates** after verifying the stated controls. The service owner must accept actual residual risks.

| Risk | L×I before | Controls / evidence anchor | Proposed disposition and residual L×I | Accountable role; next review |
|---|---:|---|---|---|
| R01 Refresh or administrator identity abuse | 3×3=9 | Config/auth checks; token lifecycle; queue bounds; `src/config.rs`, API tests, [identity](identity-and-secrets.md) | Mitigate; 1×3=3 after auth/denial test; no public exposure before verification | Application maintainer; P1 and token changes |
| R02 Untrusted content executed in browser | 2×3=6 | Escaped text, safe URL schemes, security headers; browser smoke and static checks | Mitigate; 1×3=3, upstream text remains untrusted | Maintainer; every UI-rendering change |
| R03 Release pipeline or registry tampering | 2×3=6 | Read-only PRs, explicit publisher rights, review, digest/provenance; workflow and host rules | Mitigate; 1×3=3 after host configuration and denied-write test | Release owner; each workflow change / release |
| R04 Source-driven denial of service | 3×2=6 | Time/byte/concurrency bounds, backoff, source isolation; ingestion tests | Mitigate; 2×2=4, independent sources can all be unavailable | Maintainer; P1 then monthly |
| R05 Single-volume loss or incompatible restore | 2×3=6 | Online backup, integrity/hash verification, guarded restore, one replica; [runbook](../operations.md) | Mitigate; 1×3=3 only after measured restore; outage window remains | Platform operator; before deployment then monthly restore |
| R06 Compromised dependency or builder | 2×3=6 | Lockfile, scan gates, SBOM, restricted build identity, reviewed updates; [supply chain](supply-chain.md) | Mitigate; 1×3=3, unknown malicious code and compromised builders remain | Security reviewer; every release and dependency update |
| R07 Source URL/redirect SSRF and broad egress | 2×3=6 | Public destination/redirect and resolved-address validation, controlled source configuration and platform egress; syntax checks alone are incomplete | Mitigate and restrict deployment scope; conditional 1×3=3 after application adverse tests and validated egress. Cluster enforcement remains to verify; no blanket acceptance | Operator; before live ingestion / source changes |
| R08 Secret or sensitive evidence disclosure | 2×3=6 | Secret files/stores, read permissions, redaction, secret scans, demo data, sanitized logs | Mitigate; 1×3=3 after log/artifact review and rotation test | Operator + evidence owner; every evidence export |
| R09 Platform privilege or cross-course access | 2×3=6 | Restricted container/pod, namespace boundaries, minimal identity; manifest policy + cluster denial | Mitigate; 1×3=3 after server validation and permission test | Operator; before cluster rollout / RBAC changes |
| R10 Stale or false intelligence treated as fact | 3×2=6 | Preserve conflicting evidence, source health, explicit demo mode, analyst judgment | Conditional educational acceptance proposed; 2×2=4. Never automate remediation from confidence alone | Service owner; P2 and after source incident |
| R11 Unsafe AI change or false evidence | 2×3=6 | [AI validation log](ai-validation.md), adverse tests, human explanation and independent review | Mitigate; 1×3=3 after personal verification; pending human approval is explicit | Maintainer + each student; before adoption/submission |
| R12 Resource, supplier or retention lifecycle failure | 2×2=4 | Owner/expiry, resource limits, quota review, [teardown guide](../../deploy/README.md), evidence backup | Mitigate; 1×2=2 after scoped inventory/teardown rehearsal | Owner; P0, P2, end of environment lease |

## Control coverage and limitations

| Control family | Risks addressed | Positive demonstration | Negative demonstration |
|---|---|---|---|
| C01 API identity and bounds | R01, R04 | Authorized operation behaves as documented | Incorrect token, oversized query, disabled refresh denied |
| C02 Untrusted input handling | R02, R04, R10 | Valid fixture ingests/renders correctly | Script URL/malformed payload is rejected or safely displayed |
| C03 Delivery gate and provenance | R03, R06, R11 | Reviewed commit produces traceable image/evidence | Known failing check blocks; unrelated/modified artifact does not satisfy identity verification |
| C04 Runtime isolation and secrets | R07, R08, R09 | Required volume/secret is usable without elevated rights | Forbidden privilege/RBAC action fails; old rotated token rejected |
| C05 Recovery and observation | R05, R10, R12 | Readiness/metrics visible; valid backup restored | Corrupt backup rejected; outage/freshness trigger observed |
| C06 Evidence governance | R08, R11, R12 | Claim tied to commit/run/digest and personal explanation | Placeholder/unsupported claim is marked pending, not submitted as fact |

## Decision and exception lifecycle

Record discovery source → affected version → L/I and business consequence → control owner → fix or scoped exception → positive/adverse validation → residual risk → dated owner decision → review trigger. A code change alone does not close a risk. A passing scanner does not close unrelated risks.

High risk prevents public/production adoption until mitigated or a real authorized owner records a narrowly scoped time-bound decision. Proposed acceptance in this example is not that approval. Use [findings](findings.md) for gate behavior and the [decision template](../evidence/templates/run-record.md) for actual evidence. Any exception expiration, failed compensating control, newly exploitable path or wider environment scope reopens the risk.

After the tabletop, append date, changed assumption, old/new score, person responsible, immutable exercise record and next action. No tabletop has been asserted by this register.
