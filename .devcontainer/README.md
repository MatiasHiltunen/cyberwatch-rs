# Develop in a container

Install Docker and the VS Code **Dev Containers** extension, open the Cyberwatch
project folder, and run **Dev Containers: Reopen in Container**. Initial setup needs
network access to download the images, system packages, Python dependency and locked
Rust crates. Wait for post-create setup to prepare the private development token
and finish the dependency fetch.

For **Zed**, first verify `docker info` in a host terminal, then use the command
palette **Project: Open Remote** and choose **Connect Dev Container**. Wait for the
initial setup before using the workspace. Port mappings and container environment
changes require recreating the Cyberwatch development container; restarting an
existing one does not apply them. In VS Code use **Dev Containers: Rebuild Container**.
For Zed, recreate it with the Dev Containers CLI from this project directory:

```powershell
npx --yes @devcontainers/cli@0.89.0 up --workspace-folder . --remove-existing-container
```

Recreation discards the container's writable layer, including compiler caches and
editor files in its home directory. Keep work in the mounted project and preserve
any home-directory files you need before recreating. Then reconnect in Zed. See
[Zed's Dev Container instructions](https://zed.dev/docs/dev-containers).

In the container terminal:

```sh
python tools/check.py
cargo run --locked
```

Once `cargo run --locked` reports that the server has started, open
**http://127.0.0.1:8080** in your host browser. Creating or opening the Dev Container
prepares the tools; it does not automatically launch the application. Stop the app
with Ctrl+C and run the command again whenever you need the server.

Docker explicitly publishes `127.0.0.1:8080:8080`, so local browser access works in
Zed, VS Code and the Dev Containers CLI. The server listens on `0.0.0.0:8080` inside
the container, while the published host endpoint is limited to localhost.
`forwardPorts` is deliberately omitted: Zed converts numeric entries into a second
Docker publication without a host-address restriction. See
[Docker port publishing](https://docs.docker.com/engine/network/port-publishing/).

The app uses fictional offline data in the workspace's `data/devcontainer-demo.db`.
Setup creates a random admin token at `/home/vscode/secrets/admin-token` (directory
0700, file 0600) and reuses it on subsequent runs. Only its path is configured through
`ADMIN_TOKEN_FILE`; no token is required to browse the demo. Live refresh is disabled.

If the page is unavailable, run `curl -fsS http://127.0.0.1:8080/ready` inside the
container. A refused connection means the server has not started or has exited;
check the `cargo run` terminal. If the inner request succeeds, inspect `docker port`
on the host: the mapping must show `127.0.0.1:8080`. An empty mapping requires
recreation with the updated configuration. Port 8080 must also be free on the host.

The image includes Rust 1.98.1, the components selected in `rust-toolchain.toml`,
`rust-src`, C/C++ and Clang build tools, Git, Python3 with the project requirements
in `/opt/venv`, and Node24 for JavaScript syntax checks. Rust Analyzer and Python
editor settings are included. Rebuild the container after changing the Dockerfile,
toolchain or Python requirements.

The terminal runs as `vscode`, with UID synchronization on Linux hosts. Rust's
installation, crate cache and build output live under that user's home. Build output
uses `CARGO_TARGET_DIR=/home/vscode/cyberwatch-target`; `tools/check.py` asks Cargo
for the effective directory when locating the smoke-test executable. This avoids
mixing container artifacts with a host's `target/`. Container caches are disposable
and may be lost on rebuild; source files and the workspace database persist.

To work with live ingestion, explicitly choose a separate database:

```sh
DEMO_MODE=false REFRESH_ENABLED=true DATABASE_PATH=./data/devcontainer-live.db cargo run --locked
```

Use the [deployment guide](../deploy/README.md) for host Docker/Compose and cloud
operations. This development environment needs no host Docker socket or privileged
container mode. It is a coding workspace with build tooling; the root Dockerfile
defines the restricted application runtime.

Reference: [Dev Containers configuration](https://containers.dev/implementors/json_reference/)
and [VS Code non-root users](https://code.visualstudio.com/remote/advancedcontainers/add-nonroot-user).

## Docker startup troubleshooting on Windows

If Zed reports `DevContainerUpFailed` / `CommandFailed("docker")`, check the preceding
Zed log entry for the Docker command's stderr. Run `docker info` on the host; its
Server response must succeed before an editor can create a development container.
A Docker API 502 can reflect a stopped or crashed engine.

For the September 8 incident, Docker's VM log recorded disk I/O errors and a daemon
crash at the same instant as Zed's failed container-creation request. Docker's host
logs subsequently identified stale zero-byte IPC sockets that prevented restart.
The recovery preserved those socket directories, recreated their runtime locations,
and restarted Docker. Its existing image and volume data remained available.

Relevant local logs are `%LOCALAPPDATA%\Zed\logs\Zed.log`,
`%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log`, and
`%LOCALAPPDATA%\Docker\log\vm\init.log`. Keep free disk space for image downloads,
build layers and Rust compilation. `cargo clean` from this project removes its
rebuildable native `target` output when that cache is no longer needed.

Docker's supported restart command is `docker desktop restart --timeout 45`.
Inspect failures before taking further recovery actions; the stale IPC repair above
was specific to the paths identified in this incident's logs.
[Docker Desktop CLI reference](https://docs.docker.com/desktop/features/desktop-cli/).
