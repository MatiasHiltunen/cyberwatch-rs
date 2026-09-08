# Identity, permissions, and secret lifecycle

This is the intended access model for the example. Workflow permissions and deployment manifests can be inspected locally; repository rules, effective cluster permissions, secret encryption settings and denial tests require an actual configured environment.

| Principal | Needed access | Unneeded/denied access | Verification |
|---|---|---|---|
| Reader | GET dashboard/public intelligence and permitted health views | Refresh mutation, token or database access | Unauthenticated mutation rejected in live public configuration |
| Refresh administrator | POST refresh with a configured long random token; read status | Shell, registry push, cluster API | Incorrect token denied; legitimate refresh accepted/coalesced; demo refresh remains disabled |
| PR check runner | Read selected source and run tests/scans | Package publish, cloud deploy, production secrets | Inspect `permissions`; test untrusted contribution without exposing release credentials |
| Release job | Read source; explicitly declared package/attestation/OIDC rights needed by publisher | Broad repository writes, unrelated repositories, cloud administrator | Gate must pass; inspect job-scoped rights and release context; verify exact image digest |
| Platform bootstrap operator | Create the selected application/secret/storage and scoped deployer role in the assigned namespace | Unrelated course resources | Inspect rendered resources and actual authorization before initial apply |
| Automated deployer | Patch the existing named application Deployment and inspect rollout using [scoped RBAC](../../deploy/rbac/deployer.yaml) | Create arbitrary workloads, read Secrets, delete storage, other namespaces or cluster-admin | Use `kubectl auth can-i` for required patch and denied create/secret/cross-namespace actions with the actual identity |
| Application service account | Application runtime; mounted data and explicitly provisioned secret | Kubernetes API credentials or cluster mutation | Service-account token automount disabled; no unnecessary RoleBinding; inspect effective pod |
| Backup operator | Selected volume/backup directory; controlled maintenance workload | Other projects' volumes or unredacted public artifact upload | Restore only disposable/new destination with app stopped and verified backup |

Do not run a broad cluster administrator denial test and call it least-privilege evidence. Test the identity the automation will actually use. A role that can create arbitrary pods may indirectly access namespace secrets; restricting `get secrets` alone is incomplete isolation.

The [deployment workflow](../../.github/workflows/deploy.yml) runs explicitly on `main` in `course-staging`, verifies the requested digest's provenance, and uses a configured namespace-scoped credential to update the existing application. Its environment secret/namespace variable, required human reviewer and branch protections must be configured by the operator; YAML does not create host-side approvals. Restrict credential lifetime and rotate it. The deployer's ability to patch the approved Deployment still permits changing its image/configuration, so it remains a sensitive capability even without direct Secret reads.

## Application secrets

`ADMIN_TOKEN` protects manual refresh; `NVD_API_KEY` and `GITHUB_TOKEN` are optional upstream credentials. Their `_FILE` counterparts support injected secret files. Do not set both the value and file form of the same secret. Every non-loopback bind, including container demo mode, requires an administrator token of at least 32 bytes; generate cryptographically random content, rather than meeting the length rule with a predictable phrase. Local loopback convenience behavior is not a network authorization boundary.

Configuration Debug output redacts secret values. Source transport errors should omit credential-bearing URL paths/query/body. These controls reduce disclosure; check actual logs, tooling and deployment events before exporting them as evidence. Do not put tokens in a URL, command history, screenshots, fixture data, SBOM annotations or portfolio text.

The default Compose demo needs no upstream credentials and disables refresh, but still mounts an administrator token because the process binds the container network. Follow [deploy/README.md](../../deploy/README.md), which provisions the token from the operator's excluded `secrets/` directory and separates demo/live data volumes. In a cluster provision secrets outside Git and mount only into the relevant container. Kubernetes Secret data is base64-encoded, not intrinsically encrypted; configure appropriate storage encryption and tightly control namespace access. [Kubernetes Secrets documentation](https://kubernetes.io/docs/concepts/configuration/secret/).

## Lifecycle exercise

1. **Create:** choose owner, purpose, scope and expiry; generate a test-only value with a trusted cryptographic generator; provision through the actual secret mechanism without printing it. Record a non-secret reference such as “refresh credential revision B”.
2. **Use:** start live mode in the owned isolated lab; prove authorized refresh and incorrect/missing-token denial. Capture status codes without request credentials.
3. **Rotate:** replace the secret, restart the application so configuration is reloaded, and verify the new value works and the old one is rejected. The application reads secret files at startup; replacing a file alone does not prove rotation took effect.
4. **Revoke after suspected leak:** disable the issuing credential where applicable, stop unauthorized refresh exposure, replace affected deployment secret and sessions, audit the time window, then rebuild/redeploy if build identity was affected. Removing a leaked value from Git is not revocation.
5. **Retire:** remove the course's secret and runtime resources at expiry, following retention requirements for redacted evidence. Do not delete another course's resources.

Record actual operator, date, commit, namespace, status codes, old-value denial and residual risk in [run-record.md](../evidence/templates/run-record.md). The steps are an unperformed exercise until that record exists.

## Boundaries still needing an operator

TLS/user access control belongs at the selected platform ingress for a network deployment. Metrics and source diagnostics can reveal operating details and should remain on a restricted surface. Validate the cluster's restricted pod settings, storage class/permissions, admission controls, egress and quota. The code's source destination and redirect checks are defense in depth; confirm actual network enforcement, including DNS behavior, before broader live exposure.
