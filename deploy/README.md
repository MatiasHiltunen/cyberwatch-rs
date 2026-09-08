# Container, Kubernetes and CSC Rahti operations

This is a reproducible single-instance teaching deployment. It is not highly
available: updates and recovery intentionally cause a short outage. SQLite lives
on one persistent volume; the Deployment must stay at **one replica, Recreate**.
ReadWriteOnce restricts nodes, not processes. Never add an HPA, a second writer,
or a rolling update around this database. Use a client/server database before
scaling the application horizontally.

## Local container

From the project root, with Docker Engine and Compose v2:

```sh
python tools/create_admin_secret.py
docker compose config --quiet
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:8080/ready
```

The default is a deterministic offline demo on loopback port 8080, with a named
data volume. Build dependencies still need internet access. The process is UID
10001, has no Linux capabilities, cannot gain privileges, and has a read-only
root filesystem. Only `/app/data` and bounded `/tmp` are writable. Compose sets
1 CPU, 768 MiB RAM, 128 PIDs and rotating logs. Health checks use database
readiness; the process handles SIGTERM with a 30-second shutdown allowance.

The default production image contains the stripped Rust program, three static
dashboard files and its small Debian 12 distroless runtime. It has no shell,
Python, curl, tar, package manager or compiler. Its exec-form health check runs
`cyberwatch-rs --healthcheck`; Kubernetes continues to use HTTP probes. A separate
`maintenance` build target provides Python and tar for controlled volume recovery.
The Dev Container remains a full development workspace and is not a release image.

The first command creates an untracked secret file, refuses to replace an
existing token and does not print it. Keep the existing file on subsequent runs.
Even offline mode needs a token because the server binds the container network.
For live ingestion, stop the demo container and use a separate Compose project:

```sh
docker compose down
docker compose -p cyberwatch-live -f docker-compose.yml -f deploy/compose.live.yml config --quiet
docker compose -p cyberwatch-live -f docker-compose.yml -f deploy/compose.live.yml up --build -d
```

