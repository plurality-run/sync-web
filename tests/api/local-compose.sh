#!/bin/sh
set -eu

MODE="${1:-up}"
if [ "$MODE" != "up" ] && [ "$MODE" != "smoke" ] && [ "$MODE" != "build" ]; then
    echo "Usage: $0 [build|up|smoke]"
    exit 1
fi

ROOT_DIR="$(git -C "$(dirname -- "$0")" rev-parse --show-toplevel)"
COMPOSE_DIR="$ROOT_DIR/deploy/compose/general"
COMPOSE_FILE="$COMPOSE_DIR/compose.yaml"

if [ -z "${CONTAINER_RUNTIME+x}" ]; then
    if command -v docker >/dev/null 2>&1; then
        CONTAINER_RUNTIME="docker"
    elif command -v podman >/dev/null 2>&1; then
        CONTAINER_RUNTIME="podman"
    else
        echo "FAIL: neither docker nor podman is available" >&2
        exit 1
    fi
fi

if [ -z "${CONTAINER_COMPOSE+x}" ]; then
    case "$CONTAINER_RUNTIME" in
        docker)
            CONTAINER_COMPOSE="docker compose"
            ;;
        podman)
            if podman compose version >/dev/null 2>&1; then
                CONTAINER_COMPOSE="podman compose"
            elif command -v podman-compose >/dev/null 2>&1; then
                CONTAINER_COMPOSE="podman-compose"
            else
                CONTAINER_COMPOSE="podman compose"
            fi
            ;;
        *)
            CONTAINER_COMPOSE="$CONTAINER_RUNTIME compose"
            ;;
    esac
fi

HTTP_PORT="${HTTP_PORT:-${PORT:-8192}}"
HTTPS_PORT="${HTTPS_PORT:-8193}"
ORIGIN="${ORIGIN:-http://localhost:$HTTP_PORT}"
SECRET="${SECRET:-root-password}"
INTERFACE_SECRET="${INTERFACE_SECRET:-interface-password}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin-pass}"
PERIOD="${PERIOD:-8}"
WINDOW="${WINDOW:-1024}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-60}"
CONNECT_TIMEOUT_SECONDS="${CONNECT_TIMEOUT_SECONDS:-2}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-5}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-sync-local}"
LOCAL_COMPOSE_FORCE_HTTP="${LOCAL_COMPOSE_FORCE_HTTP:-1}"
DOCKER_PLATFORM="${DOCKER_PLATFORM:-}"

LOCAL_COMPOSE_SKIP_FILE_SYSTEM="${LOCAL_COMPOSE_SKIP_FILE_SYSTEM:-0}"
LOCAL_COMPOSE_SKIP_BUILD="${LOCAL_COMPOSE_SKIP_BUILD:-0}"
IMAGE_MANIFEST="${IMAGE_MANIFEST:-$ROOT_DIR/target/release-qa/local-images.json}"

if [ "$CONTAINER_RUNTIME" = "docker" ]; then
    COMPOSE_GLOBAL_ARGS="${COMPOSE_GLOBAL_ARGS:---ansi always}"
    COMPOSE_UP_ARGS="${COMPOSE_UP_ARGS:---pull never}"
else
    COMPOSE_GLOBAL_ARGS="${COMPOSE_GLOBAL_ARGS:-}"
    COMPOSE_UP_ARGS="${COMPOSE_UP_ARGS:-}"
fi

cleanup_mode="down"

VERSION="$(cat "$ROOT_DIR/VERSION")"
SYNC_WEB_VERSION="$VERSION"

JOURNAL_SDK_REMOTE_TAG="ghcr.io/plurality-run/sync-web/journal-sdk:$VERSION"
GATEWAY_REMOTE_TAG="ghcr.io/plurality-run/sync-web/gateway:$VERSION"
EXPLORER_REMOTE_TAG="ghcr.io/plurality-run/sync-web/explorer:$VERSION"
WORKBENCH_REMOTE_TAG="ghcr.io/plurality-run/sync-web/workbench:$VERSION"
ROUTER_REMOTE_TAG="ghcr.io/plurality-run/sync-web/router:$VERSION"
IDENTITY_PROVIDER_REMOTE_TAG="ghcr.io/plurality-run/sync-web/identity-provider:$VERSION"
FILE_SYSTEM_REMOTE_TAG="ghcr.io/plurality-run/sync-web/file-system:$VERSION"

