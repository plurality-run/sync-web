# Plurality 0.1 port and hosting checklist

Plurality 0.1.0 is a distribution port of Sandia Sync Web 1.6.2, based on
`93ca37cd548d9431fe0d3dae43af1bd625ce54ae`. It changes project destinations,
platform release numbering and the existing publication paths, not the Records
protocol, object APIs, cryptography or persistence behavior. The original
license, attribution, historical changelog and migration documents remain.
Queued features and the separate Rust CLI rewrite are not part of this port.

A source candidate or open PR is not a published release. Do not deploy the
`0.1.0` image defaults or run release-download consumers until the corresponding
Plurality artifacts have been published and checked. Source-local builds remain
available through `tests/api/local-compose.sh`.

## Version and artifact map

| Surface | Producer | Version/destination | Consumers |
| --- | --- | --- | --- |
| Journal image | `.github/workflows/journal.yml` | `ghcr.io/plurality-run/sync-web/journal-sdk:0.1.0` (preferred musl), plus `0.1.0-musl` | General/Ledger Compose, local smoke, messaging demo, network tests |
| Six service images | `services-*.yml` | `ghcr.io/plurality-run/sync-web/{gateway,explorer,workbench,router,identity-provider,file-system}:0.1.0` | General Compose, local smoke, messaging demo, network tests |
| Social-agent image | `tests-social-agent.yml` | `ghcr.io/plurality-run/sync-web/social-agent:0.1.0` | Generated network Compose |
| Journal/Ledger binaries and AOT | `ledger.yml` | `plurality-run/sync-web` release `ledger-v0.1.0`, Linux x86_64 glibc/musl, `SHA256SUMS` | Manual downloads, messaging demo's `fetch-ledger.py` |
| Agent Recorder | `agent-recorder.yml` | Independent `agent-recorder-v0.1.3` version stream; checksummed Linux/macOS/Windows artifacts | Optional standalone recorder; no platform-version reassignment |
| Journal CLI | `journal-cli.yml` | Independent Python package `0.1.0`; source install, not a new package-index publisher | Existing CLI users and messaging demo |
| Messenger | `tools-messenger.yml` | Independent Node package `0.1.0`; source install, not a new package-index publisher | Optional browser messaging tool and demo |
| Documentation/PDF | `docs.yml` | `https://plurality-run.github.io/sync-web/`, platform package version `0.1.0` | Current repository/docs links |
| File-system Go module | Service workflow and Go tests | `github.com/plurality-run/sync-web/services/file-system` | File-system command and internal imports |
| Explorer/Gateway/UI/Workbench/docs manifests | `scripts/sync-platform-package-versions.js` | Root `VERSION` = `0.1.0`, synchronized package/lock roots | Platform builds |
| Native Journal SDK crate | Existing Cargo builds | Independent crate version `1.4.0`, unchanged | Existing Rust dependency/build graph |

The social-agent in this repository reads the root `VERSION` both in its
producer and in `tests/network/compose/generate.py`; it follows the platform
version. This is distinct from the external Firewheel dependency below.
Internal Records installer metadata remains `1.6.2`. It describes the unchanged
installer generation, not the Plurality distribution version. Historical test
fixtures and their expected Records generation remain unchanged.

## Producers before consumers

1. Validate this candidate with the existing native/Records/service/tool tests,
   deployment and demo checks, package synchronization and documentation build.
2. Feature-branch pushes run existing CI and can publish **SHA-tagged validation
   images** for Journal and the six services. The social-agent workflow also
   tests/builds a SHA-tagged branch image. These are pre-merge package writes,
   not final version tags or a release. Pull-request jobs build without pushing
   images. Ledger and Recorder build jobs upload workflow artifacts; they do
   not create a release from the feature branch.
3. Check each validation image's source provenance, actual pull access and
   visibility in the new namespace. These are development artifacts, not an
   approved numbered release or substitutes for the selected main source.
