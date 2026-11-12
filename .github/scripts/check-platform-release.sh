#!/usr/bin/env bash
set -euo pipefail

# A manual dispatch on main approves this exact source/version, not a PR image.
if [[ ${GITHUB_EVENT_NAME:-} != workflow_dispatch || ${GITHUB_REF:-} != refs/heads/main || ${PLATFORM_RELEASE:-} != true ]]; then
  echo 'Platform publication requires explicit release intent on main.' >&2
  exit 1
fi
selected_commit="$1"
selected_version="$2"
if [[ ! $selected_commit =~ ^[0-9a-f]{40}$ || $selected_commit != "${GITHUB_SHA:-}" || $selected_commit != "$(git rev-parse HEAD)" ]]; then
  echo 'Selected commit must match the dispatched main commit and checkout.' >&2
  exit 1
fi
if [[ ! $selected_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ || $selected_version != "$(cat VERSION)" || $selected_version != "$(git show "$selected_commit:VERSION")" ]]; then
  echo 'Selected version must match VERSION at the selected main commit.' >&2
  exit 1
fi