JOURNAL_SDK_LOCAL_TAG="sync-web/local-journal-sdk:$VERSION"
GATEWAY_LOCAL_TAG="sync-web/local-gateway:$VERSION"
EXPLORER_LOCAL_TAG="sync-web/local-explorer:$VERSION"
WORKBENCH_LOCAL_TAG="sync-web/local-workbench:$VERSION"
ROUTER_LOCAL_TAG="sync-web/local-router:$VERSION"
IDENTITY_PROVIDER_LOCAL_TAG="sync-web/local-identity-provider:$VERSION"
FILE_SYSTEM_LOCAL_TAG="sync-web/local-file-system:$VERSION"
FILE_SYSTEM_IMAGE="${FILE_SYSTEM_IMAGE:-$FILE_SYSTEM_REMOTE_TAG}"

dc() {
    $CONTAINER_COMPOSE -f "$COMPOSE_FILE" "$@"
}

validate_declared_volume_names() {
    input_path="$1"
    output_path="$2"
    awk '
        NF != 1 || $1 !~ /^[A-Za-z0-9][A-Za-z0-9_.-]*$/ {
            print "FAIL: invalid declared Compose volume name: " $0 > "/dev/stderr"
            failed = 1
            next
        }
        seen[$1]++ {
            print "FAIL: duplicate declared Compose volume name: " $1 > "/dev/stderr"
            failed = 1
            next
        }
        { print $1 }
        END { if (failed) exit 1 }
    ' "$input_path" > "$output_path"
}

parse_normalized_declared_volumes() {
    input_path="$1"
    output_path="$2"
    awk '
        function fail(message) {
            print "FAIL: malformed normalized top-level volumes mapping: " message > "/dev/stderr"
            failed = 1
        }
        /^[^ ]/ {
            if ($0 == "volumes:" || $0 == "volumes: {}") {
                if (found) fail("duplicate volumes section")
                found = 1
                in_volumes = ($0 == "volumes:")
                inline_empty = ($0 == "volumes: {}")
                next
            }
            if ($0 ~ /^volumes:/) {
                fail("unexpected volumes section shape: " $0)
                in_volumes = 0
                next
            }
            if (in_volumes) in_volumes = 0
            inline_empty = 0
            next
        }
        inline_empty && /^ / {
            fail("indented entry after empty inline mapping: " $0)
            next
        }
        in_volumes {
            if ($0 == "") next
            if ($0 !~ /^  [A-Za-z0-9][A-Za-z0-9_.-]*: null$/) {
                fail("unexpected entry or indentation: " $0)
                next
            }
            logical_name = $0
            sub(/^  /, "", logical_name)
            sub(/: null$/, "", logical_name)
            if (seen[logical_name]++) {
                fail("duplicate volume key: " logical_name)
                next
            }
            names[++name_count] = logical_name
        }
        END {
            if (failed) exit 1
            for (i = 1; i <= name_count; i++) print names[i]
        }
    ' "$input_path" > "$output_path"
}

