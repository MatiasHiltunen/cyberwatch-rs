# Production size and packaging

The serving image uses a pinned distroless runtime. Its application payload is the
Rust executable, three browser files, and the license. Python, tar, backup tooling,
shells, package managers, source code, tests, and compiler caches are excluded.
The optional maintenance image and the Dev Container have separate build targets
and purposes; neither is an ancestor of the production stage.

## Measured results

Measured on 2026-09-08 with Docker 29.5.2, native Linux ARM64, and Rust 1.88.0.
Both container measurements use the same engine and architecture. The baseline
was rebuilt from the supplied project before this size optimization.

| Metric | Before | Optimized | Reduction |
|---|---:|---:|---:|
| Exported root filesystem, including TAR metadata | 156.37 MiB | 40.89 MiB | 73.85% |
| Docker image `Size` on this containerd image store | 49.34 MiB | 12.11 MiB | 75.45% |
| Linux ARM64 executable | 11.34 MiB | 7.03 MiB | 38.02% |
| Compressed Linux ARM64 application archive | Not previously produced | 3.35 MiB | — |
| Windows ARM64 executable, independently rebuilt | 11.40 MiB | 7.24 MiB | 36.47% |

MiB means 1,048,576 bytes. Docker's `Size` has engine-dependent semantics; do not
compare it with unpacked filesystem size or assume it is registry transfer size.
The exported filesystem measurement provides a consistent uncompressed comparison.
Exact bytes and image identities are retained in [production-size.json](evidence/production-size.json).
These measurements exclude persistent data, build caches and the optional maintenance
image. Linux AMD64 is built and gated by CI; no local AMD64 measurement is claimed.

## Build and export

```sh
docker build --target production -t cyberwatch:local .
python tools/runtime_artifact.py --image cyberwatch:local --output-dir dist
```

The exporter inspects that actual image by immutable local ID, checks its filesystem
and executable architecture, then creates `dist/cyberwatch-rs-linux-<architecture>.tar.gz`,
a SHA256 sidecar and `runtime-size.json`. The archive has exactly five files under
`cyberwatch-rs/`: the executable, `web/index.html`, `web/app.js`, `web/styles.css`, and
`LICENSE`. Gzip uses maximum compression and fixed metadata. Re-exporting identical
payload bytes produces the same archive; this does not claim reproducible compilation.
CI uploads the already compressed archive without another compression pass.

This is a dynamically linked Linux executable for the named architecture. Native
hosts need compatible glibc and libgcc libraries (Debian 12 or compatible), plus CA
certificates for live ingestion. Run from the extracted directory so the default
`./web` resolves, and configure a writable database path. Use the production container
when a packaged OS runtime is needed. The archive cannot run natively on Windows or
on Alpine's musl runtime. `make bundle` produces the separate course **source ZIP**,
including documentation and tests, while excluding runtime archives and build outputs.

## Keep size regressions visible

[runtime_size_policy.json](../tools/runtime_size_policy.json) is enforced in CI and
before publication: at most 48 MiB for Docker `Size` and exported rootfs TAR,
10 MiB for the executable, and 6 MiB for the compressed archive. The filesystem
inspection also fails if common shell, Python, package manager, compiler or source
content appears. These are regression ceilings with headroom for supported
architectures and security updates, not targets to fill.

The release profile uses `opt-level="s"`, full LTO, one code generation unit and
stripped symbols. Unused dependency features and server Brotli/deflate/zstd encoders
were removed; server gzip and identity responses remain supported. Upstream ingestion
retains gzip, deflate, Brotli, HTTP/2 and verified Rustls TLS. Panic unwinding remains
enabled because source adapters rely on panic isolation. The maintained distroless
`cc` base supplies the dynamic runtime without hand-pruning library/package metadata.

`cyberwatch-rs --healthcheck` uses a small bounded TCP probe of `/ready`, without
starting Tokio or loading secrets/database configuration. It reads `BIND_ADDRESS`
from the process environment, maps wildcard listeners to loopback and returns
nonzero for unavailable or unhealthy servers. Docker uses exec-form health checks,
so no shell or curl is needed. Local Docker networking required `--network host`
for dependency downloads during this verification; this host-specific setting is
not stored in the production recipe or required by the application.

See [RELEASE_STATUS.md](../RELEASE_STATUS.md) for executed checks and remaining
hosted/platform verification. Production and maintenance images are scanned and
attested separately, and backup recovery is tested by starting the application on
the restored database before publication.
