# Changelog

## 0.1.0 (Plurality edition)

- Port the Sandia 1.6.2 baseline to the `plurality-run/sync-web` repository, documentation site and container/binary artifact namespace.
- Synchronize platform manifests and consumers on the Plurality 0.1.0 line; retain independently versioned tools and the unchanged Records installer generation.
- Preserve the original license, historical releases and attribution. Hosting is qualified separately from source preparation; see `docs/plurality-port.md`.

## 1.6.2

### Fixed

- **Endpoint configuration synchronization** — Exact `update-config!` changes to `(public interface endpoint)` now update the persisted Federation endpoint in the same Interface call, preventing reciprocal bridge responses from advertising an obsolete URL. Existing mismatches require an explicit post-update endpoint reapplication; installation does not silently repair them.
- **Maintenance update admission** — Explicit updates admit released 1.6.1 in addition to the existing 1.5.0 and 1.6.0 predecessors. A private Interface installer version marker distinguishes this Interface-only maintenance update from unsupported reapplication while preserving keys, history, relationships and authorization state.

## 1.6.1

### Fixed

- **Large-history federation latency** — Ordinary scalar and batch federated invocation now proves the selected terminal head instead of enumerating every retained bridge-history index. Explicit bridge-chain boundary retrieval retains complete-inventory behavior.
- **Patch update admission** — The existing explicit update workflow now admits exact released 1.6.0 state in addition to the existing exact 1.5.0 predecessor, preserves durable 1.6 state, and rejects reapplication or unsupported predecessor classes.

## 1.6.0

### Added

- **Retained federation retrieval** — Allows `retrieve` and `retrieve-batch` to use one explicit `$federation.route` as a terminal retention provider. The responder interprets committed paths locally, serves only permanently retained evidence under ordinary authorization, resolves each parent-relative `-1` to the greatest materialized index in its containing permanent Chain, exposes deterministic Chain inventories, and never searches for or contacts the attributed source. The terminal anchors proof construction to the exact permanent invocation head. The origin anchors the response proof, independently derives the same permanent selections from that proof, and uses richer same-root route evidence only for exact-path content verification.
- **Chain inventories** — Adds read-only `indices` to current linear and log Chains with exact ascending materialized indexes and structural completeness; historical Chains negotiate the method or execute their own complete `size`/`get` fallback inside `sync-let`.
- **Committed read indexes** — Added opt-in `index?` metadata to scalar and batch resolution so callers can capture the absolute local and per-hop indexes selected for a committed read without changing existing response shapes when omitted or false.
- **Atomic staged copies** — Added `copy!` and `copy-batch!` Interface/Gateway operations for raw server-side file and directory copying from one pre-mutation staged snapshot, including optional target expectations, ordered duplicate handling, and same-terminal signed routing.
- **Administrative history truncation** — Added Self-local administrator `truncate!` across both Chain implementations, Ledger permanent/temporary history, Interface, and Gateway. Inclusive positive/negative cutoffs release locally available history while preserving logical chain identity, numbering, retained suffix, staged state, and future appends.
- **Administrative retained-path pruning** — Added Self-local administrator `prune!` and `prune-batch!` for idempotent leaf/directory removal from both temporary and permanent Ledger retention. Canonical committed paths include negative indexes; direct or ancestral committed `*crypto*` targets reject complete prune and unpin calls, and valid batches install their retained-field candidates atomically while preserving Stage and committed history identity, signatures, size, and numbering.
- **Explicit staged-program authorization** — Added independent recursive path-scoped `call!` grants for authenticated local non-admin and federated route principals. Namespace ownership and `get` do not imply execution; nested operations preserve and recheck the original caller, while Root/configured local Interface administrators retain default authority. Bridge, configuration, access, retention, secret, window, periodic-configuration, and root-plane controls remain local, and 1.6 claims no deterministic execution meter.

### Changed

- **Unified retained Explorer tree** — Replaces the routed Ledger snapshot strip with one `State`/`Bridges` tree at the selected responder, including exact retained indexes, authorized nested State, recursive retained bridges, and route-preserving deep links.
- **Typed Explorer paths** — Preserves integer, symbol, and Scheme-string terminal key identity from directory listing through selection and follow-up reads, with stable disambiguation for colliding labels.

