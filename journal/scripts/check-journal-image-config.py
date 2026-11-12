#!/usr/bin/env python3
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCK = "d69e38d29ecabd5ae3d62cf2a7c018b292a9e3a40102a0547971bf0d03e34854"
PUBLISH_COMMAND = (
    "python3 journal/scripts/publish-journal-image.py "
    "target/journal-image-evidence/image.tar target/journal-image-evidence "
    "target/qualified-kernel/kernel.wasmer"
)
PUBLISH_STEP = (
    "      - name: Push SHA-tagged validation image\n"
    "        if: github.event_name != 'pull_request'\n"
    "        env:\n"
    "          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n"
    f"        run: {PUBLISH_COMMAND}\n"
)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def require(text: str, values: tuple[str, ...], name: str) -> None:
    for value in values:
        if value not in text:
            fail(f"{name} is missing {value}")


def ledger_contract_errors(text: str) -> list[str]:
    errors = []
    expected_rows = [("glibc", "linux-x86_64"), ("musl", "linux-x86_64-musl")]
    marker = "      matrix:\n        include:\n"
    if marker not in text or "    runs-on:" not in text.split(marker, 1)[-1]:
        errors.append("ledger release workflow must contain the release matrix")
    else:
        matrix = text.split(marker, 1)[1].split("    runs-on:", 1)[0]
        rows = re.findall(
            r"^          - variant: ([^\s]+)\n            target: ([^\s]+)$",
            matrix,
            re.MULTILINE,
        )
        variant_lines = re.findall(r"^\s*- variant:", matrix, re.MULTILINE)
        if rows != expected_rows or len(variant_lines) != len(expected_rows):
            errors.append("ledger release workflow matrix must be exactly glibc and musl")
    shell = " ".join(text.replace("\\\n", "").split())
    smoke = (
        'test "$(/tmp/ledger --database /tmp/ledger-smoke/db '
        '--secret release-smoke-root '
        '--evaluate "((function size) (arguments ()))")" = 0'
    )
    if shell.count(smoke) != 1:
        errors.append("ledger release workflow must require exactly one installed Interface size = 0 smoke")
    if shell.count("/tmp/ledger --database /tmp/ledger-smoke/db") != 1:
        errors.append("ledger release workflow must contain exactly one fresh Ledger invocation")
    old_smoke = (
        '/tmp/ledger --database /tmp/ledger-smoke/db '
        '--secret release-smoke-root --evaluate "(+ 1 2)"'
    )
    if old_smoke in shell:
        errors.append("ledger release workflow must not evaluate raw arithmetic after installation")
    return errors