declared_project_volumes() {
    discovery_dir="$(mktemp -d "${TMPDIR:-/tmp}/sync-compose-volumes.XXXXXX")" || return 1
    primary_out="$discovery_dir/primary.out"
    primary_err="$discovery_dir/primary.err"
    normalized_out="$discovery_dir/normalized.out"
    normalized_err="$discovery_dir/normalized.err"
    validated_out="$discovery_dir/validated.out"

    if dc config --volumes >"$primary_out" 2>"$primary_err"; then
        cat "$primary_err" >&2
        if validate_declared_volume_names "$primary_out" "$validated_out"; then
            cat "$validated_out"
            rm -rf "$discovery_dir"
            return 0
        fi
        command_status=$?
        rm -rf "$discovery_dir"
        return "$command_status"
    else
        command_status=$?
    fi
    cat "$primary_out" >&2
    cat "$primary_err" >&2
    if [ "$command_status" -ne 2 ] || ! grep -Eq '^podman-compose: error: unrecognized arguments: --volumes$' "$primary_err"; then
        rm -rf "$discovery_dir"
        return "$command_status"
    fi

    echo "Compose provider lacks 'config --volumes'; using bounded normalized-config volume discovery." >&2
    if dc config >"$normalized_out" 2>"$normalized_err"; then
        cat "$normalized_err" >&2
    else
        command_status=$?
        cat "$normalized_out" >&2
        cat "$normalized_err" >&2
        rm -rf "$discovery_dir"
        return "$command_status"
    fi

    if parse_normalized_declared_volumes "$normalized_out" "$validated_out"; then
        cat "$validated_out"
        rm -rf "$discovery_dir"
        return 0
    else
        command_status=$?
    fi
    rm -rf "$discovery_dir"
    return "$command_status"
}

has_existing_named_volumes() {
    names="$(declared_project_volumes 2>/dev/null || true)"
    if [ -z "$names" ]; then
        return 1
    fi
    for logical_name in $names; do
        full_name="${COMPOSE_PROJECT_NAME}_${logical_name}"
        if $CONTAINER_RUNTIME volume inspect "$full_name" >/dev/null 2>&1; then
            return 0
        fi
    done
    return 1
}

confirm_volume_wipe_if_needed() {
    if ! has_existing_named_volumes; then
        return 0
    fi
    echo "Existing compose volumes were found for project '$COMPOSE_PROJECT_NAME'."
    while :; do
        printf "Wipe existing volumes and continue? [y/n]: "
        IFS= read -r answer || true
        case "$(printf "%s" "$answer" | tr '[:upper:]' '[:lower:]')" in
            y|yes) return 0 ;;
            n|no)
                echo "Aborting."
                exit 1
                ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

remember_teardown_failure() {
    failure_status="$1"
    if [ "$failure_status" -eq 0 ]; then
        failure_status=1
    fi
    if [ "$teardown_status" -eq 0 ]; then
        teardown_status="$failure_status"
    fi
}

teardown_project() {
    teardown_status=0

    if declared_volumes="$(declared_project_volumes)"; then
        :
    else
        command_status=$?
        echo "FAIL: could not derive declared Compose volumes for project '$COMPOSE_PROJECT_NAME' (status $command_status)." >&2
        remember_teardown_failure "$command_status"
        declared_volumes=""
    fi

    echo "Stopping Compose project '$COMPOSE_PROJECT_NAME' with volume and orphan removal..."
    if dc $COMPOSE_GLOBAL_ARGS ${compose_profile_args:-} down -v --remove-orphans; then
        :
    else
        command_status=$?
        echo "FAIL: Compose down failed for project '$COMPOSE_PROJECT_NAME' (status $command_status)." >&2
        remember_teardown_failure "$command_status"
    fi

    if project_containers="$($CONTAINER_RUNTIME ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"; then
        if [ -n "$project_containers" ]; then
            for resource_id in $project_containers; do
                echo "FAIL: residual container for project '$COMPOSE_PROJECT_NAME': $resource_id" >&2
            done
            remember_teardown_failure 1
        fi
    else
        command_status=$?
        echo "FAIL: could not verify containers for project '$COMPOSE_PROJECT_NAME' (status $command_status)." >&2
        remember_teardown_failure "$command_status"
    fi

    if project_networks="$($CONTAINER_RUNTIME network ls -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"; then
        if [ -n "$project_networks" ]; then
            for resource_id in $project_networks; do
                echo "FAIL: residual network for project '$COMPOSE_PROJECT_NAME': $resource_id" >&2
            done
            remember_teardown_failure 1
        fi
    else
        command_status=$?
        echo "FAIL: could not verify networks for project '$COMPOSE_PROJECT_NAME' (status $command_status)." >&2
        remember_teardown_failure "$command_status"
    fi

    for logical_name in $declared_volumes; do
        full_name="${COMPOSE_PROJECT_NAME}_${logical_name}"
        if $CONTAINER_RUNTIME volume inspect "$full_name" >/dev/null 2>&1; then
            echo "Cleanup residue: declared volume '$full_name' remains after Compose down." >&2
            echo "Cleanup fallback: removing declared project volume '$full_name'." >&2
            if $CONTAINER_RUNTIME volume rm "$full_name"; then
                :
            else
                command_status=$?
                echo "FAIL: could not remove declared project volume '$full_name' (status $command_status)." >&2
                remember_teardown_failure "$command_status"
            fi
        fi
    done

    for logical_name in $declared_volumes; do
        full_name="${COMPOSE_PROJECT_NAME}_${logical_name}"
        if $CONTAINER_RUNTIME volume inspect "$full_name" >/dev/null 2>&1; then
            echo "FAIL: declared project volume remains after cleanup: $full_name" >&2
            remember_teardown_failure 1
        fi
    done

    return "$teardown_status"
}

