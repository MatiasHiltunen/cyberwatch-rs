# Rust 1.98.1 upgrade verification

Recorded 2026-09-08 for the user-requested workspace upgrade from Rust 1.88.0.
This is a working-tree verification, not a published or deployed release.

Rust 1.98.1 was verified against `rustup check` and the
[official September 3 release](https://blog.rust-lang.org/2026/09/03/Rust-1.98.1/).
The repository selects `1.98.1`; Cargo's minimum supported version is now also
`1.98.1`. Rustfmt, Clippy and `rust-src` are included. `Cargo.lock` is unchanged.

## Procedure and results

From the project directory on Windows ARM64:

```powershell
rustup toolchain install 1.98.1 --profile minimal --component rustfmt --component clippy --component rust-src
rustup show active-toolchain
rustc --version
cargo --version
# Reduce disposable test/debug build storage; release settings are unchanged.
$env:CARGO_INCREMENTAL = '0'
$env:CARGO_PROFILE_DEV_DEBUG = '0'
$env:CARGO_PROFILE_TEST_DEBUG = '0'
$env:LIBCLANG_PATH = 'C:\Program Files\LLVM\bin'
python tools/check.py
```

- Selected compiler: `rustc 1.98.1 (48a229cea 2026-09-01)`, host `aarch64-pc-windows-msvc`.
- Cargo: `1.98.1 (797e8a9bc 2026-08-05)`.
- Full check entry point exited 0: source/schema checks, 23 Python tests,
  deployment/workflow policy, JavaScript syntax, Rustfmt, Clippy correctness gate,
  35 Rust tests (25 library, 3 probe unit, 2 healthcheck CLI, 5 HTTP integration),
  locked native build and 14 offline HTTP smoke requests passed.
- Clippy emitted six `collapsible_if` style suggestions; no correctness errors.
  These suggestions were not suppressed or represented as a warning-free run.
- Native log is retained locally at `reports/rust-1.98.1-check.log` (excluded from source packaging).
- Cross-file checks confirmed the manifest, toolchain, CI and both Dockerfiles
  select compiler 1.98.1. Release optimization settings, size limits and production
  runtime stages remain unchanged.

## Container verification scope

Docker Hub did not yet publish `rust:1.98.1-bookworm` (registry returned
`404 MANIFEST_UNKNOWN`). Both Dockerfiles bootstrap from the verified official
`rust:1.98.0-bookworm@sha256:82150a52ec202c1b14d7817e14516c392bb7f5cfebd88f1ed531cb37ebd39922`.
Its index contains Linux AMD64 and ARM64/v8. Registry content digest and the SHA256
of the raw manifest matched. Recheck with:

```sh
docker buildx imagetools inspect docker.io/library/rust:1.98.0-bookworm
```

Production explicitly installs the minimal 1.98.1 toolchain and invokes
`cargo +1.98.1`. The Dev Container installs the version and editor components in
the copied `rust-toolchain.toml`. Keeping Bookworm preserves compatibility with
the Debian 12 distroless runtime. Build tooling stays outside the production image.

`docker build --check .` could not execute: the daemon returned
`Docker Desktop is unable to start`. Full production and Dev Container builds,
updated image scans and Linux artifact size measurements were therefore not run
for this upgrade. Run the existing CI container gates before publishing it.
Earlier Rust 1.88.0 measurements and scan reports remain historical evidence;
the existing Azure runtime was not redeployed by this workspace upgrade.

In VS Code, use **Rust Analyzer: Restart server** or **Developer: Reload Window**
if the previous compiler warning is cached. Rebuild an existing Dev Container with
**Dev Containers: Rebuild Container**.

Check log SHA256: `7e309bdffa8ff613570278f954b8b23489e25e0bd492a5db2a4067bc9412e89b`.

Follow-up: [Docker recovery and Dev Container verification](devcontainer-recovery.md) subsequently completed both Dockerfile checks and a real development image build/start. The production image still has not been rebuilt for this compiler upgrade.
