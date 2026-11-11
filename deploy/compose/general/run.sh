#!/bin/sh
set -e

PLATFORM_VERSION="${SYNC_WEB_VERSION:-}"
VERSION_MARKER="database/.sync-web-version"

if [ -z "$PLATFORM_VERSION" ]; then
    echo "Must set the SYNC_WEB_VERSION variable" >&2
    exit 1
fi

if [ -z "$SECRET" ]; then
    echo "Must set the SECRET variable" >&2
    exit 1
fi

if [ -z "$INTERFACE_SECRET" ]; then
    echo "Must set the INTERFACE_SECRET variable" >&2
    exit 1
fi

if [ -z "$WINDOW" ]; then
    WINDOW="#f"
fi

if [ -z "$JOURNAL_UPDATE" ]; then
    JOURNAL_UPDATE=0
fi

resolve_lisp_file() {
    filename="$1"

    if [ -n "$LISP_DIR" ]; then
        path="$LISP_DIR/$filename"
        if [ ! -f "$path" ]; then
            echo "Missing required Lisp file: $path"
            exit 1
        fi
        echo "$path"
        return 0
    fi

    if [ ! -f "$filename" ]; then
        echo "Missing required Lisp file: $filename"
        exit 1
    fi
    echo "$filename"
}

build_admins_list() {
    result=""
    OLD_IFS="$IFS"
    IFS=","
    for name in ${INTERFACE_ADMINS:-}; do
        if [ -n "$result" ]; then
            result="$result "
        fi
        result="$result(*state* $name)"
    done
    IFS="$OLD_IFS"
    echo "($result)"
}

checked_evaluate() {
    label="$1"
    expected="$2"
    expr="$3"
    if ! output=$(printf '%s' "$expr" | RUST_LOG=$RUST_LOG ./journal-sdk -e - -d database); then
        echo "$label failed; result omitted" >&2
        return 1
    fi
    if [ "$output" != "$expected" ]; then
        echo "$label failed; result omitted" >&2
        return 1
    fi
}

run_startup() {
    clear_flag="$1"
    root=$( cat "$(resolve_lisp_file root.scm)" )
    standard=$( cat "$(resolve_lisp_file standard.scm)" )
    chain=$( cat "$(resolve_lisp_file log-chain.scm)" )
    tree=$( cat "$(resolve_lisp_file tree.scm)" )
    ledger=$( cat "$(resolve_lisp_file ledger.scm)" )
    federation=$( cat "$(resolve_lisp_file federation.scm)" )
    authorization=$( cat "$(resolve_lisp_file authorization.scm)" )
    interface=$( cat "$(resolve_lisp_file interface.scm)" )
    admins=$( build_admins_list )
    origin="${ORIGIN:-http://localhost:8192}"
    interface_url="${INTERFACE:-$origin/api/v1/journal/interface}"
    journal_name="${JOURNAL_NAME:-$interface_url}"
    config="((clear? $clear_flag) (root-secret \"$SECRET\") (interface-secret \"$INTERFACE_SECRET\") (admins $admins) (window $WINDOW) (root $root) (interface \"$interface_url\") (name \"$journal_name\"))"
    expr="($interface $config '$standard '$chain '$tree '$ledger '$federation '$authorization)"
    if [ "$clear_flag" = "#f" ]; then
        expr="(*eval* \"$SECRET\" $expr)"
    fi
    checked_evaluate "Journal record installation" '"Installed interface"' "$expr"
}

write_version_marker=0
if [ -d database ] && [ -n "$(find database -mindepth 1 -print -quit 2>/dev/null)" ]; then
    if [ ! -f "$VERSION_MARKER" ]; then
        echo "Existing database has no supported Sync Web version marker" >&2
        exit 1
    fi
    installed_version=$(cat "$VERSION_MARKER")
    if [ "$installed_version" != "$PLATFORM_VERSION" ]; then
        if [ "$PLATFORM_VERSION" != "0.1.0" ] || \
           { [ "$installed_version" != "1.5.0" ] && [ "$installed_version" != "1.6.0" ] && [ "$installed_version" != "1.6.1" ]; } || \
           [ "$JOURNAL_UPDATE" != "1" ]; then
            echo "Database version $installed_version cannot be opened by $PLATFORM_VERSION" >&2
            exit 1
        fi
        write_version_marker=1
    fi
    if [ "$JOURNAL_UPDATE" = "1" ]; then
        run_startup "#f"
    fi
else
    run_startup "#t"
    write_version_marker=1
fi

if [ "$write_version_marker" = "1" ]; then
    printf '%s\n' "$PLATFORM_VERSION" > "$VERSION_MARKER"
fi

step="(*step* \"$SECRET\")"
RUST_LOG=$RUST_LOG ./journal-sdk -p 80 -c $PERIOD -s "$step" -d database