### Fixed

- **Administrator JSON projection** — Projects the unchanged internal administrator principal list as an exact username-keyed JSON object, validates replacements atomically, and provides guarded Explorer removal controls.

## 1.5.0

### Added

- **Reciprocal federation** — Added exact committed-object routing, direct terminal invocation limited to `get`, `set!`, `get-batch`, `set-batch!`, and `resolve`, terminal-local authorization, and one-round-trip reciprocal bridge synchronization.
- **Federated service context** — Gateway uses explicit working-route context for staged scalar `get`/`set!` and dedicated `get-batch`/`set-batch!`; Explorer currently uses it for scalar `get`/`set!`. Committed resolution and retention use canonical full paths while Interface keeps proof retention local to Self.
- **Bridge acceptance configuration** — Added Explorer controls for automatic or preapproved incoming bridge establishment through the generic configuration API.
- **Raw value view** — Added view-only exact-byte inspection in Stage and Ledger with inert text/source, signature-checked browser media previews, hex fallback, and exact-byte download.
- **Deterministic Records scenarios** — Added an isolated-process suite and discrete-event multi-journal scheduler with fixed time/randomness, stable message ordering, latency/drop schedules, trace capture, and parallel case execution.
- **Journal key rotation** — Added root-authorized journal signing-key transitions, retained key epochs, and exact historical authentication indexes for reciprocal federation.
- **Release diagnostics** — Added compact changed-component checks, exact-image release QA, a fresh single-node administrator/nonadministrator journey, and project-scoped network readiness/probe/snapshot tooling with semantic activity counters and redacted artifacts.
- **Administrator staged programs** — Added local-only `call!` for staged Scheme procedures under the root caller or configured local Interface administrators. Namespace owners and Authorization-policy grantees cannot gain execution authority, rules naming the removed `call!` field fail closed, and every remote/federated principal is denied. Version 1.5 defines no execution meter, limit, budget, timeout, or meter configuration because those controls cannot yet be enforced reliably. Nested calls re-enter current authentication and administrator checks, capabilities cannot escape, and completed nested effects remain non-atomic when a later program operation fails.
- **Periodic staged program** — When an outer Interface step creates a new Ledger index, launch the optional admin-managed `(*state* *periodic*)` program once through detached `call!` with that committed index. Launches may overlap and complete out of order; unchanged steps, internal optimistic retries, and step continuations do not create duplicate launches.

### Changed

- **Separated Root and Interface credentials** — Root remains Journal-only and host-managed, while the independently rotatable Interface bearer is persisted in private Root state and shared only with Gateway. Installation and both rotation directions reject equivalent credentials. Journal/Gateway diagnostics omit request and response bodies. Backups therefore contain a live Interface credential but never Root or private signing keys.
- **Journal SDK 1.4.0** — Bumped the crate for exact one-argument `sync-eval`, shared-code isolation, request-local proof serialization, deterministic scenario support, and related evaluator/persistence changes.
- **Tree-native values** — Removed the durable Document wrapper and general metadata API; user payloads are byte vectors stored directly by Tree, while `expression?` remains an Interface boundary codec and preview types are inferred safely at read time. Transition audit values now record the encoded bytes received by Ledger rather than the caller-side expression.
- **Bridge model** — Replaced publishers, subscribers, and Push/Pull/None negotiation with one reciprocal bridge relationship and one synchronization initiator.
- **Explorer navigation** — Stage and Ledger share a working-journal breadcrumb; Ledger adds a mirrored historical breadcrumb and an in-place synchronization spinner, while Access and Admin remain Self-local.
- **Bridge administration** — Presents a spacious bridge list and explicit incoming preapproval allow/remove controls without legacy reciprocal/publisher/subscriber terminology.
- **Federation routes** — Finite routes may revisit their origin; terminal policy, rather than routing mechanics, decides whether a self-targeted request is allowed.
- **Ledger path syntax** — Uses directional bridge names directly as one flat traversal prefix, with optional interleaved indexes, instead of repeating `*bridge*` before every hop. Public committed `resolve`, `pin!`, and `unpin!` now accept this same full path without separate federation cursors or client-managed proof responses.
- **Social-agent model** — Creates configurable deterministic users on every journal, splits each user's fixed keys between public and private state, grants same-user private access over exact SEGMENTS-bounded walks including finite journal revisits, runs independent per-user activity/accounting, and exercises path-only `pin!`/`unpin!` without a redundant client-side proof resolve.
- **Execution isolation** — Made `sync-eval` an exact one-argument object loader, introduced explicit shared-code `sync-let` boundaries, moved proof serialization to request-local primitive tracing over the authoritative Journal session, and retained rollback for trusted host dispatch. Each request builds one sealed capability template and clones fresh direct slots for every boundary without sharing state, results, proofs, or mutable child environments.
- **Records composition** — Split networking, routing, invocation authentication, and peer operational state into a trusted Federation class while Ledger remains authoritative for data, history, proofs, retention, and peer evidence and Authorization remains policy-only.
- **Ephemeral interface signing** — Derives journal-bound interface and continuation signing keys only for the authenticated request, persists public keys alone, and accepts a temporary stale-route gap during explicit interface-secret rotation instead of retaining old private keys.
- **Fresh installation policy** — Removed in-place record recoding and legacy peer/key migration machinery. The 1.5 installer atomically rejects every nonfresh database; Compose records the platform version in fresh volumes and rejects missing/mismatched markers before server startup. Preserve 1.4.x databases with their exact runtime for read-only historical access and start 1.5 on a new volume.
- **Records performance** — Reduced repeated contained Ledger head traversal and eliminated per-read 256-bit Tree lookup lists while preserving proof, wire, history, and mixed-code state behavior.

