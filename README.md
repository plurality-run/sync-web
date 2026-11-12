# Synchronic Web - Plurality Edition

The Synchronic Web is infrastructure for data assurance. Each journal maintains immutable, cryptographically linked records. Reciprocal bridges exchange root-signed heads so journals can preserve and inspect verifiable cross-journal history without requiring global consensus. Applications can retain selective proof material and verify data against an exact committed journal state.

Plurality 0.1.0 ports the Sandia Sync Web 1.6.2 baseline to Plurality-owned project destinations and release artifacts. Records behavior and its internal installer generation remain unchanged; original licenses, attribution and release history are preserved. See [the port and hosting checklist](docs/plurality-port.md) for artifact availability and acceptance gates.

Full documentation: [plurality-run.github.io/sync-web](https://plurality-run.github.io/sync-web)

## Federation model

Sync Web 1.6 uses reciprocal bridges for identity, proof reachability, and signed-head synchronization. A bridge grants no application-data access by itself. Remote application calls are delivered directly to the terminal journal, whose local policy may independently authorize staged blank read-only `use!`/`put!`, dedicated `use-batch!`/`put-batch!`, path-scoped staged `run!`, and committed `retrieve`. Namespace ownership and blank read-only `use!` do not imply `run!`; nested operations preserve and recheck the original caller. Retention, including administrator-only `prune!` / `prune-batch!` removal from temporary and permanent retained history, bridge/configuration changes, access policy, administration, secrets, windows, periodic configuration, and root-plane control remain local. Ready routes retain their exact public reverse-key material across process boundaries and unchanged Journal restarts. Optional `index?` metadata on committed resolution reports the exact absolute local and per-hop indexes selected without changing existing responses by default. An explicit `$federation.route` may also select one terminal responder for permanent-only retained `retrieve`/`retrieve-batch`; responder-local paths and structural Chain inventories expose exact retained evidence without provider search or contacting the attributed source, and each parent-relative `-1` selects the greatest materialized index in its containing permanent Chain. [`docs/ideas/federation.md`](docs/ideas/federation.md) is retained only as a historical, superseded design note; this README and the shipped documentation describe the current protocol and trust model.

## Isolated stored programs

`run!` executes a staged Scheme procedure under root/configured-local-admin default authority or an independent recursive path-scoped Authorization rule. Interface evaluates it outside `sync-let` in a masked environment and supplies the authenticated Journal capability. Namespace ownership and blank read-only `use!` do not imply execution; authenticated local non-admin and federated route principals may receive `run!` explicitly. Sync Web 1.6 makes no deterministic execution-meter, limit, budget, timeout, or meter-configuration claim. Every nested operation preserves and rechecks the original caller, and capabilities cannot escape. Shared self-coded object work separately runs through fresh `sync-let` children cloned from a sealed request-local capability template; no mutable child, result, proof, or application state is cached across boundaries.

## Repository Layout

| Directory | Description |
|---|---|
| `journal/` | Rust journal-sdk: HTTP server, S7 Scheme evaluator, RocksDB persistence |
| `records/` | Scheme record logic: `root`, `standard`, `tree`, `chain`, `ledger`, `federation`, `authorization`, `interface` |
| `services/` | Web services: `gateway`, `router`, `explorer`, `workbench`, `file-system` |
| `deploy/` | Single-node Compose-compatible container deployment |
| `tests/` | API smoke tests, load tests, multi-node network tests |
| `docs/` | Documentation site (Astro/Starlight) |
| `scripts/` | Compact check orchestration and read-only network diagnostics |
| `tools/` | Optional standalone tools, including `journal-cli`, Messenger, and the agent recorder |

## Quickstart

The fastest way to run a local stack:

```sh
COMPOSE_PROJECT_NAME=sync-local SYNC_WEB_VERSION=0.1.0 \
SECRET=your-root-secret INTERFACE_SECRET=your-interface-secret \
ADMIN_PASSWORD=your-login-password HTTP_PORT=8192 HTTPS_PORT=8193 \
docker compose -f deploy/compose/general/compose.yaml up
```

Use `podman-compose` or `podman compose` instead of `docker compose` if that is your container runtime. Plurality 0.1.0 retains the Sandia 1.6.2 installer, supporting fresh installation and exact updates from 1.5.0 or released 1.6.0/1.6.1 through the explicit update procedure; unsupported or unmarked existing databases fail closed. Already-diverged endpoint configuration needs the explicit repair in [`docs/migrations/1.6.2-endpoint-sync.md`](docs/migrations/1.6.2-endpoint-sync.md); code installation alone does not repair it. See `deploy/compose/general/README.md` for full configuration options, `tests/release-qa/README.md` for exact-image acceptance checks, and `docs/development-checks.md` for validation commands and tool dependencies.

## Messaging Demo

[`tests/demos/messaging`](tests/demos/messaging/README.md) provides a manual, local-HTTP Linux amd64 demo with Messenger, Explorer, and two Pi agents. It uses released Journal artifacts and explicit bridge/mailbox warm-up, with configurable LiteLLM and polling settings.

## License

MIT — see [LICENSE](LICENSE).