4. Obtain the owner's acceptance and authorized squash merge. Main CI performs
   real validation, including Journal native/AOT/build/Compose checks even when
   `VERSION` changes. Merge alone does not approve a numbered release.
5. After explicit owner approval of the main commit and version, dispatch the
   single platform release entry point below. It builds/tests that exact source,
   publishes its SHA images, promotes those same-source images and publishes
   `ledger-v0.1.0` plus the platform social-agent version. It never selects an
   associated PR head or a diagnostic image. Pages remains a separate main-only
   development deployment; a PR builds docs without requiring Pages setup.
6. Validate final image digests/source labels, unauthenticated pulls as intended,
   binary asset availability/checksums and the published docs/PDF before using
   their consumers. Run exact-image Compose/API and network acceptance against
   those actual artifacts, not merely renamed references or old Sandia layers.

The normal branch-push workflows run in addition to PR workflows. Review their
publication effects before pushing. Preserve failed runs and source/image
identities; do not reinterpret a package write as end-to-end hosting success.

## Explicit platform release

`Platform Release` (`.github/workflows/platform-release.yml`) is the single
owner-triggered numbered platform publication entry point. After merge and owner
approval, select **main** in Actions and supply the full main SHA and its root
`VERSION`. For example, using the existing repository access:

```sh
gh workflow run platform-release.yml --ref main \
  -f commit="$APPROVED_MAIN_SHA" -f version=0.1.0
```

Set `APPROVED_MAIN_SHA` to the full owner-approved main SHA first. This is an
operator instruction, not approval to execute it. The selected SHA
must equal the main SHA captured by that dispatch and each checkout; the version
must equal the committed `VERSION` and synchronized manifests. A branch dispatch,
wrong SHA or version fails before producer jobs. If main moves before dispatch,
select/review the new main SHA rather than publishing some other source silently.

The entry point reuses Journal, Ledger, six service and social-agent workflows
with explicit `release: true`. All other events, including their individual
manual CI buttons, default to false. Journal promotion requires successful native,
image and Compose jobs; it cannot promote a skipped builder. Native/AOT/linkage,
source provenance, runtime smoke and release checksums remain mandatory. Existing
image promotion uses the selected `GITHUB_SHA`, never a PR-head lookup. Journal
and six service numbered images retain the existing Linux/amd64 validation-image
path (Journal preferred musl); social-agent retains amd64/arm64, and Ledger
retains its Linux/x86_64 glibc/musl binaries and qualified AOT. No extra architecture
support is implied.

This automates the existing publication mechanics with ordinary Docker and the
repository `GITHUB_TOKEN`, without new credentials, trust or repository settings.
Publication is not transactional: if a producer fails, the run fails and other
producers may already have published. Preserve that outcome and inspect it before
any separately owner-approved recovery; do not automatically replay the workflow
or assume a failed run rolled back accepted writes. Success is publication,
not deployment or final consumer/hosting acceptance.

### Separate development behavior

- PR builds validate without pushing images. Branch pushes can publish SHA images;
  Journal also publishes a SHA image from automatic main CI. These are not releases.
- Six service workflows retain their existing direct-main service-change,
  non-`VERSION` multi-arch `latest` path. Main `VERSION` changes validate rather
  than automatically promote numbered tags. Service release promotion builds
  and consumes the selected main SHA image in the explicit release run.
- Social-agent main service/version CI retains its existing multi-arch `latest`
  publication, but emits a numbered tag only for explicit platform release.
  Thus development `latest` is not a numbered-release approval signal.
- Docs Pages deployment remains automatic on its existing main triggers, separate
  from platform release approval. No deployment/environment policy is changed.
- Recorder remains independently versioned and tag-triggered by
  `agent-recorder-v*`; platform dispatch does not release Recorder, CLI or Messenger.

## Hosting capabilities and settings

