# Docker and Dev Container recovery — 2026-09-08

The supplied Zed error occurred at 12:29:00 +03:00. Its preceding log entry showed
Docker returning HTTP 502 during container creation. At the same instant, Docker's
VM log recorded disk I/O failures, a `dockerd` SIGBUS and shutdown. The subsequent
997 ms Zed foreground-hang report does not by itself explain that engine failure.

## Recovery performed

1. Inspected Zed and Docker logs and verified that the Docker WSL distributions
   were stopped. The host drive had about 5.7 GiB free at diagnosis; the underlying
   cause of the recorded I/O failures was not independently proven.
2. Tried `docker desktop restart --timeout 45`. It timed out waiting for stuck
   Desktop processes; `docker desktop stop --force --timeout 30` stopped them.
3. Subsequent startup logs identified inaccessible stale IPC sockets. Verified
   that `%LOCALAPPDATA%\Docker\run` contained only zero-byte runtime sockets and
   `%LOCALAPPDATA%\docker-secrets-engine` contained only the zero-byte `engine.sock`.
   Direct socket rename failed. With Docker stopped, preserved these directories
   under `.stale-20260908*` sibling names, recreated their original locations and
   started Docker. A failed partial startup recreated a socket, so both locations
   had to be clear together. Image and volume data disks were preserved.
4. Verified Docker Engine 29.5.2 on ARM64 responds successfully. Existing containers
   and volumes remained available. Docker Desktop is 4.75.0 and WSL is 2.7.3.0.
5. Validated both project Dockerfiles with `docker build --check`: no warnings.
6. Checked the actual project's `target` directory was local and not a reparse
   point, then ran `cargo clean --target-dir <project>\target` to provide build
   headroom. This removed generated native build outputs (6,970 files, 2.1 GiB
   logical total); no source, application database or retained evidence was removed.
7. Built and started this workspace using the official Dev Containers CLI:

   ```powershell
   npx --yes @devcontainers/cli@0.89.0 up --workspace-folder . --log-level info
   ```

   The CLI completed with `outcome: success`; `cargo fetch --locked` completed.
   Its preliminary registry metadata lookup emitted a nonfatal tag/digest parsing
   warning; Docker BuildKit correctly resolved the pinned base and built the image.
8. Verified login-shell tools as `vscode` (UID 1000): Rust/Cargo 1.98.1, Rustfmt,
   Clippy, rust-src, Python 3.11.2 and Node 24.20.0. Ran `python tools/check.py --static`
   inside the container: 23 Python tests and source/schema/policy/JavaScript checks
   passed. Both standard workspace labels match Zed's normalized Windows paths,
   and exactly one running container matches them.

## Result and scope

The prepared container is running and ready for Zed's **Project: Open Remote →
Connect Dev Container** from the actual project folder. Zed GUI attachment was not
performed. The full Rust suite previously passed natively under Rust 1.98.1; it was
not repeated inside this container because C: had only about 1.7 GiB free afterward.
Free more disk space before a full compilation. No production image or Azure
runtime was rebuilt or redeployed during this recovery.

Current official [Zed instructions](https://zed.dev/docs/dev-containers) describe the
connection workflow and manual restart after configuration changes. The
[Zed implementation](https://github.com/zed-industries/zed/blob/main/crates/dev_container/src/devcontainer_manifest.rs)
checks both standard workspace labels before building. Docker's supported desktop
commands are documented in the [CLI reference](https://docs.docker.com/desktop/features/desktop-cli/).

Local detailed logs are retained under `reports/` and excluded from source packaging:

- `devcontainer-up.log` — SHA256 `6a9ddef94f29b5465d3913a139968858c153472e016d1bdd605965bf03c8a07d`.
- `devcontainer-static-check.log` — SHA256 `9344627d4ed98d3ed3624894f0b8f8e746da3ab42378650a77b4c8cf433e1f3c`.
- `devcontainer-docker-check.log` — SHA256 `488b0d642662e2840f1e8ef3a2224855202633efef84c270b2f59ab24c3703ee`.
- `production-docker-check-after-recovery.log` — SHA256 `4253bc5536fa5c0c4e38c5a3506e6e0b9d0d401e8a86d68d3685650b9afedb34`.

Container ID: `f578003a7826e3d40a9ab8493c03b65ebc92d9dcb09a9da962400d8d1c3436c7`.
Image ID: `sha256:10cf0b8959378b1943b8ec99c018d25d8a49d3c30e5949ff10b500fda8d8027a`.

Follow-up: [local browser access repair](devcontainer-local-access.md) recreated the container with explicit localhost publishing, preserved its development home, and verified the running application from Windows. Its newer container ID supersedes the one recorded above.
