# Development Checks and Dependencies

This repo has several independent validation layers. Run the checks relevant to the area you changed.

## Compact orchestration

- `scripts/sync-check --changed --base origin/main` conservatively maps committed, staged, unstaged, and untracked changes to existing component checks. Use `--plan` to inspect its selection and `--full` for every profile. Complete logs and a compact report are written under `target/sync-check/`.
- `scripts/sync-network status|wait-ready|probe|logs|snapshot --project <isolated-name>` provides read-only diagnostics for an existing generated multi-node network. Exact test project names are required and production-like names are rejected. It does not create, restart, or remove containers.
- Both tools use the local artifact contract documented in [`scripts/README.md`](../scripts/README.md).

## Core journal and records

- Rust journal tests
  - Path: `journal/`
  - Requires: Rust toolchain with Cargo, C build dependencies
  - Command: `cargo test`
- Scheme record tests
  - Path: repo root
  - Requires: Rust toolchain with Cargo and C build dependencies
  - Command: `CARGO_TARGET_DIR=journal/target cargo build --manifest-path records/tests/Cargo.toml && journal/target/debug/records-test --suite records/tests/suite.toml`

## Services

- Gateway tests
  - Path: `services/gateway/`
  - Requires: Node.js/npm
  - Command: `npm test`
- Explorer tests
  - Path: `services/explorer/`
  - Requires: Node.js/npm
  - Command: `npm test -- --watchAll=false`
- Workbench tests
  - Path: `services/workbench/`
  - Requires: Node.js/npm
  - Command: `npm test -- --watchAll=false`
- File-system/WebDAV tests
  - Path: `services/file-system/`
  - Requires: Go
  - Command: `go test ./...`

## Tools

- Journal CLI checks
  - Path: `tools/journal-cli/`
  - Requires: Python 3.11+
  - Command: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest discover -s tests -v`
  - Install smoke: `python3 -m pip install . && journal-cli --version && journal-cli --help`
- Messenger checks
  - Path: `tools/messenger/`
  - Requires: Node.js/npm; Docker or Podman for the image smoke test
  - Command: `npm run check`
  - Container command: `docker build -t sync-web-messenger:local .`

## CI release posture

- Pull requests validate without pushing; branch CI can publish `sha-<commit>` development images. Main/version merges perform real CI without creating numbered releases or versioned-image promotion.
- After owner approval, the single `Platform Release` manual entry point checks the exact main commit/version and reuses existing producers to build/test/publish that selected source. Release intent defaults false, and promotion never substitutes a PR-head image. See [operator instructions and exact development publication behavior](plurality-port.md#explicit-platform-release).
- Existing service non-version main `latest`, social-agent development `latest`, automatic Pages and independent Recorder tag releases remain separate, documented behaviors; none implies platform release approval.
- Offline release guard/event/source-binding tests: `python3 .github/scripts/test-platform-release.py -v`; shell checks: `bash -n .github/scripts/check-platform-release.sh .github/scripts/promote-image.sh`.
- Journal image builds use `cargo-chef` and registry BuildKit cache. Source-only Rust changes can reuse dependency layers; dependency graph changes in `journal/Cargo.toml` or lockfile inputs invalidate the dependency recipe and require a real rebuild per architecture.

## Release QA

- Lightweight release harness and provenance checks
  - Command: `scripts/sync-check release-qa deploy --jobs 1 --keep-going`
- Exact fresh single-node journey
  - Command: `LOCAL_COMPOSE_RELEASE_QA=1 COMPOSE_PROJECT_NAME=sync-release-local SECRET=root-password INTERFACE_SECRET=interface-password ADMIN_PASSWORD=admin-pass tests/api/local-compose.sh smoke`
- Sticky four-node route qualification and unchanged Journal restart
  - Command: `CONTAINER_RUNTIME=podman CONTAINER_COMPOSE='podman compose' tests/release-qa/run_sticky_readiness.sh --build`
  - Notes: requires an exclusive container-heavy lane; preserves an exact image manifest and fails on any post-ready route/proof/counter regression.

See [`tests/release-qa/README.md`](../tests/release-qa/README.md) for exact-image repeat and cleanup requirements.

## Integrated local stack

- Single-node compose smoke
  - Path: repo root
  - Requires: Docker Compose, Podman Compose, or `podman-compose`; `curl`; Python 3 for smoke helpers
  - Command: `COMPOSE_PROJECT_NAME=sync-local SECRET=root-password INTERFACE_SECRET=interface-password ADMIN_PASSWORD=admin-pass tests/api/local-compose.sh smoke`
  - Notes: builds local images, starts the general compose stack, runs API/WebDAV checks, and tears the stack down.

- Container image test targets
  - Path: repo root
  - Requires: Docker or Podman compatible build command
  - Command: `CONTAINER_RUNTIME=podman tests/test.sh` or `CONTAINER_RUNTIME=docker tests/test.sh`

## Load and network tests

- Locust unit tests
  - Path: `tests/load/locust/`
  - Requires: Python 3
  - Command: `python -m unittest discover -s tests`
- Locust load run
  - Path: `tests/load/locust/`
  - Requires: Python 3, Locust dependencies, running gateway, API token
  - Example: `API_TOKEN=sync-... locust --host=http://localhost:8192`
- Social-agent unit tests
  - Path: `tests/network/common/social-agent/`
  - Requires: Python 3
  - Command: `python -m unittest discover -s tests`
- Multi-node compose harness
  - Path: `tests/network/compose/`
  - Requires: Compose-compatible runtime, Python 3, PyYAML
  - Commands: `tests/network/compose/local-compose.sh generate`, then run compose from `tests/network/compose/`
- FIREWHEEL harness
  - Path: `tests/network/firewheel/`
  - Requires: FIREWHEEL and Docker-specific model-component support
  - Notes: this harness is intentionally Docker-specific and is not part of the baseline Compose-compatible workflow.

## Messaging demo

`tests/demos/messaging/README.md` documents the eight-service local HTTP/amd64 manual messaging demo, its LiteLLM configuration, and explicit bridge/mailbox warm-up. Cheap checks:

```sh
python3 -m unittest discover -s tests/demos/messaging -p 'test_*.py'
node --test tests/demos/messaging/agent/inbox.test.mjs
```

The Python demo checks use the existing topology-test PyYAML dependency. Container startup and human/agent exchanges are separate manual integration acceptance, not claimed by these unit tests. Do not point a demo at production credentials or Journals.

## Browser/manual checks

- Playwright is useful for local manual UI sanity checks, but is not part of the Explorer unit-test or CI setup unless explicitly added later.
- For ad hoc scripts that `require('playwright')`, set `NODE_PATH=$(npm root -g)` if using the globally installed package.