### Fixed

- **Deployment admin seeding** — Renders `INTERFACE_ADMINS` as literal local principal data so configured administrators are authorized immediately on a fresh Compose installation and can replace the admin list.
- **Metrics boundary** — Keeps Prometheus metrics on the private Gateway service, returns `404` for public router `/metrics` requests in HTTP and TLS modes, and bounds unmatched Gateway request labels to one constant series.
- **Social benchmark saturation** — Restores `ACTIVITY=0` as continuous no-delay federation traffic for concurrency and throughput benchmarks, with `ACTIVITY_DISABLED=1` as the explicit setup-only mode.
- **Bridge head exchange** — Returns the receiver-known historical digest and merges retained temporary structure into locally pruned signed-head proofs, preserving synchronization under concurrent pin/unpin activity.
- **Remote proof retention** — Deserializes proof node maps independently of JSON object key order so real Gateway resolve responses can be pinned locally at the origin.
- **Scoped Explorer routes** — Roots Stage and Ledger trees at the shared `*state*` namespace with the signed-in user's real folder sorted first and emphasized, refreshes latest origin snapshots before extending a route, traverses ordinary ancestor names without exposing reserved state or unauthorized child content, hides mutation controls outside the exact writable remote bucket, presents authorization failures as stable errors, keeps mobile global controls and Access scroll position stable during refresh, and visibly marks remote-disabled Access/Admin controls as Self-local.
- **Strict evaluation isolation** — Re-evaluates object state in its current proof/materialization context because content words alone do not identify available descendants, while retaining only immutable-code loader caching and rejecting missing graph dependencies before durable commit.
- **Federation startup** — Reports uncommitted bridge routes explicitly and waits for complete signed route reads before social-agent activity metrics begin.
- **Sticky route readiness** — Carries an already-hydrated reverse interface key through terminal route serialization with an exact bounded trace, preventing a ready route from reverting to “reverse interface key is unavailable” across process boundaries or unchanged Journal restart while preserving roots and proof digests.
- **Bridge re-establishment** — Retains alias/root identity tombstones across deletion, allows the same relationship to be restored (including under preapproval policy), and cleanly rejects alias or root substitution.
- **Localized Explorer denial** — Keeps the tree mounted and places access failures beneath the denied expanded row so allowed siblings, collapse, and upward navigation remain usable.
- **Historical retention** — Preserves Log Chain branch boundaries and pinned proof paths across pruning, truncation, explicit window shrink/widen, retained-history boundaries, and separate-process reopen.
- **Tree and batch invariants** — Prevents writes through unavailable stubs, preserves absent-path/non-membership proof digests, validates full batch shape before mutation, and removes missing-copy ghosts.
- **Federated WebDAV** — Forwards latest and explicit multi-hop ledger paths in canonical full form and correctly lists, copies, moves, and deletes percent-escaped filenames.
- **Workbench errors and mobile layout** — Treats canonical journal `(error ...)` values returned over HTTP 200 as failures while preserving raw request/response text, and keeps query, output, and history controls usable at narrow widths.