cleanup() {
    primary_status=$?
    trap - EXIT INT TERM
    set +e

    cleanup_status=0
    if [ "$cleanup_mode" = "down" ]; then
        cleanup_mode="none"
        teardown_project
        cleanup_status=$?
    fi

    if [ "$cleanup_status" -ne 0 ]; then
        echo "FAIL: cleanup could not establish an empty project '$COMPOSE_PROJECT_NAME' (status $cleanup_status)." >&2
    fi
    if [ "$primary_status" -ne 0 ]; then
        exit "$primary_status"
    fi
    exit "$cleanup_status"
}

on_interrupt() {
    exit 130
}

trap cleanup EXIT
trap on_interrupt INT TERM

CUSTOM_SETUP="${CUSTOM_SETUP:-}"

if [ "$LOCAL_COMPOSE_FORCE_HTTP" = "1" ]; then
    TLS_STUB_DIR="/tmp/sync-services-local-compose"
    TLS_STUB_CERT="$TLS_STUB_DIR/http-only.crt"
    TLS_STUB_KEY="$TLS_STUB_DIR/http-only.key"
    mkdir -p "$TLS_STUB_DIR"
    printf "HTTP-only local-compose placeholder cert.\n" > "$TLS_STUB_CERT"
    printf "HTTP-only local-compose placeholder key.\n" > "$TLS_STUB_KEY"
    TLS_CERT_HOST_PATH="$TLS_STUB_CERT"
    TLS_KEY_HOST_PATH="$TLS_STUB_KEY"
fi

build_and_retag() {
    context="$1"
    local_tag="$2"
    remote_tag="$3"
    build_platform="${4:-$DOCKER_PLATFORM}"
    dockerfile="${5:-}"
    extra_build_arg="${6:-}"

    echo "Building $local_tag ..."

    set -- --build-arg "CUSTOM_SETUP=$CUSTOM_SETUP" -t "$local_tag"
    if [ -n "$extra_build_arg" ]; then
        set -- --build-arg "$extra_build_arg" "$@"
    fi
    if [ -n "$build_platform" ]; then
        set -- --platform "$build_platform" "$@"
    fi
    if [ -n "$dockerfile" ]; then
        set -- -f "$dockerfile" "$@"
    fi

    $CONTAINER_RUNTIME build "$@" "$context"

    echo "Tagging $local_tag as $remote_tag ..."
    $CONTAINER_RUNTIME tag "$local_tag" "$remote_tag"
}

