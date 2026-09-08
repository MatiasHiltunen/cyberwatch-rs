# Current example verification status

Prepared 2026-09-08 from the supplied Cyberwatch source. Original file hashes are retained in [docs/evidence/source-baseline.json](docs/evidence/source-baseline.json). Historical archive assembly checks are not carried forward as validation of this changed version. This is a local example, not a published release or a completed course submission.

| Verification | Actual status |
|---|---|
| Native Rust/API tests | 35 optimized release tests passed on Windows ARM64 using Rust 1.88.0: 25 library, 3 probe unit, 2 real healthcheck CLI and 5 HTTP integration tests |
| Python regression tests | 23 passed: recovery, deployment rollback/provenance boundary, policy, smoke-target isolation and runtime archive safety/determinism |
| Kustomize local/Rahti/maintenance rendering | Rendered successfully; server validation and real cluster behavior not established |
| Source/schema/policy/JavaScript, Rustfmt, Clippy, locked build | Passed; final Clippy run reported no warnings |
| Native-process offline HTTP smoke | 14 requests passed, including pagination, filtering, invalid queries, unknown API, disabled refresh, headers and metrics |
| Compose configurations | Default, live, monitoring and optional maintenance configurations validated |
| Dev Container | JSON, source/package integration and effective Cargo target-directory checks validated; actual Docker context export retains its build inputs. Full development image build/start remains unverified |
| Local Trivy 0.74.0 repository scan | Current HIGH/CRITICAL vulnerability, secret and misconfiguration scan passed; exact report in docs/evidence/source-security-scan.json |
| Production image security scan | Current Linux ARM64 production image passed HIGH/CRITICAL vulnerability and secret scan; exact report in docs/evidence/production-security-scan.json |
| Maintenance image security scan | Pinned Alpine/Python image with reviewed libuuid security update passed HIGH/CRITICAL vulnerability and secret scan; exact report in docs/evidence/maintenance-security-scan.json. Nine recovery regression tests also passed inside this image |
| SBOMs | Current source, production and maintenance inventories are retained as separate CycloneDX documents in docs/evidence/ |
| Docker build/container smoke | Linux ARM64 production built and passed 14 HTTP checks, gzip negotiation, scheduled exec-form healthcheck and missing-listener failure under read-only/non-root restrictions |
| Runtime archive | Exported five-file Linux ARM64 archive passed size/content/ELF gates; extracted binary/web passed 14 HTTP checks and healthcheck from a read-only volume |
| Production size | Rootfs TAR reduced 156.37 to 40.89 MiB; compressed application archive 3.35 MiB. Exact measurements and limits: docs/production-size.md |
| Hosted CI security scans and DAST | Workflows configured, including both image gates and restored-database startup; no hosted run asserted |
| Registry publication, provenance/signature verification | Workflow/design supplied; not executed |
| Cloud deployment, RBAC/egress enforcement, TLS and secret rotation | Manifests/procedures supplied; actual environment evidence pending |
| Local recovery | Real container database backup, checksum/integrity verification, guarded restore, restored startup and unique-marker preservation passed; arbitrary non-root maintenance/restored UID tested |
| Operator recovery and security tabletop | Local technical recovery tested; actual course/platform recovery timing and human tabletop remain pending |
| Reviewed PR, student roles/passport, personal reflection and peer/leadership assessment | Human work pending; templates are not completed evidence |

Run the checked-in entry point on the selected version:

```sh
python -m pip install -r tools/requirements-dev.txt
python tools/check.py
```

`--static` runs the Python/source/policy/browser subset. Docker/hosted checks are defined in [.github/workflows/ci.yml](.github/workflows/ci.yml). Record actual versions, commit, command, outcome and limitations in a [run record](docs/evidence/templates/run-record.md), then select a passing immutable baseline for separate course adoption.

Docker became available during production optimization. Container bridge networking
timed out for build dependencies; the local verification build used `--network host`.
This is an environment workaround, not a production runtime requirement. No cloud
endpoint, effective cluster RBAC/NetworkPolicy, live upstream refresh, delivered
alert, Linux AMD64 execution, or end-to-end hosted pipeline is asserted. Local tests
use synthetic demo data, and vulnerability reports describe their recorded scan time.