Repository-relative `github.repository` / `GITHUB_REPOSITORY` destinations stay
portable. The existing workflows require GitHub-hosted runners, repository
`GITHUB_TOKEN` access with the declared contents/packages permissions, release
asset writes, and Pages/OIDC deployment capability. They do not require Sandia
self-hosted runner labels. Changing a workflow file additionally requires the
publishing identity's **Workflows write** permission; Actions write alone is not
permission to edit workflow definitions.

Before final hosting acceptance, verify separately:

- Actions is enabled, permitted actions are allowed, and the workflow-token
  policy supports existing package/release producers.
- GHCR packages are owned/linked correctly, accessible to their workflows and
  publicly pullable where intended. A manifest or successful login alone does
  not qualify all layers, versions, architectures or visibility.
- Pages is configured for GitHub Actions, its environment accepts the authorized
  deployment, the homepage points to the Plurality site, and the docs/PDF URL
  actually serves the new build.
- Existing required checks, branch protection and release policy are understood;
  no policy removal or broad permission change is implied by this port.
- Recorder release artifacts are built in Plurality under their independent
  version stream at an explicitly authorized release transition; existing
  Sandia assets do not transfer automatically.

Missing settings permissions block only their dependent hosting steps. Record
an exact owner-operated setting or missing capability rather than guessing that
an inaccessible response means an empty configuration. Keep setting changes
reversible and separate from final release acceptance.

## Legacy Firewheel (unmaintained)

The owner has removed Firewheel from maintained v0.1 completion and hosting
requirements. Leave its existing source/references unchanged, without a version
hunt, replacement runtime/topology or legacy hosting work. Disable it only if a
concrete recorded failure actually breaks maintained work, not preemptively.
The following retained inventory is historical context, not an acceptance gate.
These adapters consume older external dependencies, not the modern Compose chain:

- `tests/network/firewheel/model-components/general-journal/INSTALL` clones
  `sandialabs/sync-services`, a different repository.
- `tests/network/firewheel/model-components/social-agent/INSTALL` pulls
  `ghcr.io/sandialabs/sync-analysis/social-agent` using a component-local
  `version.txt` that is not checked into this repository.

These baseline adapters already contain stale integration inputs. The general
installer requests `deploy/compose/general/compose.yaml`, whereas the inspected
external source at `5b1a7a0d0365f8d6aadaa9239b14a2754f7f0978` provides
`compose/general/docker-compose.yml` and the older general `1.2.3` image. That
Compose supports `PORT` and has no identity-provider service. The external
social-agent source at `ffafe350ed781ced47f1e31454340181e12c10c9` uses
`SECRET` / `x-sync-auth`, not the current monorepo agent's IdP login flow.
These observations identify pre-existing adapter/runtime differences; they do
not establish a working legacy installation or its exact deployed image.

Organization/hosting renaming does not itself require Kratos admin-port exposure
or a different network topology. Replacing these dependencies with the current
monorepo runtime is a separate adaptation, not part of this correction. No such
replacement, credential-policy change or topology change is made here.

No working legacy version or equivalent Plurality image is asserted. The owner
has explicitly left these inputs unchanged and outside maintained hosting scope;
no like-for-like Firewheel publication or portability claim is required.

## Existing database and rollback boundary

This port does not update running installations or add a cross-edition database
migration. Fresh Plurality deployments write the `0.1.0` Compose marker. Existing
exact Sandia `1.5.0`, `1.6.0` and `1.6.1` predecessor updates retain their explicit
`JOURNAL_UPDATE=1` installer path and advance that deployment marker only after
success. Unsupported/mismatched/unmarked state still fails closed. In particular,
a Sandia `1.6.2` deployment marker is not automatically relabeled `0.1.0`; no new
admission or marker-conversion procedure is introduced. Keep existing runtimes
unchanged unless an independently approved deployment procedure applies.

Reverting this source port does not undo package/release/settings publication,
or make a database opened by another runtime safe to relabel. Preserve historical
artifacts and exact source/volume/image identities; do not overwrite old releases
or treat an older database snapshot as a universal rollback.