image_manifest_arguments() {
    set -- \
        --image "$JOURNAL_SDK_REMOTE_TAG" \
        --image "$GATEWAY_REMOTE_TAG" \
        --image "$EXPLORER_REMOTE_TAG" \
        --image "$WORKBENCH_REMOTE_TAG" \
        --image "$ROUTER_REMOTE_TAG" \
        --image "$IDENTITY_PROVIDER_REMOTE_TAG"
    if [ "$LOCAL_COMPOSE_SKIP_FILE_SYSTEM" != "1" ]; then
        set -- "$@" --image "$FILE_SYSTEM_IMAGE"
    fi
    printf '%s\n' "$@"
}

if [ "$LOCAL_COMPOSE_SKIP_BUILD" != "1" ]; then
    : "${SYNC_WEB_WASMER_KERNEL:?set SYNC_WEB_WASMER_KERNEL to the qualified AOT artifact}"
    if [ "${LOCAL_COMPOSE_RELEASE_QA:-0}" = "1" ]; then
        CONTAINER_RUNTIME="$CONTAINER_RUNTIME" \
            "$ROOT_DIR/journal/scripts/build-journal-image" \
            --variant musl --kernel "$SYNC_WEB_WASMER_KERNEL" \
            --tag "$JOURNAL_SDK_LOCAL_TAG" \
            --evidence-dir "$ROOT_DIR/target/local-compose-journal-image"
    else
        cp "$SYNC_WEB_WASMER_KERNEL" "$ROOT_DIR/journal/kernel.wasmer"
        trap 'rm -f "$ROOT_DIR/journal/kernel.wasmer"; cleanup' EXIT
        $CONTAINER_RUNTIME build --build-arg TARGETARCH=amd64 \
            --build-arg SOURCE_COMMIT=local-dirty \
            --build-arg SOURCE_TREE=local-dirty \
            --build-arg SOURCE_INPUTS_SHA256=local-dirty \
            --build-arg AOT_SHA256="$(sha256sum "$ROOT_DIR/journal/kernel.wasmer" | awk '{print $1}')" \
            -f "$ROOT_DIR/journal/Dockerfile.musl" \
            -t "$JOURNAL_SDK_LOCAL_TAG" "$ROOT_DIR"
        rm -f "$ROOT_DIR/journal/kernel.wasmer"
        trap cleanup EXIT
    fi
    echo "Tagging $JOURNAL_SDK_LOCAL_TAG as $JOURNAL_SDK_REMOTE_TAG ..."
    $CONTAINER_RUNTIME tag "$JOURNAL_SDK_LOCAL_TAG" "$JOURNAL_SDK_REMOTE_TAG"
    build_and_retag "$ROOT_DIR/services/gateway" "$GATEWAY_LOCAL_TAG" "$GATEWAY_REMOTE_TAG"
    build_and_retag "$ROOT_DIR/services/explorer" "$EXPLORER_LOCAL_TAG" "$EXPLORER_REMOTE_TAG"
    build_and_retag "$ROOT_DIR/services/workbench" "$WORKBENCH_LOCAL_TAG" "$WORKBENCH_REMOTE_TAG"
    build_and_retag "$ROOT_DIR/services/router" "$ROUTER_LOCAL_TAG" "$ROUTER_REMOTE_TAG"
    build_and_retag "$ROOT_DIR/services/identity-provider" "$IDENTITY_PROVIDER_LOCAL_TAG" "$IDENTITY_PROVIDER_REMOTE_TAG"
    if [ "$LOCAL_COMPOSE_SKIP_FILE_SYSTEM" != "1" ]; then
        build_and_retag "$ROOT_DIR/services/file-system" "$FILE_SYSTEM_LOCAL_TAG" "$FILE_SYSTEM_REMOTE_TAG"
        echo "Tagging $FILE_SYSTEM_LOCAL_TAG as $FILE_SYSTEM_IMAGE ..."
        $CONTAINER_RUNTIME tag "$FILE_SYSTEM_LOCAL_TAG" "$FILE_SYSTEM_IMAGE"
    fi
    if [ "${LOCAL_COMPOSE_RELEASE_QA:-0}" = "1" ]; then
        mkdir -p "$(dirname "$IMAGE_MANIFEST")"
        # shellcheck disable=SC2046
        python3 "$ROOT_DIR/tests/release-qa/image_manifest.py" write \
            --manifest "$IMAGE_MANIFEST" --source-root "$ROOT_DIR" --runtime "$CONTAINER_RUNTIME" \
            $(image_manifest_arguments)
    fi
