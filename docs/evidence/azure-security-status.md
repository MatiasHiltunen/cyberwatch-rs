# Azure security evidence

The final source gate passed at 10:14:12 UTC. The final installed-host package
gate failed at 10:25:45 UTC and remains visible. The service must not be described
as having a clean host vulnerability scan. Trivy 0.74.0 used the database updated
at 07:08 UTC on 8 September 2026.
The official Windows scanner archive and executable were checksum-verified;
exact identities and scan times are in the linked JSON status files.

| Scope | HIGH | CRITICAL | Result |
| --- | ---: | ---: | --- |
| Current source: vulnerabilities, secrets and supported configuration checks | 0 | 0 | [Passed](azure-source-security-status.json) |
| Initial Ubuntu installed-package inventory, 680 packages | 328 | 10 | [Failed](azure-host-initial-security-status.json) |
| Final host after maintained-kernel migration, 680 packages | 1,504 | 45 | [Failed](azure-host-security-status.json) |

The [unchanged production image](production-security-scan.json) previously
passed its image gate; the deployed image configuration is checked against the
reviewed Docker archive. Its result is separate from the host OS result.

The initial 338 host findings mapped through `linux-cloud-tools-common` and
`linux-tools-common` at `6.8.0-139.139`: 169 package associations each, covering
169 unique CVEs. The report provides no fixed version for these associations.
No selected-severity finding was reported for the other inventoried packages,
including Nginx, Certbot, OpenSSL and Python cryptography. This package-level
mapping does not establish the runtime applicability of every kernel flaw.
Removing the two utility packages was rejected because APT's simulation would
also remove the Azure kernel metapackage and eight kernel/integration companions.

The final scan reports 1,549 package associations for **175 unique CVEs** across
nine kernel-source packages. Seven Azure packages at `6.8.0-1067.75` have 173
associations each; the two common utilities at `6.8.0-139.139` retain 169 each.
The report supplies no fixed versions. No selected-severity findings were
reported for other inventoried packages. The maintained Azure 6.8 packages are
now represented in vendor matching; the EOL 6.17 stream was not reported
equivalently. The count difference is not a measure of changed runtime
exploitability. Individual advisory review and any accountable human risk
acceptance remain outstanding; no exception is recorded.

Vendor review prevents treating absent kernel findings as proof of safety.
Ubuntu lists Noble `linux` and `linux-azure` as vulnerable for
[CVE-2026-53398](https://ubuntu.com/security/CVE-2026-53398); its record marks the
6.17 Azure stream as end of life.
[CVE-2026-63940](https://ubuntu.com/security/CVE-2026-63940) also records the 6.17
stream's end-of-life status. The controlled transition to the maintained
`linux-azure-lts-24.04` stream completed: the host runs `6.8.0-1067-azure`, with
metapackage `6.8.0-1067.75`. A trial boot preserved data and service health;
13 reviewed obsolete 6.17 packages were then removed. A second ordinary boot
passed without a version-specific pin, with the same data UUID and 2,232 records.
The [final runtime check](azure-final-runtime.json) found no loaded `nfsd` module
or NFS server port listener; the [final HTTPS check](azure-live-final.json) passed
17 checks at 10:16:42 UTC.
These are scoped observations, not proof that all kernel advisories are fixed.
No findings have been suppressed or reclassified as false positives.

The final inventory was exported from the actual VM after explicit user approval,
with guest and downloaded
SHA-256 values matched. It contains `/etc/os-release`, `/etc/lsb-release` and
`/var/lib/dpkg/status`; it omits credentials and application data. The
[final raw host report](azure-host-final-security-scan.json) and
[final inventory SBOM](azure-host-final-sbom.cdx.json) describe that snapshot, not a
full filesystem/secret scan or an exploitability assessment. A first export
missing the Ubuntu detector's release marker was rejected as incomplete. The
[initial report](azure-host-initial-security-scan.json) and
[initial SBOM](azure-host-initial-sbom.cdx.json) remain available for comparison.

The [new source report](azure-source-security-scan.json) is distinct from the
pre-Azure source scan. It analyzed Cargo dependencies and 13 recognized Dockerfile
and Kubernetes configuration files. Bicep and Nginx configuration are not
recognized configuration targets in this scan; Bicep compilation, Azure what-if,
`nginx -t`, TLS and authentication tests provide separate evidence.

The proposed Caddy image was rejected before deployment after its own scan
reported 38 HIGH and 1 CRITICAL package findings. Its
[status](azure-proxy-initial-security-status.json),
[scan](azure-proxy-initial-security-scan.json) and
[SBOM](azure-proxy-initial-sbom.cdx.json) remain available as remediation evidence.
