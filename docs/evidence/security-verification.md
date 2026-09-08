Verified locally on 8 September 2026 with Trivy 0.74.0 and the vulnerability database updated at 01:14 UTC that day. All final HIGH/CRITICAL gates passed; no findings were ignored or reclassified.

| Scope | Final scan time (UTC) | HIGH/CRITICAL findings | Evidence |
| --- | --- | --- | --- |
| Source dependencies, secrets and configuration | 08:08:40 | 0 | [Scan](source-security-scan.json), [Cargo SBOM](source-sbom.cdx.json) |
| Production image, Linux ARM64 | 08:09:53 | 0 | [Scan](production-security-scan.json), [image SBOM](production-sbom.cdx.json) |
| Maintenance image, Linux ARM64 | 08:07:22 | 0 | [Scan](maintenance-security-scan.json), [image SBOM](maintenance-sbom.cdx.json) |

The maintenance image uses a pinned Python 3.13 Alpine base, removes unused pip tooling, and pins the fixed `libuuid=2.42.3-r1` package. All nine recovery regression tests passed inside that final image with its filesystem read-only and networking disabled. Earlier Debian-based maintenance candidates failed the unchanged gate and were replaced.

[Machine-readable verification](security-verification.json) records exact image identities, report hashes, database metadata, source input hashes and the failed candidate results. The image SBOMs inventory detected operating-system packages; the separate Cargo SBOM supplies application dependency evidence. CI must scan its separately built AMD64 publication candidates. Zero selected-severity findings does not establish that an artifact is vulnerability-free.

Trivy warned that Alpine 3.24 is absent from its built-in EOL list. [Alpine's release table](https://alpinelinux.org/releases/) lists the branch as supported through 1 June 2028; vulnerability scanning itself completed successfully.
