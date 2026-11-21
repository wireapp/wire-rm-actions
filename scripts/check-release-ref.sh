#!/usr/bin/env bash
# The actions this repository calls by ref point at the release about to be
# published: every `uses: wireapp/wire-rm-actions/<action>@<ref>` of the
# reusable workflow (and of the templates, when the directory exists) must be
# @<version>. The prepare-release and publish-release workflows refuse a
# commit whose refs name another release (make release-prep VERSION=vX.Y.Z).
#
# Usage: check-release-ref.sh vX.Y.Z [file...]
# Default files: .github/workflows/dev-build.yml templates/*.yml
set -euo pipefail
export LC_ALL=C

version=${1:-}
num='(0|[1-9][0-9]*)'
[[ $version =~ ^v${num}\.${num}\.${num}(-(alpha|beta|rc)\.[1-9][0-9]*)?$ ]] || {
  echo "usage: $0 vX.Y.Z[-<alpha|beta|rc>.N] [file...]" >&2
  exit 64
}
shift || true
files=("$@")
if [[ ${#files[@]} -eq 0 ]]; then
  files=(.github/workflows/dev-build.yml)
  for f in templates/*.yml; do
    [[ -f $f ]] && files+=("$f")
  done
fi

pattern='uses: wireapp/wire-rm-actions/[^@[:space:]]+@[^[:space:]]+'
status=0
for f in "${files[@]}"; do
  [[ -f $f ]] || { echo "check-release-ref: no $f" >&2; exit 1; }
  refs=$(grep -Eo "$pattern" "$f" || true)
  [[ -n $refs ]] || { echo "check-release-ref: no wireapp/wire-rm-actions ref in $f" >&2; exit 1; }
  if wrong=$(grep -v "@${version}\$" <<<"$refs"); then
    echo "check-release-ref: $f must call the actions at @${version} (make release-prep VERSION=${version}):" >&2
    while IFS= read -r line; do echo "  $line" >&2; done <<<"$wrong"
    status=1
  else
    echo "$f: every wireapp/wire-rm-actions ref is @${version}"
  fi
done
exit $status
