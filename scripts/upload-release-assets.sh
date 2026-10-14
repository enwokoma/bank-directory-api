#!/usr/bin/env bash
# Attach every country's data file, exactly as it was at a release's tag, to
# that GitHub release, with a SHA256SUMS file so downloads can be verified.
# Uploads run as whoever `gh` is logged in as.
#
# Usage: scripts/upload-release-assets.sh v0.2.0
set -euo pipefail

tag="${1:?Usage: $0 <tag>, for example v0.2.0}"
git rev-parse --verify --quiet "refs/tags/${tag}" >/dev/null || { echo "No tag ${tag} in this repository." >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

files=()
while IFS= read -r path; do
  name="$(basename "${path}")"
  git show "${tag}:${path}" >"${work}/${name}"
  files+=("${work}/${name}")
done < <(git ls-tree --name-only "${tag}" data/countries/ | grep '\.json$')

if [ "${#files[@]}" -eq 0 ]; then
  echo "No data files under data/countries/ at ${tag}." >&2
  exit 1
fi

(cd "${work}" && shasum -a 256 -- *.json >SHA256SUMS)
gh release upload "${tag}" "${files[@]}" "${work}/SHA256SUMS" --clobber
echo "Uploaded ${#files[@]} data file(s) and SHA256SUMS to ${tag}."
