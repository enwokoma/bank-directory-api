#!/usr/bin/env bash
# Create the GitHub release for a tag, with the tag's section of CHANGELOG.md
# as its notes, and attach every country's data file exactly as it was at the
# tag, with a SHA256SUMS file so downloads can be verified. A release that
# already exists is left as it is, and only the files are attached again.
#
# The release workflow runs this on every signed tag push, so it is only run
# by hand when that job failed. It runs as whoever `gh` is logged in as.
#
# Usage: scripts/create-release.sh v0.7.0
set -euo pipefail

tag="${1:?Usage: $0 <tag>, for example v0.7.0}"
version="${tag#v}"
git rev-parse --verify --quiet "refs/tags/${tag}" >/dev/null || { echo "No tag ${tag} in this repository." >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

# The release's section of the changelog: from its "## X.Y.Z - date" heading to
# the next "## " heading, without the heading or the blank lines around the body.
git show "${tag}:CHANGELOG.md" | awk -v prefix="## ${version} - " '
  /^## / { if (found) done = 1; found = !done && substr($0, 1, length(prefix)) == prefix; next }
  found { lines[++n] = $0 }
  END {
    first = 1; while (first <= n && lines[first] ~ /^[[:space:]]*$/) first++
    last = n; while (last >= first && lines[last] ~ /^[[:space:]]*$/) last--
    for (i = first; i <= last; i++) print lines[i]
  }
' >"${work}/notes.md"
if [ ! -s "${work}/notes.md" ]; then
  echo "CHANGELOG.md at ${tag} has no '## ${version} - <date>' section to use as the release notes." >&2
  exit 1
fi

if output="$(gh release view "${tag}" --json tagName 2>&1)"; then
  echo "Release ${tag} already exists; its notes are left as they are."
elif [[ "${output}" == *"release not found"* ]]; then
  gh release create "${tag}" --verify-tag --title "${tag}" --notes-file "${work}/notes.md"
  echo "Created release ${tag} with its changelog section as the notes."
else
  printf '%s\n' "${output}" >&2
  exit 1
fi

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
echo "Attached ${#files[@]} data file(s) and SHA256SUMS to ${tag}."