else
    [ -f "$IMAGE_MANIFEST" ] || {
        echo "Exact-tag repeat requires IMAGE_MANIFEST: $IMAGE_MANIFEST" >&2
        exit 2
    }
    python3 "$ROOT_DIR/tests/release-qa/image_manifest.py" verify \
        --manifest "$IMAGE_MANIFEST" --source-root "$ROOT_DIR" --runtime "$CONTAINER_RUNTIME"
    echo "Skipping local image builds; verified source-bound image identities."
fi

if [ "$MODE" = "build" ]; then
    echo "PASS: local images built and tagged."
    exit 0
fi

export SECRET INTERFACE_SECRET ADMIN_USERNAME ADMIN_PASSWORD PERIOD WINDOW HTTP_PORT ORIGIN HTTPS_PORT COMPOSE_PROJECT_NAME TLS_CERT_HOST_PATH TLS_KEY_HOST_PATH FILE_SYSTEM_IMAGE SYNC_WEB_VERSION

compose_profile_args="--profile explorer --profile workbench"
compose_up_services="journal explorer workbench identity-provider gateway router"
if [ "$LOCAL_COMPOSE_SKIP_FILE_SYSTEM" != "1" ]; then
    compose_profile_args="$compose_profile_args --profile file-system"
    compose_up_services="$compose_up_services file-system"
fi

confirm_volume_wipe_if_needed
echo "Starting from scratch: removing compose stack + volumes..."
cleanup_mode="none"
if teardown_project; then
    cleanup_mode="down"
else
    teardown_status=$?
    echo "FAIL: could not establish a clean initial Compose project '$COMPOSE_PROJECT_NAME' (status $teardown_status)." >&2
    exit "$teardown_status"
fi

wait_for_http() {
    url="$1"
    elapsed=0
    while [ "$elapsed" -lt "$TIMEOUT_SECONDS" ]; do
        if curl -fsS \
          --connect-timeout "$CONNECT_TIMEOUT_SECONDS" \
          --max-time "$REQUEST_TIMEOUT_SECONDS" \
          "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    echo "Timed out waiting for $url" >&2
    return 1
}

wait_for_admin_seed() {
    if [ -z "$ADMIN_USERNAME" ]; then
        return 0
    fi

    elapsed=0
    while [ "$elapsed" -lt "$TIMEOUT_SECONDS" ]; do
        logs="$(dc logs --no-color identity-provider 2>/dev/null || dc logs identity-provider 2>/dev/null || true)"
        if printf "%s" "$logs" | grep -Fq "Admin identity '$ADMIN_USERNAME' created" \
          || printf "%s" "$logs" | grep -Fq "Admin identity '$ADMIN_USERNAME' already exists"; then
            return 0
        fi
        if printf "%s" "$logs" | grep -Fq "Failed to create admin identity '$ADMIN_USERNAME'"; then
            echo "FAIL: identity-provider failed to seed admin identity '$ADMIN_USERNAME'" >&2
            return 1
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "FAIL: timed out waiting for identity-provider to seed admin identity '$ADMIN_USERNAME'" >&2
    return 1
}

api_post() {
    body="$1"
    curl -fsS \
      -H "Content-Type: application/json" \
      -d "$body" \
      "http://127.0.0.1:$HTTP_PORT/interface"
}

gateway_status() {
    method="$1"
    path="$2"
    shift 2
    curl -sS -o /dev/null -w "%{http_code}" -X "$method" "$@" "http://127.0.0.1:$HTTP_PORT$path"
}

gateway_get() {
    path="$1"
    shift
    curl -fsS "$@" "http://127.0.0.1:$HTTP_PORT$path"
}

