# Develop in a container

Install Docker and the VS Code **Dev Containers** extension, open the Cyberwatch
project folder, and run **Dev Containers: Reopen in Container**. Initial setup needs
network access to download the images, system packages, Python dependency and locked
Rust crates. Wait for the post-create dependency fetch to finish.

In the container terminal:

```sh
python tools/check.py
cargo run --locked
```

Open the forwarded port8080 from VS Code's **Ports** panel. The app starts in offline
demo mode, bound to loopback, with fictional data in `data/devcontainer-demo.db`.
The source folder and demo data are backed by the opened workspace. The forwarded
port is restricted to localhost in local VS Code; Codespaces forwarding is private
by default. Stop the app with Ctrl+C.

The image includes Rust1.88.0, the components selected in `rust-toolchain.toml`,
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
