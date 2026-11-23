#!/usr/bin/env bash
# Point the reusable workflow at a release (make release-prep): every
# `uses: wireapp/wire-rm-actions/<action>@<ref>` of dev-build.yml (and of the
# templates, when the directory exists) becomes @<version>, whatever <ref> was
# (dev or the previous release). The release workflows refuse a commit whose
# refs name another release (check-release-ref.sh, same files).
#
# Usage: set-release-ref.sh vX.Y.Z[-<alpha|beta|rc>.N]
# Environment: WORKFLOW, one file instead of the default
# .github/workflows/dev-build.yml templates/*.yml.
set -euo pipefail
export LC_ALL=C

version=${1:-}
num='(0|[1-9][0-9]*)'
[[ $version =~ ^v${num}\.${num}\.${num}(-(alpha|beta|rc)\.[1-9][0-9]*)?$ ]] || {
  echo "usage: $0 vX.Y.Z[-<alpha|beta|rc>.N]" >&2
  exit 64
}
if [[ -n ${WORKFLOW:-} ]]; then
  files=("$WORKFLOW")
else
  files=(.github/workflows/dev-build.yml)
  for f in templates/*.yml; do
    [[ -f $f ]] && files+=("$f")
  done
fi

pattern='(uses: wireapp/wire-rm-actions/[^@[:space:]]+)@[^[:space:]]+'
for f in "${files[@]}"; do
  [[ -f $f ]] || {
    echo "set-release-ref: no $f" >&2
    exit 1
  }
  grep -Eq "$pattern" "$f" || {
    echo "set-release-ref: no wireapp/wire-rm-actions ref in $f" >&2
    exit 1
  }
done
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
for f in "${files[@]}"; do
  sed -E "s|${pattern}|\\1@${version}|" "$f" >"$tmp"
  cat "$tmp" >"$f"
  grep -Eo "$pattern" "$f"
done
