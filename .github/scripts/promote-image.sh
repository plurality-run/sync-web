#!/usr/bin/env bash
set -euo pipefail

image_name="$1"
version_file="${2:-VERSION}"
variant="${3:-}"
preferred="${4:-}"

repo="ghcr.io/${GITHUB_REPOSITORY}/${image_name}"
version="$(cat "$version_file")"

"$(dirname "$0")/check-platform-release.sh" "$GITHUB_SHA" "$version"

suffix="${variant:+-${variant}}"
source="${repo}:sha-${GITHUB_SHA}${suffix}"
tags=(-t "${repo}:latest${suffix}" -t "${repo}:${version}${suffix}")
if [[ $preferred == preferred ]]; then
  tags+=(-t "${repo}:latest" -t "${repo}:${version}")
fi
echo "Promoting ${source} to variant${preferred:+ and preferred} tags"

docker buildx imagetools inspect "$source" >/dev/null

docker buildx imagetools create "${tags[@]}" "$source"
