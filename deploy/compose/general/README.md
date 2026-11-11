# Synchronic Web Ledger Compose Network

This Compose application runs a core Sync Web stack consisting of Journal, Gateway, identity provider, and Router. Explorer, Workbench, and the WebDAV `file-system` service are independent optional profiles.

The journal service uses the generic `journal-sdk` image directly. The general interface is assembled at startup from mounted deployment inputs:

- `records/lisp/*.scm`
- `deploy/compose/general/run.sh`
- the persistent `database` volume

For a fresh database, `run.sh` installs the general interface from the mounted Lisp files. Installation is fail-closed: only the exact successful installer result is accepted. A process error, Scheme error value, or malformed result exits nonzero; the version marker is not written, the server is not started, and result or credential content is omitted from diagnostics. With `JOURNAL_UPDATE=0`, a correctly version-marked database reopens normally without reinstalling or interpreting mounted record source during startup.

The 1.6.2 Interface supports exact in-place transitions from version-marked 1.5.0, 1.6.0 and 1.6.1 databases when `JOURNAL_UPDATE=1`. The 1.5.0 path performs the 1.6 durable conversion; the 1.6.0/1.6.1 path preserves the existing durable shape while replacing built-in Records classes. Both 1.6 maintenance paths preserve history, derived keys, relationships, and authorization state; the 1.5.0 path also requires the documented resource-API grant conversion procedure. The Plurality runners write the 0.1.0 deployment marker only after exact Interface success. Every other version mismatch or unmarked existing database fails closed. See [the 1.6.2 endpoint procedure](../../../docs/migrations/1.6.2-endpoint-sync.md) for explicit repair of already-diverged endpoint configuration; installation alone does not repair it.

Before release or deployment, bind every mutable image tag to a clean source commit/tree using the image manifest and run the fresh single-node plus sticky federation journeys in [`tests/release-qa/README.md`](../../../tests/release-qa/README.md). A no-build repeat rejects changed image IDs/digests before startup.

## Requirements

- A Compose-compatible container runtime: Docker Compose, Podman Compose, or `podman-compose`
- `curl` for the local smoke helper

The bind mounts use SELinux relabel flags (`:Z`) so rootless Podman can read the mounted startup script and Lisp files.

## Stack identity and ports

Use `COMPOSE_PROJECT_NAME` to isolate local, public, and experimental stacks. Container and network names are prefixed from this value, for example `sync-dev-journal` and `sync-prod-gateway`.

Default local ports are adjacent and non-privileged:

- `HTTP_PORT` default `8192`
- `HTTPS_PORT` default `8193`

Example local core-only stack:

```bash
COMPOSE_PROJECT_NAME=sync-dev SECRET=root-password INTERFACE_SECRET=interface-password \
ADMIN_PASSWORD=admin-pass HTTP_PORT=8192 HTTPS_PORT=8193 \
docker compose -f deploy/compose/general/compose.yaml up -d
```

