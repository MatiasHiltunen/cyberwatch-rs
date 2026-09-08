# Dev Container local browser access — 2026-09-08

Initial inspection found no running Cyberwatch process or port 8080 listener inside
the development container. Both the container and Windows health requests failed.
Docker inspection showed no published ports. Its configuration also bound the app
to the container's loopback address, so adding a Docker mapping alone was insufficient.

## Change and verification

- Configured `runArgs` with `--publish 127.0.0.1:8080:8080` and the app's internal
  `BIND_ADDRESS=0.0.0.0:8080`. Removed `forwardPorts`: Zed treats numeric entries as
  Docker publications, while the Dev Containers CLI does not create an editor tunnel.
  One explicit host-loopback publication works with either editor.
- Added idempotent `.devcontainer/post-create.py`: prepare a private development
  admin token under `/home/vscode/secrets/admin-token`, then fetch locked Cargo
  dependencies. The app requires a token for a non-loopback internal bind. Only
  the token file path appears in configuration; the secret is never printed.
- Preserved the original container filesystem as the local image
  `cyberwatch-devcontainer:before-port-fix-20260908`
  (`sha256:86bd326e5a029a67da281bb270eb51af4ac32b1c5895fe4339bc4b1f2f21d00f`).
  Recreated the project container with the new mapping and restored its complete
  `vscode` home, including compiler caches and editor files. The source and demo
  database are in the host-mounted project. The snapshot remains local and is not
  a distribution or production image.
- Post-create setup completed. Isolated temporary-file checks verified creation,
  reuse without rotation, 0700/0600 permissions, weak/oversized-token rejection and
  refusal to follow a token symlink. The existing 23 Python regressions and project
  source/schema/policy/JavaScript checks passed.
- Started `cargo run --locked` as `vscode`; the preserved build was reused in 0.32 s.
  The app logged `0.0.0.0:8080` and Windows received HTTP 200 from `/health`.
- All 14 HTTP smoke checks passed **from Windows** through the Docker publication;
  see [devcontainer-local-http.json](devcontainer-local-http.json). `docker port`
  reports exactly `127.0.0.1:8080`.

The server is running at **http://127.0.0.1:8080** in offline demo mode. Reconnect
Zed after the container recreation. Creating or opening the development container
prepares tools; future server starts still use `cargo run --locked` in its terminal.

For this verification the server was started in the background. Its log is
`/tmp/cyberwatch-dev-server.log` inside the container. To take over in a foreground
terminal, stop that process with `pkill -TERM -x cyberwatch-rs`, then run
`cargo run --locked`. A stopped/restarted container also needs the server started again.

No Azure deployment or production image was changed.

Recreated container ID: `0d914bae07a3a40622daac1ee1f204f4c8f6ea2dc29503c5f5c25ae4a9388ae8`.