if [ "$MODE" = "up" ]; then
    echo "Starting compose project '$COMPOSE_PROJECT_NAME' on HTTP $HTTP_PORT / HTTPS $HTTPS_PORT in up mode (Ctrl+C to stop)..."
    dc $COMPOSE_GLOBAL_ARGS $compose_profile_args up $COMPOSE_UP_ARGS $compose_up_services
    exit 0
fi

echo "Starting compose project '$COMPOSE_PROJECT_NAME' on HTTP $HTTP_PORT / HTTPS $HTTPS_PORT in smoke mode..."
dc $COMPOSE_GLOBAL_ARGS $compose_profile_args up -d $COMPOSE_UP_ARGS $compose_up_services

echo "Waiting for routes..."
wait_for_http "http://127.0.0.1:$HTTP_PORT/explorer/"
wait_for_http "http://127.0.0.1:$HTTP_PORT/workbench/"
wait_for_http "http://127.0.0.1:$HTTP_PORT/api/v1/docs"
echo "Waiting for seeded admin identity..."
wait_for_admin_seed

echo "Running API smoke checks..."
size_response="$(api_post '{"function":"size"}' | tr -d '[:space:]')"
case "$size_response" in
    ''|*[!0-9]*)
        echo "FAIL: size response is not a number: $size_response"
        exit 1
        ;;
esac

config_response="$(api_post "{\"function\":\"config\",\"authentication\":\"$INTERFACE_SECRET\"}")"
if [ -z "$config_response" ]; then
    echo "FAIL: config response is empty"
    exit 1
fi

gateway_size="$(gateway_get "/api/v1/general/size" | tr -d '[:space:]')"
case "$gateway_size" in
    ''|*[!0-9]*)
        echo "FAIL: gateway size response is not a number: $gateway_size"
        exit 1
        ;;
esac

root_unauthorized_status="$(gateway_status POST "/api/v1/root/step" -H "Content-Type: application/json" -d '[]')"
if [ "$root_unauthorized_status" != "404" ]; then
    echo "FAIL: expected Root to remain unavailable through Gateway (404), got $root_unauthorized_status"
    exit 1
fi

if [ "$LOCAL_COMPOSE_SKIP_FILE_SYSTEM" = "1" ]; then
    echo "Skipping WebDAV file-system smoke checks."
    echo "PASS: smoke checks succeeded."
    exit 0
fi

echo "Running WebDAV file-system smoke checks..."
webdav_options_status="$(gateway_status OPTIONS "/webdav/stage/admin/compose-smoke.txt")"
if [ "$webdav_options_status" != "204" ]; then
    echo "FAIL: expected WebDAV OPTIONS to return 204, got $webdav_options_status"
    exit 1
fi

webdav_root_status="$(gateway_status PROPFIND "/webdav/")"
if [ "$webdav_root_status" != "207" ]; then
    echo "FAIL: expected WebDAV root PROPFIND to return 207, got $webdav_root_status"
    exit 1
fi

webdav_unauthorized_status="$(gateway_status PROPFIND "/webdav/stage/admin/compose-smoke.txt")"
if [ "$webdav_unauthorized_status" != "401" ]; then
    echo "FAIL: expected unauthorized WebDAV stage PROPFIND to return 401, got $webdav_unauthorized_status"
    exit 1
fi

login_flow_json="$(curl -fsS "http://127.0.0.1:$HTTP_PORT/auth/.ory/self-service/login/api")"
login_flow="$(printf "%s" "$login_flow_json" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
session_json="$(curl -fsS \
  -X POST "http://127.0.0.1:$HTTP_PORT/auth/.ory/self-service/login?flow=$login_flow" \
  -H "Content-Type: application/json" \
  -d "{\"method\":\"password\",\"identifier\":\"$ADMIN_USERNAME\",\"password\":\"$ADMIN_PASSWORD\"}")"