## 1.4.3

### Changed

- **Journal interface defaults** — General Compose now derives the raw journal interface endpoint from `ORIGIN` instead of ever falling back to `SECRET`, and passes `ORIGIN`, `INTERFACE`, and `JOURNAL_NAME` into the journal container.
- **Admin update behavior** — `JOURNAL_UPDATE=1` preserves the existing runtime-managed admin list instead of reseeding it from `INTERFACE_ADMINS`.
- **Bridge admin UI polish** — Shortened the bridge creation button to “Create” and aligned selected Push/Pull/None segment color with the page’s primary button color.

## 1.4.2

### Added

- **Bridge admin controls** — Added Explorer admin controls for subscribing to peers and publishing to peers, including endpoint editing, delete actions, and Push/Pull/None policy selection.
- **Bridge delete operations** — Added explicit incoming bridge and outgoing subscriber delete operations through the interface and gateway.
- **Version-driven ledger releases** — Ledger and journal-sdk release artifacts are now published from main `VERSION` changes, using `VERSION` as the release source of truth.

### Changed

- **Bridge configuration** — Disabled bridge and subscriber entries are preserved as `none` tombstones, while delete removes the config entry.
- **Bridge identity defaults** — Ledger public config now stores the journal name so Explorer can autofill the remote name when creating publishing relationships.
- **Idea docs** — Consolidated current cross-journal data-flow notes and removed stale/superseded idea documents.

### Fixed

- **Stale bridge endpoints** — Explorer now prefers authoritative bridge interface config over legacy local registration snapshots.
- **Bridge sync loop** — Incoming bridges with negotiated `none` policy are skipped during periodic bridge synchronization.

## 1.4.1

### Added

- **Windows ARM64 binaries** — Add Windows ARM64 builds for `ledger`, `journal-sdk`, and `agent-recorder` release artifacts.

### Changed

- **Journal SDK patch version** — Bump `journal-sdk` to `1.3.1` because the journal crate dependency configuration changed.
- **Journal dependency build scope** — Disable unused default `pqcrypto` algorithm features so Windows ARM64 builds avoid compiling unused PQClean C implementations.

## 1.4.0

### Added

- **Lightweight ledger binary** — Added a user-facing `ledger` executable for local and agent-recorder-oriented deployments without the full gateway/explorer/identity/router stack. The binary embeds core ledger records, initializes empty databases, runs periodic steps, supports record updates, bridge configuration, generated local secrets, and direct query evaluation.
- **Ledger release artifacts** — Added a `Ledger Binaries` workflow that builds downloadable `ledger-*` and `journal-sdk-*` artifacts for Linux, Linux musl/Alpine, macOS, and Windows targets. Versioned tag builds publish release assets from a final publish job with `SHA256SUMS`.
- **Ledger deployment docs** — Added lightweight ledger deployment notes and initial binary/Compose documentation.

### Changed

- **Explorer stage tree** — The staged-state tree now shows all readable stage users while keeping the current user’s staged home as the default view.
- **Platform package metadata** — Added tooling to keep platform-versioned TypeScript package metadata aligned with top-level `VERSION`.

### Fixed

- **Ledger bridge tracing** — Preserve document metadata through remote bridge trace results.
- **Ledger public config** — Restrict public configuration exposure to intended public fields.
- **Log-chain truncation** — Ensure `truncate!` mutates log-chain state correctly.
- **Ledger signing keys** — Derive ledger signing keys at step time instead of storing private signing keys in ledger config.
- **Docs 404 page** — Added a custom docs 404 page and disabled Starlight’s injected 404 route to avoid build warnings.
- **Windows ledger builds** — Patch vendored s7 at build time for Windows/MSVC builds without modifying vendored s7 sources.

## 1.3.2

### Fixed

