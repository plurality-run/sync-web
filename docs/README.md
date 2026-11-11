# The Synchronic Web

The Synchronic Web is a global infrastructure for data assurance, enabling anyone to cryptographically and temporally notarize information. By publishing data to the Synchronic Web, creators and organizations can irrefutably prove the existence and integrity of their data at a specific point in time relative to their trusted anchors. This system supports strong notions of shared global state, provenance, and verifiable history, making it useful for public transparency, cybersecurity, digital media, legal records, intellectual property, and more.

At its core, the Synchronic Web is powered by distributed programs called journals, which maintain immutable, version-controlled logs (records) and continuously synchronize cryptographic metadata with other journals to achieve global consensus.

Please see the full [documentation](https://plurality-run.github.io/sync-web/) for more details.

---

## Repository Contents

Everything lives in [sandialabs/sync-web](https://github.com/plurality-run/sync-web):

| Directory | Description |
|---|---|
| `journal/` | Rust journal-sdk: HTTP server, S7 Scheme evaluator, RocksDB persistence |
| `records/` | Scheme record logic: `root`, `standard`, `tree`, `chain`, `ledger`, `interface` |
| `services/` | Web services: `gateway`, `router`, `explorer`, `workbench`, `file-system` |
| `deploy/` | Compose-compatible deployment config for a single-node stack |
| `tests/` | Smoke tests (`api/`), load tests (`load/`), network tests (`network/`) |
| `docs/` | Documentation site (Astro/Starlight) |

## Quickstart

See `deploy/compose/general/README.md` for single-node deployment instructions.

## Testing

- `tests/api/local-compose.sh smoke` — single-node full-stack smoke test
- `tests/network/compose/local-compose.sh up` — multi-node social-agent network
- `docs/development-checks.md` — check matrix and required tools