session_token="$(printf "%s" "$session_json" | python -c 'import json,sys; print(json.load(sys.stdin)["session_token"])')"
api_token_json="$(curl -fsS \
  -X POST "http://127.0.0.1:$HTTP_PORT/api/v1/tokens" \
  -H "X-Session-Token: $session_token" \
  -H "Content-Type: application/json" \
  -d '{"description":"local-compose WebDAV smoke"}')"
api_token="$(printf "%s" "$api_token_json" | python -c 'import json,sys; print(json.load(sys.stdin)["token"])')"

fs_tmp_dir="/tmp/sync-services-webdav-smoke"
fs_local_file="$fs_tmp_dir/local.txt"
fs_download_file="$fs_tmp_dir/downloaded.txt"
mkdir -p "$fs_tmp_dir"
printf "compose WebDAV smoke\n" > "$fs_local_file"
rm -f "$fs_download_file"

webdav_put_status="$(curl -sS -o /dev/null -w "%{http_code}" \
  -u "$ADMIN_USERNAME:$api_token" \
  -T "$fs_local_file" \
  "http://127.0.0.1:$HTTP_PORT/webdav/stage/$ADMIN_USERNAME/compose-smoke.txt")"
if [ "$webdav_put_status" != "201" ]; then
    echo "FAIL: expected WebDAV PUT to return 201, got $webdav_put_status"
    exit 1
fi

webdav_get_status="$(curl -sS -o "$fs_download_file" -w "%{http_code}" \
  -u "$ADMIN_USERNAME:$api_token" \
  "http://127.0.0.1:$HTTP_PORT/webdav/stage/$ADMIN_USERNAME/compose-smoke.txt")"
if [ "$webdav_get_status" != "200" ]; then
    echo "FAIL: expected WebDAV GET to return 200, got $webdav_get_status"
    exit 1
fi
if ! cmp -s "$fs_local_file" "$fs_download_file"; then
    echo "FAIL: WebDAV round-trip content mismatch"
    exit 1
fi

curl -fsS -u "$ADMIN_USERNAME:$api_token" \
  -X PROPFIND "http://127.0.0.1:$HTTP_PORT/webdav/stage/$ADMIN_USERNAME/" \
  -o /tmp/sync-services-webdav-propfind.xml
if ! grep -q "compose-smoke.txt" /tmp/sync-services-webdav-propfind.xml; then
    echo "FAIL: WebDAV PROPFIND did not list uploaded file"
    cat /tmp/sync-services-webdav-propfind.xml
    exit 1
fi

webdav_move_status="$(curl -sS -o /dev/null -w "%{http_code}" \
  -u "$ADMIN_USERNAME:$api_token" \
  -X MOVE \
  -H "Destination: http://127.0.0.1:$HTTP_PORT/webdav/stage/$ADMIN_USERNAME/compose-smoke-moved.txt" \
  "http://127.0.0.1:$HTTP_PORT/webdav/stage/$ADMIN_USERNAME/compose-smoke.txt")"
if [ "$webdav_move_status" != "201" ]; then
    echo "FAIL: expected WebDAV MOVE to return 201, got $webdav_move_status"
    exit 1
fi

webdav_delete_status="$(curl -sS -o /dev/null -w "%{http_code}" \
  -u "$ADMIN_USERNAME:$api_token" \
  -X DELETE \
  "http://127.0.0.1:$HTTP_PORT/webdav/stage/$ADMIN_USERNAME/compose-smoke-moved.txt")"
if [ "$webdav_delete_status" != "204" ]; then
    echo "FAIL: expected WebDAV DELETE to return 204, got $webdav_delete_status"
    exit 1
fi

if [ "${LOCAL_COMPOSE_RELEASE_QA:-0}" = "1" ]; then
    echo "Running pre-release identity, authorization, run, and UI-help journey..."
    python3 "$ROOT_DIR/tests/release-qa/single_node_journey.py" \
      --base "http://127.0.0.1:$HTTP_PORT" \
      --admin-username "$ADMIN_USERNAME" \
      --admin-password "$ADMIN_PASSWORD"
fi

echo "PASS: smoke checks succeeded."