Default startup is core-only. Add profiles explicitly for optional services; see [Optional service profiles](#optional-service-profiles).

Example public stack using standard ports:

```bash
COMPOSE_PROJECT_NAME=sync-prod SECRET=root-password INTERFACE_SECRET=interface-password \
ADMIN_PASSWORD='<independent-password>' ORIGIN=https://example.com HTTP_PORT=80 HTTPS_PORT=443 \
docker compose -f deploy/compose/general/compose.yaml up -d
```

With Podman Compose:

```bash
COMPOSE_PROJECT_NAME=sync-dev SECRET=root-password INTERFACE_SECRET=interface-password \
ADMIN_PASSWORD=admin-pass HTTP_PORT=8192 HTTPS_PORT=8193 \
podman-compose -f deploy/compose/general/compose.yaml up -d
```

## Optional service profiles

The optional profile names are `explorer`, `workbench`, and `file-system`. Each profile starts only that service plus its genuine core dependencies. Router remains in the core stack and resolves optional upstreams at request time, so disabling an optional service does not prevent Router startup; its route responds as unavailable until that service is enabled.

Use the same project name and required secrets for each command. The abbreviated examples show only the profile selection:

```bash
# Core only: Journal, Gateway, identity provider, and Router
docker compose -f deploy/compose/general/compose.yaml up -d

# One optional service
docker compose -f deploy/compose/general/compose.yaml --profile explorer up -d
docker compose -f deploy/compose/general/compose.yaml --profile workbench up -d
docker compose -f deploy/compose/general/compose.yaml --profile file-system up -d

# Representative combinations
docker compose -f deploy/compose/general/compose.yaml \
  --profile explorer --profile workbench up -d
docker compose -f deploy/compose/general/compose.yaml \
  --profile explorer --profile file-system up -d

# Complete service set
docker compose -f deploy/compose/general/compose.yaml \
  --profile explorer --profile workbench --profile file-system up -d
```

`podman compose` and `podman-compose` accept the equivalent profile flags for runtimes that implement the Compose profile specification. Stopping with `down` removes containers and the project network for both core and currently selected profiles; add the same profile flags when required by an older Compose frontend.

## Configuration

- `COMPOSE_PROJECT_NAME` (recommended): stack/project identity used for generated volumes and parameterized container/network names
- `SYNC_WEB_VERSION` (default `0.1.0`): platform image version; fresh databases record this value and later starts reject missing or mismatched volume markers
- `SECRET` (required): Root secret supplied only to Journal
- `INTERFACE_SECRET` (required): independently rotatable Interface bearer supplied to Journal and Gateway and persisted in private Root state; it must differ from `SECRET` at installation and after rotation in either direction
- `INTERFACE_ADMINS` (default `admin`): comma-separated local usernames seeded as `(*state* <name>)` interface administrators on fresh installation
- `ADMIN_USERNAME` (default `admin`): identity-provider bootstrap username
- `ADMIN_PASSWORD` (default empty): independent identity-provider bootstrap password
- `HTTP_PORT` (default `8192`): host HTTP port exposed by router
- `HTTPS_PORT` (default `8193`): host TLS port exposed by router
- `ORIGIN` (default `http://localhost:8192`): public origin used by the identity provider and as the default base for the raw journal interface URL; set this explicitly when using non-default/public ports or hostnames
- `INTERFACE` (default `${ORIGIN}/api/v1/journal/interface`): public raw journal interface endpoint advertised to bridge peers
- `JOURNAL_NAME` (default `INTERFACE`): public journal display/peer name advertised to bridge peers
- `PERIOD` (default `8`): seconds between outer Interface steps; each newly committed Ledger index launches the optional `(*state* *periodic*)` program once
- `WINDOW` (default `1024`): retained historical state window
- `JOURNAL_UPDATE` (default empty): set to `1` only for the supported, version-marked 1.5.0-to-0.1.0 or 1.6.0/1.6.1-to-0.1.0 transition; ordinary 0.1.0 reopen leaves it unset
- `TLS_CERT_HOST_PATH` (default `./tls/tls.crt`): host certificate file mounted into router
- `TLS_KEY_HOST_PATH` (default `./tls/tls.key`): host key file mounted into router
- `ACME_WEBROOT_HOST_PATH` (default `./acme-challenge`): host directory mounted at `/var/www/acme-challenge` for HTTP-01 challenge files
- `TLS_CERT_FILE` (default `/etc/nginx/certs/tls.crt`): in-container certificate path used by router
- `TLS_KEY_FILE` (default `/etc/nginx/certs/tls.key`): in-container key path used by router
- `FILE_SYSTEM_IMAGE` (default `ghcr.io/plurality-run/sync-web/file-system:0.1.0`): image used by the `file-system` service
- `SYNC_FS_MAX_OBJECT_BYTES` (default `1048576`): maximum WebDAV object size

Gateway note:

- `ALLOW_ADMIN_ROUTES` is disabled in the standard stack. Gateway receives only `INTERFACE_SECRET`, never Root, so Root-plane administration remains Journal-local.
- Gateway landing page is exposed through the router at `/gateway`.
- Public/client-facing API traffic should go to `gateway` under `/api/v1/general/*` and `/api/v1/root/*`.
- WebDAV traffic is exposed through the router under `/webdav/`.
- The raw `/interface` endpoint is still present for direct journal transport use and bridge-oriented internals.
- The journal's periodic scheduler uses the raw Root call `(*step* "<root-secret>")`. The non-mutating outer step commits through its internal continuation, then launches the optional `(*state* *periodic*)` procedure once via detached `run!` only when that commit created a new index.

Monitoring note:

- Prometheus metrics remain available inside `sync-net` at `http://gateway/metrics`.
- Gateway does not publish a host port, and exact router `/metrics` requests return `404` over HTTP and TLS.
- Existing monitors that scraped the router must move to an internal Compose-network scraper or another explicitly private collector.

## TLS behavior

This stack uses one compose file. Router auto-selects mode at startup:

- HTTP mode: if TLS cert/key files are not present
- TLS mode: if both `TLS_CERT_FILE` and `TLS_KEY_FILE` exist

`tests/api/local-compose.sh` forces HTTP mode by default (`LOCAL_COMPOSE_FORCE_HTTP=1`) for predictable local smoke runs. Set `LOCAL_COMPOSE_FORCE_HTTP=0` if you explicitly want TLS behavior during local-compose execution.

In TLS mode, router serves:

- container port `80` for ACME HTTP-01 challenge path and HTTPS redirects
- container port `443` for proxied application routes

The host ports are controlled by `HTTP_PORT` and `HTTPS_PORT`.

The default compose stack mounts ACME webroot to `/var/www/acme-challenge`. Use `ACME_WEBROOT_HOST_PATH` to override where challenge files come from on the host.

Example TLS-backed public stack:

```bash
COMPOSE_PROJECT_NAME=sync-prod \
TLS_CERT_HOST_PATH=/absolute/path/to/fullchain.pem \
TLS_KEY_HOST_PATH=/absolute/path/to/privkey.pem \
SECRET=root-password INTERFACE_SECRET=interface-password \
ADMIN_PASSWORD='<independent-password>' ORIGIN=https://example.com HTTP_PORT=80 HTTPS_PORT=443 \
docker compose -f deploy/compose/general/compose.yaml up -d
```

## Local runner

Use the local helper from repository root:

```bash
# Interactive run
COMPOSE_PROJECT_NAME=sync-local tests/api/local-compose.sh up

# Smoke test
COMPOSE_PROJECT_NAME=sync-local tests/api/local-compose.sh smoke
```

The local compose helper defaults to `COMPOSE_PROJECT_NAME=sync-local`, `HTTP_PORT=8192`, and `HTTPS_PORT=8193`. It builds local service images, enables the WebDAV file-system service by default, and uses the same mounted Lisp/runtime script layout as the reference compose stack.

To override the file-system image during local development:

```bash
FILE_SYSTEM_IMAGE=sync-web/local-file-system:1.0.0 tests/api/local-compose.sh up
FILE_SYSTEM_IMAGE=sync-web/local-file-system:1.0.0 tests/api/local-compose.sh smoke
```

## Teardown

Stop a stack without deleting data:

```bash
COMPOSE_PROJECT_NAME=sync-dev docker compose -f deploy/compose/general/compose.yaml down
```

Delete stack volumes only when you intentionally want to remove the journal database and identity-provider state:

```bash
COMPOSE_PROJECT_NAME=sync-dev docker compose -f deploy/compose/general/compose.yaml down -v
```

Do not run `down -v` against a public/prod `COMPOSE_PROJECT_NAME` unless you intend to destroy that stack's persisted data.
