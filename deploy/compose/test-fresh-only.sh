#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
platform_version=$(cat "$repo_root/VERSION")

check_runner() {
    runner=$1
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT INT TERM
    mkdir -p "$work/lisp"
    for file in root standard log-chain tree ledger federation authorization interface; do
        printf '(%s-class-marker)\n' "$file" > "$work/lisp/$file.scm"
    done
    cp "$repo_root/$runner" "$work/run.sh"
    cat > "$work/journal-sdk" <<'MOCK'
#!/bin/sh
if [ "${1:-}" = "-e" ]; then
    cat >/dev/null
    printf 'install\n' >> calls.log
    mkdir -p database
    : > database/CURRENT
    if [ "${MOCK_INSTALL_STATUS:-0}" != 0 ]; then
        exit "$MOCK_INSTALL_STATUS"
    fi
    printf '%s\n' "${MOCK_INSTALL_RESULT:-\"Installed interface\"}"
    exit 0
fi
printf 'server\n' >> calls.log
MOCK
    chmod +x "$work/journal-sdk"

    run() {
        update=${1:-0}
        install_result=${2:-\"Installed interface\"}
        install_status=${3:-0}
        (cd "$work" && SECRET=test INTERFACE_SECRET=interface-test WINDOW=8 PERIOD=2 RUST_LOG=error \
            LISP_DIR="$work/lisp" SYNC_WEB_VERSION="$platform_version" JOURNAL_UPDATE="$update" \
            MOCK_INSTALL_RESULT="$install_result" MOCK_INSTALL_STATUS="$install_status" sh ./run.sh)
    }

    # A fresh database is marked and served only after the installer returns
    # the one exact success value.
    run
    test "$(cat "$work/database/.sync-web-version")" = "$platform_version"
    test "$(grep -c '^install$' "$work/calls.log")" = 1
    test "$(grep -c '^server$' "$work/calls.log")" = 1

    # JOURNAL_UPDATE=0 is an ordinary reopen: it validates the environment and
    # version marker but does not reinstall or interpret mounted source.
    run
    test "$(grep -c '^install$' "$work/calls.log")" = 1
    test "$(grep -c '^server$' "$work/calls.log")" = 2

    # JOURNAL_UPDATE=1 on the current marker still invokes the installer; its
    # fail-closed result cannot launch another server or alter the marker.
    if run 1 "(error 'upgrade-error \"stale-secret-payload\")" > /dev/null 2>"$work/failure.err"; then
        echo "FAIL: JOURNAL_UPDATE=1 Scheme error succeeded for $runner" >&2
        exit 1
    fi
    test "$(grep -c '^server$' "$work/calls.log")" = 2
    ! grep -Fq 'stale-secret-payload' "$work/failure.err"
    ! grep -Fq 'interface-test' "$work/failure.err"
    if run 1 '"Installed interface"' 9 > /dev/null 2>"$work/failure.err"; then
        echo "FAIL: JOURNAL_UPDATE=1 process error succeeded for $runner" >&2
        exit 1
    fi
    test "$(grep -c '^server$' "$work/calls.log")" = 2

    reset_fresh() {
        rm -rf "$work/database"
        : > "$work/calls.log"
        rm -f "$work/failure.err"
    }

    # Fresh Scheme errors, malformed values, and process errors leave no marker
    # and never launch the server; diagnostics omit returned and secret content.
    reset_fresh
    if run 0 "(error 'upgrade-error \"stale-secret-payload\")" > /dev/null 2>"$work/failure.err"; then
        echo "FAIL: fresh Scheme error succeeded for $runner" >&2
        exit 1
    fi
    test ! -f "$work/database/.sync-web-version"
    ! grep -q '^server$' "$work/calls.log"
    ! grep -Fq 'stale-secret-payload' "$work/failure.err"
    ! grep -Fq 'interface-test' "$work/failure.err"

    reset_fresh
    if run 0 '(malformed installer result)' > /dev/null 2>"$work/failure.err"; then
        echo "FAIL: malformed installer result succeeded for $runner" >&2
        exit 1
    fi
    test ! -f "$work/database/.sync-web-version"
    ! grep -q '^server$' "$work/calls.log"

    reset_fresh
    if run 0 '"Installed interface"' 7 > /dev/null 2>"$work/failure.err"; then
        echo "FAIL: fresh process error succeeded for $runner" >&2
        exit 1
    fi
    test ! -f "$work/database/.sync-web-version"
    ! grep -q '^server$' "$work/calls.log"

    # Existing unmarked or unsupported-version state remains fail-closed.
    rm -rf "$work/database"
    mkdir -p "$work/database"
    : > "$work/database/LEGACY"
    if run > /dev/null 2>&1; then
        echo "FAIL: unmarked legacy database opened for $runner" >&2
        exit 1
    fi
    printf 'mismatched-version\n' > "$work/database/.sync-web-version"
    if run > /dev/null 2>&1; then
        echo "FAIL: mismatched database version opened for $runner" >&2
        exit 1
    fi

    # The new distribution number does not implicitly admit or relabel a
    # Sandia 1.6.2 volume, even with the explicit update switch.
    printf '1.6.2\n' > "$work/database/.sync-web-version"
    for update in 0 1; do
        if run "$update" > /dev/null 2>&1; then
            echo "FAIL: Sandia 1.6.2 database relabeled for $runner" >&2
            exit 1
        fi
        test "$(cat "$work/database/.sync-web-version")" = 1.6.2
    done

    # Supported Sandia 1.5.0/1.6.0/1.6.1 -> Plurality transitions require the explicit update
    # switch and advance the marker only after exact installer success.
    printf '1.5.0\n' > "$work/database/.sync-web-version"
    if run 0 > /dev/null 2>&1; then
        echo "FAIL: 1.5.0 database opened without update for $runner" >&2
        exit 1
    fi
    before_servers=$(grep -c '^server$' "$work/calls.log" || true)
    run 1
    test "$(cat "$work/database/.sync-web-version")" = "$platform_version"
    test "$(grep -c '^server$' "$work/calls.log")" = $((before_servers + 1))

    printf '1.6.0\n' > "$work/database/.sync-web-version"
    if run 0 > /dev/null 2>&1; then
        echo "FAIL: 1.6.0 database opened without update for $runner" >&2
        exit 1
    fi
    before_servers=$(grep -c '^server$' "$work/calls.log" || true)
    run 1
    test "$(cat "$work/database/.sync-web-version")" = "$platform_version"
    test "$(grep -c '^server$' "$work/calls.log")" = $((before_servers + 1))

    printf '1.6.1\n' > "$work/database/.sync-web-version"
    if run 0 > /dev/null 2>&1; then
        echo "FAIL: 1.6.1 database opened without update for $runner" >&2
        exit 1
    fi
    before_servers=$(grep -c '^server$' "$work/calls.log" || true)
    run 1
    test "$(cat "$work/database/.sync-web-version")" = "$platform_version"
    test "$(grep -c '^server$' "$work/calls.log")" = $((before_servers + 1))

    printf '1.5.0\n' > "$work/database/.sync-web-version"
    if run 1 "(error 'upgrade-error \"stale-secret-payload\")" > /dev/null 2>"$work/failure.err"; then
        echo "FAIL: failed 1.5.0 migration succeeded for $runner" >&2
        exit 1
    fi
    test "$(cat "$work/database/.sync-web-version")" = 1.5.0
    ! grep -Fq 'stale-secret-payload' "$work/failure.err"

    # Ordinary reopen still enforces required runtime environment variables.
    rm -rf "$work/database"
    run
    servers=$(grep -c '^server$' "$work/calls.log")
    if (cd "$work" && INTERFACE_SECRET=interface-test WINDOW=8 PERIOD=2 RUST_LOG=error \
        LISP_DIR="$work/lisp" SYNC_WEB_VERSION="$platform_version" JOURNAL_UPDATE=0 sh ./run.sh) \
        > /dev/null 2>"$work/failure.err"; then
        echo "FAIL: reopen without root secret succeeded for $runner" >&2
        exit 1
    fi
    test "$(grep -c '^server$' "$work/calls.log")" = "$servers"

    rm -rf "$work"
    trap - EXIT INT TERM
}

check_runner deploy/compose/general/run.sh
check_runner deploy/compose/ledger/run.sh

echo "PASS: compose runners install, update supported predecessors, and reopen fail closed"
