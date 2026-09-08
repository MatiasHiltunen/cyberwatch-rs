# Supply-chain evidence and signing design

The supply chain includes Rust crates resolved by `Cargo.lock`, native/transitive libraries, builder/runtime container images, CI actions and downloaded scanner tools, browser source shipped in the image, the registry, and the chosen deployment digest. It also depends on the integrity of the build worker and the person authorizing release.

Production uses a pinned distroless image with a stripped Rust executable, dashboard assets, and license. Python backup/restore tooling is delivered in a separate pinned maintenance image; the Dev Container has its own build and compiler cache. Each image has different dependencies and must be assessed independently. Size optimization retains Rust panic unwinding and the server's source-failure isolation; the built-in readiness probe removes the need to ship an HTTP command-line client.

## Five risks and decisions

| Risk | Example failure | Control and remaining limitation |
|---|---|---|
| Dependency substitution/compromise (R06) | A legitimate-looking crate update adds malicious behavior | Review lockfile changes and registry origin, use locked builds and dependency analysis. An unchanged lockfile does not prove a dependency benign |
| Mutable base/tool reference (R06) | A reused image/action/tool tag points to different content | Prefer immutable references and review updates; where a tag/version remains, record it as drift exposure and capture resolved build digest. Do not claim fully reproducible builds |
| Privileged build compromise (R03) | Untrusted PR code receives publication rights | Read-only PR context, explicit release permissions and host protections. A compromised trusted runner can still produce a malicious artifact |
| Registry/tag or deployment substitution (R03) | An operator deploys a tag that now points elsewhere | Deploy selected digest and verify provenance identity. A checksum without expected identity does not establish who built it |
| Stale/incomplete security evidence (R06/R11) | A clean old scan or unrelated SBOM is shown for a new image | Retain commit, digest, tool/database version, time, report and outcome together; rescan for release. Scanners cannot establish absence of unknown vulnerabilities |

## What the evidence establishes

| Artifact | Establishes | Does not establish |
|---|---|---|
| `Cargo.lock` / dependency list | Resolved component identities and versions represented by the build inputs | That every component is safe, or that native/runtime components were inventoried |
| SBOM for the selected image | Machine-readable component inventory to the generating tool's coverage | Exploitability, license approval, freshness, or malicious-code absence |
| Vulnerability scan | Matching findings known to the scanner/database under its settings at that time | Complete detection, reachable exploit paths, or safety after database changes |
| Image digest | Identity of particular image bytes | Trust in publisher or source review |
| Runtime archive, checksum, and size report | Identity and measured size of the allowlisted executable/dashboard/license payload exported from the selected image; executable architecture validation | A self-contained operating system runtime, or evidence about components supplied by the host |
| Signed provenance / attestation | Verifiable claims tying artifact identity to build/repository identity | That source, workflow or runner is uncompromised or behavior is acceptable |

## Release evidence procedure

Run the [CI gate](../../.github/workflows/ci.yml) on the selected reviewed commit. It scans production and maintenance images, exercises the built-in readiness check and recovery workflow, and enforces [runtime size/content limits](../../tools/runtime_size_policy.json). The runtime exporter validates Linux amd64/arm64 ELF identity and packages only the executable, dashboard assets, and license. These dynamically linked archives need compatible host glibc/libgcc; source, course documents, tests, and backup tooling are excluded. See [production size](../production-size.md) for measurements and compatibility details.

The [release workflow](../../.github/workflows/release.yml) builds Linux amd64 candidates, exports the runtime archive from the production candidate, and scans and tests the exact images before publication. It publishes production and maintenance images with separate immutable references, SBOMs, and provenance attestations, and separately attests the runtime archive. Keep source commit, workflow/run identity, build time, each image digest, archive checksum/size report, inventory, scan output, attestation output, and the deployment's selected digest together. A workflow file alone is not generated provenance or an executed signing experiment.

The included attestation design uses GitHub's workload identity/attestation mechanism in the restricted publication context. GitHub documents the required `id-token`, `attestations`, and container publication permissions as well as verification using `gh attestation verify` against the intended repository. Feature availability depends on repository visibility and account plan; confirm it before selecting this mechanism. [GitHub artifact attestation guide](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).

For a real verification, use the published OCI image's immutable digest and explicitly constrain the expected repository. Inspect the verified subject digest and workflow/source identity, and retain the redacted verifier output. As an adverse test, a different image digest or wrong expected repository must not satisfy the same identity claim. Do not weaken expected identity checks merely to make a demonstration green.

Verify the maintenance image against its own subject digest and the downloaded runtime archive against its own file attestation and checksum. Production image provenance does not automatically verify a sibling image or archive. A changed size budget requires review; lowering artifact size does not replace vulnerability scanning or recovery tests.

If the chosen hosting account cannot produce attestations, document that limitation and a concrete alternative signing/verification design before publication. YAMK283 T5 permits a signing design instead of a completed experiment; label the status honestly. This example does not claim that any image has been published or its signature verified.

Keep raw scan artifacts access-controlled if they contain private paths or environment references. Record failed scans as failed; do not substitute a generated empty JSON document for missing evidence.