def workflow_job(text: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n.*?(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(0) if match else ""


def journal_contract_errors(text: str) -> list[str]:
    errors = []
    build_job = " ".join(
        workflow_job(text, "build-journal-sdk").replace("\\\n", "").split()
    )
    build = (
        "journal/scripts/build-journal-image --variant musl "
        "--kernel target/qualified-kernel/kernel.wasmer "
        "--tag ghcr.io/${{ github.repository }}/journal-sdk:sha-${{ github.sha }}-musl "
        "--evidence-dir target/journal-image-evidence"
    )
    push = " ".join(PUBLISH_STEP.split())
    archive = (
        "docker save --output target/journal-image-evidence/image.tar "
        "ghcr.io/${{ github.repository }}/journal-sdk:sha-${{ github.sha }}-musl"
    )
    retain = (
        "uses: actions/upload-artifact@v4 with: name: journal-image-provenance "
        "path: target/journal-image-evidence if-no-files-found: error"
    )
    verify = 'journal/scripts/check-wasmer-kernel-provenance.py target/qualified-kernel "$GITHUB_SHA"'
    if build_job.count(verify) != 1:
        errors.append("build-journal-sdk job must verify exactly one tested AOT bundle")
    if build_job.count(build) != 1:
        errors.append("build-journal-sdk job must contain exactly one musl build contract")
    if build_job.count(push) != 1:
        errors.append("build-journal-sdk job must contain exactly one guarded musl push contract")
    if build_job.count(archive) != 1 or build_job.count(retain) != 1 or not (
        0 <= build_job.find(build) < build_job.find(archive) < build_job.find(retain) < build_job.find(push)
    ):
        errors.append("build-journal-sdk job must retain the complete musl archive before publication")
    tag_job = " ".join(workflow_job(text, "tag-version").split())
    guard = (
        "if: always() && github.ref == 'refs/heads/main' && "
        "needs.changes.outputs.version == 'true' && "
        "(needs.build-journal-sdk.result == 'success' || "
        "needs.build-journal-sdk.result == 'skipped')"
    )
    promote = "run: .github/scripts/promote-image.sh journal-sdk VERSION musl preferred"
    if tag_job.count(guard) != 1 or tag_job.count(promote) != 1:
        errors.append("tag-version job must guard preferred musl promotion")
    for value in (
        "build-journal-image --variant glibc",
        "journal-sdk:sha-${{ github.sha }}-glibc",
        "promote-image.sh journal-sdk VERSION glibc",
    ):
        if value in text:
            errors.append(f"Journal container workflow must not build or publish glibc images: {value}")
    return errors


def require_mutation_rejected(
    contract: str,
    name: str,
    original: str,
    mutation: str,
    validator,
    expected: str,
) -> None:
    if mutation == original:
        fail(f"{contract} checker self-test did not apply {name} mutation")
    if not any(expected in error for error in validator(mutation)):
        fail(f"{contract} checker self-test accepted {name} mutation")


musl = (ROOT / "Dockerfile.musl").read_text()
glibc = (ROOT / "Dockerfile.glibc").read_text()
build = (ROOT / "scripts" / "build-journal-image").read_text()
ledger_workflow = (ROOT.parent / ".github" / "workflows" / "ledger.yml").read_text()
ignore = {line.strip() for line in (ROOT / ".dockerignore").read_text().splitlines()}
common = (
    "cargo build --release --locked --features wasmer-evaluator --bin journal-sdk --bin ledger",
    "RUST_TEST_THREADS=1 cargo test --release --locked --features wasmer-evaluator",
    "SYNC_WEB_WASMER_KERNEL_SHA256=$AOT_SHA256",
    'sync-web.aot-sha256="$AOT_SHA256"',
    f'sync-web.lock-sha256="{LOCK}"',
    'test "$TARGETARCH" = amd64',
    'org.opencontainers.image.revision="$SOURCE_COMMIT"',
    'sync-web.source-tree="$SOURCE_TREE"',
    'sync-web.source-inputs-sha256="$SOURCE_INPUTS_SHA256"',
    'ENTRYPOINT ["/srv/journal-sdk"]',
)
require(musl, common, "musl Dockerfile")
require(glibc, common, "glibc Dockerfile")
for name, dockerfile in (("musl", musl), ("glibc", glibc)):
    if dockerfile.count("ARG AOT_SHA256") != 2:
        fail(f"{name} Dockerfile must declare the derived AOT hash in both stages")
    if dockerfile.count("SYNC_WEB_WASMER_KERNEL_SHA256=$AOT_SHA256") != 2:
        fail(f"{name} Dockerfile must bind both evaluator environments to the derived AOT hash")
    if dockerfile.count('= "$AOT_SHA256" &&') != 2:
        fail(f"{name} Dockerfile must verify builder and runtime AOT files")
if "SYNC_WEB_EVALUATOR" in musl or "SYNC_WEB_EVALUATOR" in glibc:
    fail("Journal images must not expose a request-evaluator selector")
require(
    musl,
    (
        "docker.io/library/rust@sha256:5dc2af9dd547c33f64d5fc1d299ab93b51f39eaa16c426c476b990ce6caf5b3e",
        "docker.io/library/alpine@sha256:25109184c71bdad752c8312a8623239686a9a2071e8825f20acb8f2198c3f659",
        "CXX=g++",
        "COPY journal/scripts/llvm-config-musl-static /src/scripts/llvm-config-musl-static",
        "LLVM_CONFIG_PATH=/src/scripts/llvm-config-musl-static",
        "g++ -x c++ -std=c++17 - -o /tmp/cxx-probe",
        "openssl-libs-static=3.5.9-r0",
        "scripts/check-clang-static-toolchain.sh",
        "scripts/check-clang-feature-graph.sh musl",
        'sync-web.variant="alpine-native-musl"',
    ),
    "musl Dockerfile",
)
require(
    glibc,
    (
        "docker.io/library/rust@sha256:c993d32d95cc146bd12c84d66f0b924a6a96f3988325f39c144f2f9893dea120",
        "docker.io/library/debian@sha256:74a21da88cf4b2e8fde34558376153c5cd80b00ca81da2e659387e76524edc73",
        "scripts/check-clang-feature-graph.sh non-musl",
        'sync-web.variant="debian-bookworm-slim-glibc"',
    ),
    "glibc Dockerfile",
)
if "llvm-config-musl-static" in glibc:
    fail("glibc Dockerfile must not select the musl llvm-config wrapper")
require(
    build,
    (
        "git -C \"$repo_dir\" archive \"$commit\"",
        'build --no-cache "${pull[@]}" "${format[@]}"',
        "pull=(--pull)",
        "pull=(--pull=never)",
        "--build-arg TARGETARCH=amd64",
        '--build-arg AOT_SHA256="$aot_sha"',
        f"[[ $lock_sha == {LOCK} ]]",
        "[[ $aot_sha =~ ^[0-9a-f]{64}$ ]]",
    ),
    "image build script",
)
if ".dockerignore" in ignore or "Dockerfile" in ignore or "kernel.wasmer" in ignore:
    fail("Docker context must include image configuration and kernel.wasmer")
require(
    ledger_workflow,
    (
        "docker build --pull --target builder",
        '--build-arg AOT_SHA256="$aot_sha"',
        'journal/scripts/check-wasmer-kernel-provenance.py target/qualified-kernel "$GITHUB_SHA"',
        "docker run --rm --entrypoint /bin/sh",
        '/tmp/journal-sdk --evaluate "(+ 1 2)"',
        "/tmp/ledger --database /tmp/ledger-smoke/db",
    ),
    "ledger release workflow",
)
for error in ledger_contract_errors(ledger_workflow):
    fail(error)
rows = {
    "glibc": "          - variant: glibc\n            target: linux-x86_64\n",
    "musl": "          - variant: musl\n            target: linux-x86_64-musl\n",
}
ledger_mutations = (
    ("missing glibc row", ledger_workflow.replace(rows["glibc"], ""), "matrix"),
    ("missing musl row", ledger_workflow.replace(rows["musl"], ""), "matrix"),
    ("extra arbitrary row", ledger_workflow.replace(rows["musl"], rows["musl"] + "          - variant: debug\n            target: debug\n"), "matrix"),
    ("extra altered glibc row", ledger_workflow.replace(rows["glibc"], rows["glibc"] + "          - variant: glibc\n            target: linux-x86_64-extra\n"), "matrix"),
    (
        "wrong Interface size expectation",
        ledger_workflow.replace(
            '--evaluate "((function size) (arguments ()))")" = 0',
            '--evaluate "((function size) (arguments ()))")" = 1',
        ),
        "size = 0",
    ),
    (
        "restored raw Ledger arithmetic",
        ledger_workflow
        + '\n/tmp/ledger --database /tmp/ledger-smoke/db --secret release-smoke-root --evaluate "(+ 1 2)"\n',
        "raw arithmetic",
    ),
)
for name, mutation, expected in ledger_mutations:
    require_mutation_rejected(
        "ledger contract",
        name,
        ledger_workflow,
        mutation,
        ledger_contract_errors,
        expected,
    )
if "dist/ledger-${{ matrix.target }} --version" in ledger_workflow:
    fail("ledger release workflow must not execute extracted musl binaries on Ubuntu")

journal_workflow = (ROOT.parent / ".github" / "workflows" / "journal.yml").read_text()
for error in journal_contract_errors(journal_workflow):
    fail(error)
journal_mutations = (
    (
        "wrong musl build tag",
        journal_workflow.replace(
            "--tag ghcr.io/${{ github.repository }}/journal-sdk:sha-${{ github.sha }}-musl \\",
            "--tag ghcr.io/${{ github.repository }}/journal-sdk:sha-${{ github.sha }}-wrong \\",
        ),
        "musl build contract",
    ),
    (
        "wrong publisher archive binding",
        journal_workflow.replace(PUBLISH_COMMAND, PUBLISH_COMMAND.replace("image.tar", "wrong.tar")),
        "musl push contract",
    ),
    (
        "missing musl push",
        journal_workflow.replace(PUBLISH_STEP, ""),
        "musl push contract",
    ),
    (
        "wrong preferred promotion",
        journal_workflow.replace(
            "promote-image.sh journal-sdk VERSION musl preferred",
            "promote-image.sh journal-sdk VERSION musl",
        ),
        "tag-version job",
    ),
    (
        "restored glibc build",
        journal_workflow + "\nbuild-journal-image --variant glibc\n",
        "glibc images",
    ),
)
journal_mutations += (
    (
        "missing complete image export",
        journal_workflow.replace("docker save --output", "echo export-disabled --output"),
        "retain the complete musl archive",
    ),
    (
        "publication before retention",
        journal_workflow.replace(PUBLISH_STEP, "").replace(
            "      - name: Retain complete image with build evidence\n",
            PUBLISH_STEP + "      - name: Retain complete image with build evidence\n",
        ),
        "retain the complete musl archive",
    ),
    (
        "missing push non-PR guard",
        journal_workflow.replace(PUBLISH_STEP, PUBLISH_STEP.replace("        if: github.event_name != 'pull_request'\n", "")),
        "guarded musl push contract",
    ),
    (
        "weakened promotion job guard",
        journal_workflow.replace(
            "    if: always() && github.ref == 'refs/heads/main' && needs.changes.outputs.version == 'true' && (needs.build-journal-sdk.result == 'success' || needs.build-journal-sdk.result == 'skipped')",
            "    if: always()",
        ),
        "tag-version job",
    ),
    (
        "relocated promotion contract",
        journal_workflow.replace(
            "    if: always() && github.ref == 'refs/heads/main' && needs.changes.outputs.version == 'true' && (needs.build-journal-sdk.result == 'success' || needs.build-journal-sdk.result == 'skipped')",
            "    if: always()",
        ).replace(
            "        run: .github/scripts/promote-image.sh journal-sdk VERSION musl preferred",
            "        run: echo promotion-disabled",
        )
        + "\n  promotion-decoy:\n"
        + "    if: always() && github.ref == 'refs/heads/main' && needs.changes.outputs.version == 'true' && (needs.build-journal-sdk.result == 'success' || needs.build-journal-sdk.result == 'skipped')\n"
        + "    steps:\n"
        + "      - run: .github/scripts/promote-image.sh journal-sdk VERSION musl preferred\n",
        "tag-version job",
    ),
)
for name, mutation, expected in journal_mutations:
    require_mutation_rejected(
        "Journal container contract",
        name,
        journal_workflow,
        mutation,
        journal_contract_errors,
        expected,
    )
print("Journal musl runtime image and glibc/musl binary-builder contracts are exact")
