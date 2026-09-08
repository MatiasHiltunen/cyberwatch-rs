# Security policy

Cyberwatch is a public-intelligence example with an isolated offline demonstration mode. Its controls and limits are documented in the [threat model](docs/security/threat-model.md), [risk register](docs/security/risk-register.md), [findings/gates](docs/security/findings.md), [identity/secret model](docs/security/identity-and-secrets.md), and [supply-chain analysis](docs/security/supply-chain.md).

Keep the default loopback listener for local native use. Every non-loopback bind, including container demo mode, requires a strong administrator token of at least 32 bytes. Prefer injected `ADMIN_TOKEN_FILE`; never commit credentials. Network deployment also requires trusted TLS termination, user access controls and restricted operational endpoints. API refresh authorization does not provide dashboard user authentication.

Public feed content is untrusted. The application bounds responses, requests and ingestion, validates public destinations/redirects/resolved addresses, redacts outbound diagnostic details, validates adapter output, and safely renders browser content. Preserve these boundaries when adding sources. Platform egress restrictions remain necessary defense in depth; configuration tests do not prove a cluster enforces them.

Use one application replica with the embedded database, a persistent volume and verified database-aware backups. Follow [deployment/recovery instructions](deploy/README.md); test restore on disposable data and review schema compatibility before rollback. Protect backup and evidence access as carefully as source configuration.

Security checks and local tests are distinct from a penetration test or a production approval. Consult [RELEASE_STATUS.md](RELEASE_STATUS.md) for checks actually performed and unavailable verification. Test only a target you own or are explicitly authorized to test; default DAST exercises target the local synthetic demo.

Report vulnerabilities privately to the repository's actual maintainer or its configured private advisory channel. Include affected commit/version, a minimal safe reproduction, expected/observed behavior and impact. Do not include credentials, private source URLs, database contents or personal data in a public report. No response SLA or security contact identity is invented by this example. If a secret leaks, revoke/rotate it; deleting it from a file is insufficient.