- **Explorer path handling** — Parse ledger directory entries as `[name, type]` pairs, preserve encoded path segments for API calls, and display decoded names for files and directories with spaces or other escaped characters.
- **Release promotion** — Avoid expensive main-branch validation rebuilds for versioned releases by promoting branch-validated SHA images.
- **WebDAV docs** — Clarified API-token authentication, service-side path escaping, and Windows client limitations.

## 1.3.1

### Fixed

- **WebDAV compatibility** — Added minimal lock responses for clients that require class-2 WebDAV behavior, including macOS Finder.
- **WebDAV path handling** — Percent-encode WebDAV names that are not unescaped R7RS identifiers before ledger calls and decode them for directory listings.
- **Ledger browsing** — Accept synthetic ledger collection probes without trailing slashes for file managers that normalize paths.
- **WebDAV authentication docs** — Clarified that WebDAV Basic Auth uses a Sync Web API token as the password, not the account password.

## 1.3.0

### Added

- **Document records** — Added byte-vector-only document payloads with metadata support and explicit `expression?` public I/O codec for expression-oriented callers.
- **WebDAV file-system service** — Replaced the previous file-system adapter with a gateway-backed WebDAV service and navigable ledger index paths.
- **Gateway events** — Added authenticated Server-Sent Events change hints and Explorer live refresh integration.
- **Router splash page** — Added a static journal node home page and WebDAV guide served directly by the router.

### Changed

- **Record paths** — Public ledger/interface paths now use flat path syntax for staged, indexed, and bridge traversal paths.
- **Document adapters** — Explorer, WebDAV, gateway examples, social-agent, and load workloads now write normal document content as byte-vectors unless explicitly using `expression?`.
- **Pinned state** — `pinned?` now reports local permanent proof value availability; confirmed values including `(nothing)` are pinned, while `(unknown)` is not.
- **Compose defaults** — All service image tags default to `1.3.0`.

### Fixed

- **Bridge resolution** — Historical multi-hop bridge paths now return semantic values/unknowns instead of low-level sync-node access errors.
- **Explorer stability** — Preserved active staged edits during background refreshes and fixed bridged file pin/unpin display.
- **Batch JSON** — Normalized JSON batch subqueries and decoded batch results consistently.
- **Directory discovery** — Explorer directory discovery uses content-only reads to avoid unnecessary proof/pin coupling.

## 1.2.0

### Added

- **Identity provider** — Ory Kratos service for username/password login and registration. Username-only identity schema; no email required. Admin identity seeded on startup via `ADMIN_USERNAME` / `ADMIN_PASSWORD` environment variables.
- **Gateway authentication** — Kratos session cookies validated at the gateway boundary; unauthenticated requests rejected with 401. API tokens (`Authorization: Bearer sync-...`) accepted for machine/automation callers. Resolved identity forwarded to all journal calls.
- **Auth UI** — Login, registration, and account settings pages served at `/auth/...` by the gateway, consuming Kratos self-service flows.
- **User namespaces** — Each user may only write to `(*state* <username> ...)` paths. Cross-namespace writes are rejected with a permissions error.
- **Private paths** — Paths containing `*private*` (e.g. `(*state* alice *private* ...)`) are readable only by the owning user.
- **Admin list** — `*admins-get*` and `*admins-set*` operations manage the admin list. Admins bypass all path restrictions. `INTERFACE_ADMINS` environment variable seeds the list on startup.
- **Restricted operations** — `bridge!`, `*secret*`, `*admins-get*`, and `*admins-set*` are restricted to admins; regular users receive a `permissions-error`.
- **Explorer session awareness** — Explorer detects and surfaces the logged-in user identity in the toolbar.

### Changed

- **Authentication envelope** — Canonicalized to `(identity *journal*)` for root and a bare symbol (e.g. `alice`) for named users. The previous `(self)` and list-wrapped forms are no longer used.
- **File system / SMB** — Gateway-backed path removed; the file-system service now authenticates directly to the journal using a bearer token. `HttpGatewayClient` removed.
- **Router** — nginx routes extended to cover `/auth/`, explorer, workbench, gateway docs, and API under both HTTP and TLS configurations.
- **Compose defaults** — All service image tags default to `1.2.0`.

## 1.0.0

Initial release. Monorepo consolidation of journal, records, services, and analysis repositories.