Restrict `secrets/` to your account with the host filesystem ACLs. Local Compose
secrets are mounted files, not an encrypted secret store. On Unix the helper
sets the directory to 0700 and the file to 0644: the private parent protects the
host token while the container's different non-root UID can read the mounted
file. [File-backed Compose secrets do not remap UID/mode](https://docs.docker.com/reference/compose-file/services/#secrets). Both modes
mount `/run/secrets/admin-token` and set `ADMIN_TOKEN_FILE`; no token value is
committed or placed in container arguments. Keep using the same pair of Compose
files and `-p cyberwatch-live` for subsequent live operations. Its named volume is
separate from the demo. The application refuses to use a demo database in live
mode or seed demo data into an existing live database.

## Build once, deploy the reviewed image

The Docker build copies Cargo.lock and uses `cargo build --release --locked`.
Rust, distroless runtime and maintenance base defaults are pinned by registry
digest. Review updates to `RUST_IMAGE`, `RUNTIME_IMAGE` and `MAINTENANCE_IMAGE`
regularly, rebuild, scan and record the resulting image digests. The Rust builder
and runtime both use Debian 12; changing the runtime must preserve the binary's
glibc and shared-library requirements. The [distroless image documentation](https://github.com/GoogleContainerTools/distroless)
describes supported tags and signature verification. The maintenance base is the
official Python slim image on Debian 12; no OS packages are downloaded during
this project's build. Pins and lockfiles constrain inputs but are not a promise
of bit-identical compiler output. CI scans the two built images and produces
their SBOM/provenance.

Rahti needs a `linux/amd64` image. ARM laptops must cross-build or use the AMD64
CI runner. Build and inspect locally, then publish through the release workflow:

```sh
docker buildx build --platform linux/amd64 --load -t cyberwatch-rs:local .
docker buildx build --platform linux/amd64 --target maintenance --load -t cyberwatch-rs-maintenance:local .
docker image inspect cyberwatch-rs:local
```

The default target is `production`. Python recovery tools are built only by the
explicit `maintenance` target, which is independent of the application builder.
The `artifacts` target exports only the application binary, `web/` and `LICENSE`:

```sh
docker buildx build --platform linux/amd64 --target artifacts --output type=local,dest=dist/runtime-linux-amd64 .
```

This native artifact needs compatible Debian 12/glibc runtime libraries; the
container supplies them. Keep production archives separate from the source ZIP
and Dev Container. `.dockerignore` admits only build inputs, including the two
files the Dev Container copies; databases, secrets, caches and evidence never
enter the build context.

Before applying either overlay, add a real registry image and digest to its
`kustomization.yaml` (or use standalone `kustomize edit set image` in that
directory). Replace the placeholders with the digest from the reviewed release:

```yaml
images:
  - name: cyberwatch-rs
    newName: ghcr.io/YOUR-OWNER/cyberwatch-rs
    digest: sha256:YOUR-64-HEX-DIGEST
```

The committed `cyberwatch-rs:local` is only for a local loaded image, not a remote
release. A private registry also needs a pull secret attached to the
`cyberwatch` service account. Do not give the application registry push or
Kubernetes API credentials. Workload service account token automount is disabled.

The release also produces a separate `cyberwatch-rs-maintenance` image from the
same commit. Record its **own digest** alongside the server digest; they are
different images. Set it in `deploy/maintenance/base/kustomization.yaml` before
remote backup or restore. With Kind, load both local images. For registry-backed
Compose recovery set `MAINTENANCE_IMAGE=REGISTRY/cyberwatch-rs-maintenance@sha256:DIGEST`
and use the reviewed image without a local rebuild.

## Portable Kubernetes

Prerequisites: `kubectl`, a dedicated disposable namespace, a NetworkPolicy
enforcing CNI, and a block-backed CSI storage class that supports RWO volumes.
Docker Desktop and some default local clusters do not enforce NetworkPolicy;
rendering YAML is not proof of network isolation. Do not use NFS for SQLite WAL.
The local overlay sets UID 10001 and fsGroup 10001 for PVC and Secret access.

These commands use a dedicated `cyberwatch-example` namespace and an already
created secret file; they do not require a cluster-admin workload:

```sh
kubectl create namespace cyberwatch-example
kubectl -n cyberwatch-example create secret generic cyberwatch-admin --from-file=admin-token=secrets/admin-token
kubectl kustomize deploy/overlays/local
kubectl -n cyberwatch-example apply --dry-run=server -k deploy/overlays/local
kubectl -n cyberwatch-example apply -k deploy/overlays/local
kubectl -n cyberwatch-example rollout status deployment/cyberwatch --timeout=300s
kubectl -n cyberwatch-example port-forward service/cyberwatch 8080:8080
```

On Kind, first load the local image with `kind load docker-image
cyberwatch-rs:local`. With another cluster, set the immutable registry image.
There is no public Ingress in the portable overlay. Port-forward binds localhost;
verify `/health`, `/ready`, `/api/v1/stats`, and the dashboard in another terminal.
If you add an ingress controller, allow only its namespace/pod labels in the
NetworkPolicy, configure HTTPS and verify the certificate.

## CSC Rahti

First obtain an eligible CSC account/project, enable Rahti access and a billing
allocation through your institution, install `oc`, and log in using the command
shown by the Rahti console. Create a **dedicated Rahti project** through the
supported CSC project process. Choose a `cyberwatch-*` project name if using the
provided CI deployment workflow. Do not apply this namespace-wide quota in a
shared course project. Follow the current [CSC access instructions](https://docs.csc.fi/cloud/rahti/get-started/access/).

```sh
oc project YOUR-DEDICATED-RAHTI-PROJECT
oc get quota,limitrange,networkpolicy
oc get storageclass
oc create secret generic cyberwatch-admin --from-file=admin-token=secrets/admin-token
oc kustomize deploy/overlays/rahti
oc apply --dry-run=server -k deploy/overlays/rahti
oc apply -k deploy/overlays/rahti
oc rollout status deployment/cyberwatch --timeout=300s
oc get route cyberwatch
oc get deployment,pod,service,pvc,quota
```

Replace the image with an immutable digest before these commands. The Rahti
overlay requests `standard-csi`, documented as Rahti's RWO storage class; check
availability before applying. OpenShift assigns a non-root UID and allowed volume
group through its restricted security context constraints; the overlay does not
request a fixed UID, privileged SCC, root init container, or cluster role.
The image's data directory is group 0 writable for arbitrary UIDs. Confirm the
actual UID, fsGroup and mounted-file access after admission. [CSC storage](https://docs.csc.fi/cloud/rahti/usage/storage/persistent/)
and [OpenShift image guidelines](https://docs.openshift.com/container-platform/4.18/openshift_images/create-images.html).

The Route asks the cluster to allocate a unique hostname and uses edge TLS with
HTTP-to-HTTPS redirect. Check the allocated host and its valid router certificate
before using an admin token. Edge TLS encrypts client-to-router traffic; the
router-to-pod hop is HTTP. An environment requiring TLS on that hop needs a TLS
proxy/backend and a re-encrypt Route. Custom domains require their own DNS and
certificate configuration. [CSC networking](https://docs.csc.fi/cloud/rahti/usage/networking/).

The base ConfigMap defaults to `DEMO_MODE=true` for assessment. To use live data,
bootstrap a separate dedicated project/namespace and fresh PVC, and add this
generator to the environment overlay; Kustomize changes the config hash
and performs a Recreate rollout:

```yaml
configMapGenerator:
  - name: cyberwatch-config
    behavior: merge
    literals:
      - DEMO_MODE=false
```

## Scoped CI deployment identity

An operator bootstraps the application, PVC, Secret, policies and Route once.
Then apply `deploy/rbac/deployer.yaml` in that same dedicated namespace:

```sh
oc apply -f deploy/rbac/deployer.yaml
oc --kubeconfig=PATH-TO-SCOPED-KUBECONFIG auth can-i patch deployment/cyberwatch
oc --kubeconfig=PATH-TO-SCOPED-KUBECONFIG auth can-i get secrets
```

The first permission should be allowed and Secret reads denied. The namespace
Role can patch only the existing `cyberwatch` Deployment and read rollout status,
pods, ReplicaSets and events. It cannot create Deployments, delete PVCs, read
Secrets or administer the cluster. Patching a Deployment is still powerful: the
deployer could substitute code that reads its mounted admin secret. Keep the
GitHub deployment environment protected with reviewers and branch restrictions.

Supply a **short-lived namespace-scoped kubeconfig** as the protected GitHub
environment (`course-staging`) secret `KUBE_CONFIG_B64`, with the correct cluster
CA and namespace. Set its `KUBE_NAMESPACE` variable to that `cyberwatch-*` namespace.
Have the operator or an approved federation broker mint the credential only for
the deployment window; do not commit a kubeconfig, reuse a personal cluster-admin
token, or create a permanent service-account-token Secret. Base64 is encoding,
not encryption. The application service account is a different identity and
continues to have no API token mounted. The manual deployment workflow verifies
the selected immutable image's attestation and updates the existing Deployment;
it does not bootstrap infrastructure or need `apply` permissions. Keep the
environment overlay's image digest in version control consistent with that
release. RBAC does not expire itself: revoke RoleBinding access and remove the
GitHub environment credential when the exercise ends.

## Network and resource boundaries to verify

The policy allows port 8080 from explicitly labeled local clients; Rahti also
allows its ingress-router namespace. DNS is restricted to the cluster DNS pods
(53, and OpenShift's translated 5353). Outbound public IPv4 HTTPS is allowed;
private, loopback, link-local/metadata, multicast and reserved ranges are excluded.
IPv6 and outbound HTTP are denied. Live source redirects to HTTP will fail.
This is an IP/port boundary, not a domain allowlist; approved public HTTPS sites
are not distinguished at this layer. If strict domain egress is required, add an
audited egress proxy/CNI FQDN policy. Application URL validation adds another layer.

**NetworkPolicies are additive.** Inspect provider-created policies: a broader
same-namespace or egress allow policy can defeat this boundary. Reconcile those
only in your dedicated project, preserving the provider's router/DNS requirements.
Confirm DNS labels/ports and any public cluster/node CIDRs with the operator;
add those CIDRs to the HTTPS exclusions if the cluster uses public internal IPs.
Node-local/host-network traffic and Service NAT vary by CNI and require an actual
cluster test. See [Kubernetes NetworkPolicy behavior](https://kubernetes.io/docs/concepts/services-networking/network-policies/).

Capture actual acceptance evidence, not only manifest screenshots:

1. `/ready` responds, the dashboard renders, and an unauthenticated refresh is denied.
2. Inspect the admitted Pod's `securityContext`, volume mounts and numeric
   `runAsUser`: it must be non-root, use a read-only root filesystem and have no
   service-account token. Confirm database writes/restarts on the data volume.
   The server has no `id` or shell; use an operator-approved diagnostic workload
   for additional filesystem inspection, never add debugging tools to production.
3. DNS and public HTTPS work in live mode; a request to a **controlled** private
   HTTPS test service is denied. Test both an authorized and unauthorized client
   pod against port 8080. Do not probe metadata services or unrelated targets.
4. Restart the Deployment, verify persisted row counts, and time readiness return.
5. Record requests/limits, actual usage and PVC growth. The application requests
   100m CPU/256 MiB, capped at 1 CPU/768 MiB; quota caps namespace pods at 3,
   aggregate limits at 2 CPU/2 GiB and storage at 2 GiB. These are example budgets,
   not measured capacity guarantees. Reduce concurrency or increase budgets based
   on measured data ingestion, memory peaks and quota availability.

## Online backup and local recovery drill

`tools/backup.py` uses SQLite's online backup API, which captures committed WAL
data into a consistent standalone database. It runs full integrity and foreign
key checks, flushes the snapshot, then atomically publishes without overwriting.
It emits JSON containing bytes, elapsed time and SHA-256 for evidence. A failed
copy is not published. The destination must be on a filesystem supporting hard
links and in an existing, operator-owned directory. Symlinks/junctions and stale
destination WAL files are rejected. [SQLite backup API](https://www.sqlite.org/backup.html).

```sh
python -m unittest discover -s tools -p test_backup.py -v
mkdir backups
python tools/backup.py backup data/cyberwatch.db backups/drill-001.db
python tools/backup.py verify backups/drill-001.db
```

For a native app, stop all writers, then restore into a new database filename and
restart with `DATABASE_PATH` pointing to it:

```sh
python tools/backup.py restore backups/drill-001.db data/restored-001.db --app-stopped
```

`--app-stopped` is an operator acknowledgement, not process detection. Restore
never replaces a file, even with that flag. Keep the previous database and its
sidecars untouched until the recovery is accepted. Compare persisted records and
row counts, verify readiness and run the smoke test; measure RTO and backup age
(RPO). A successful SQLite integrity check alone does not prove application recovery.

For Compose, use the separate maintenance image. Stop the application first so
the same procedure also works with an exclusively attached cloud volume. These
commands use a unique disposable container name; preserve the same `-p` and all
live override files on every Compose command when operating a live project:

```sh
docker compose -f docker-compose.yml -f deploy/compose.maintenance.yml build maintenance
docker compose stop cyberwatch
docker compose -f docker-compose.yml -f deploy/compose.maintenance.yml run --no-deps -d --name cyberwatch-maintenance-drill-001 --entrypoint python3 maintenance -c "import time; time.sleep(3600)"
docker exec cyberwatch-maintenance-drill-001 python3 /app/tools/backup.py backup /app/data/cyberwatch.db /app/data/drill-001.db
docker cp cyberwatch-maintenance-drill-001:/app/data/drill-001.db backups/drill-001.db
python tools/backup.py verify backups/drill-001.db
```

If only taking a backup, stop/remove the maintenance container below and restart
the server. For the recovery drill, with the server still stopped:

```sh
docker exec cyberwatch-maintenance-drill-001 python3 /app/tools/backup.py restore /app/data/drill-001.db /app/data/restored-001.db --app-stopped
docker stop cyberwatch-maintenance-drill-001
docker rm cyberwatch-maintenance-drill-001
```

Set `DATABASE_PATH=/app/data/restored-001.db` in the local `.env`, then run
`docker compose up -d`. For a backup-only operation, keep the original database
path. When recovering an off-volume backup, use `docker cp` to a unique
`/app/data/incoming-001.db` in the maintenance container and restore from that
path. Do not overwrite an existing database with `docker cp`. Maintenance has no
network or admin secret and exits after one hour if the operator loses the session.
Copy verified backups off the same volume/machine to protected storage; a
same-volume snapshot does not survive volume loss. Define a backup schedule,
retention, encryption, access and recovery owner for any real deployment.

## Kubernetes backup, restore and rollback

The following `oc` commands operate in the explicitly selected dedicated project;
`kubectl -n cyberwatch-example` works equivalently for the portable deployment.
Use a unique snapshot name on every run. First configure the **separate tested
maintenance image digest from the same release** in
`deploy/maintenance/base/kustomization.yaml`. The server image intentionally has
neither Python nor tar and cannot be used for `oc cp` or backup execution. Stop
all application pods before starting maintenance, including for backup: an RWO
volume may not attach to a second node, and RWO does not exclude a second writer.

```sh
oc scale deployment/cyberwatch --replicas=0
oc wait --for=delete pod -l app.kubernetes.io/component=server --timeout=180s
oc apply -k deploy/maintenance/base
oc wait --for=condition=Ready pod/cyberwatch-maintenance --timeout=180s
oc exec cyberwatch-maintenance -- python3 /app/tools/backup.py backup /app/data/cyberwatch.db /app/data/drill-001.db
oc cp cyberwatch-maintenance:/app/data/drill-001.db backups/drill-001.db
python tools/backup.py verify backups/drill-001.db
```

For backup only, delete the maintenance pod with `--wait=true`, then scale the
Deployment back to one replica and wait for readiness. For recovery from a
previously exported backup, leave the Deployment stopped, start maintenance as
above if needed, then:

```sh
oc cp backups/drill-001.db cyberwatch-maintenance:/app/data/incoming-001.db
oc exec cyberwatch-maintenance -- python3 /app/tools/backup.py restore /app/data/incoming-001.db /app/data/restored-001.db --app-stopped
oc delete pod cyberwatch-maintenance --wait=true
```

For generic local Kubernetes use `deploy/maintenance/local` to supply fsGroup.
The maintenance pod expires after one hour and has no API credentials. Never
start it concurrently with the server. Copy into a unique `incoming` name because
`oc cp` itself is not an overwrite-protected restore operation.

Now add `DATABASE_PATH=/app/data/restored-001.db` to the overlay's ConfigMap
generator with `behavior: merge` (as in the live-mode example), review the
rendered YAML, and reapply the overlay. It restores the intended one replica:

```sh
oc apply -k deploy/overlays/rahti
oc rollout status deployment/cyberwatch --timeout=300s
oc get pods,pvc
```

Verify the records, API smoke test, readiness and logs before accepting recovery.
Keep the previous database until acceptance. For an application release rollback:

```sh
oc rollout history deployment/cyberwatch
oc rollout undo deployment/cyberwatch --to-revision=PREVIOUS-VERIFIED-REVISION
oc rollout status deployment/cyberwatch --timeout=300s
```

Retain ConfigMaps referenced by those revisions; Kustomize's generated hashes do
not delete earlier ConfigMaps automatically. Revert the environment image/config
in version control as well so the next apply preserves the rollback. Image
rollback does **not** undo a database migration. Confirm schema compatibility
first; an incompatible migration requires the tested pre-release backup recovery
procedure and its matching image. Prefer additive migrations with a rollback window.

## Teardown and costs

`docker compose down` removes the local container/network and retains its data
volume. `docker compose down --volumes` also destroys that project's database;
use only after exporting and verifying any needed backup.

For cloud pause, scale the Deployment to zero; persistent storage continues to
exist and may consume billed allocation. For final teardown of this dedicated
example, export/verify backups, inspect the current `oc project`, then remove only
the example resources. This command deletes the PVC and can delete its data:

```sh
oc delete -k deploy/overlays/rahti
oc delete secret cyberwatch-admin
```

Also remove retained generated `cyberwatch-config-*` ConfigMaps and any maintenance
pod after listing and checking their names. Deleting the entire dedicated project
is an alternative only after confirming it contains no other work. Never use a
wildcard namespace deletion. No automation in this repository provisions cloud
resources or purchases services. Check current [CSC billing and allocation rules](https://docs.csc.fi/cloud/rahti/get-started/billing/)
before deploying; record consumed CPU/memory/storage time in the course cost
evidence. A quota bounds resource use, not a guaranteed currency charge.
