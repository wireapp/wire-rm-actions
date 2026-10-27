#!/usr/bin/env bash
# Point the reusable workflow at a release (make release-prep): every
# `uses: wireapp/wire-rm-actions/<action>@<ref>` of dev-build.yml becomes
# @<version>, whatever <ref> was (dev or the previous release). The release
# workflow refuses a tag whose dev-build.yml calls another ref.
#
# Usage: set-release-ref.sh vX.Y.Z
# Environment: WORKFLOW (default .github/workflows/dev-build.yml).
set -euo pipefail
export LC_ALL=C

version=${1:-}
workflow=${WORKFLOW:-.github/workflows/dev-build.yml}
num='(0|[1-9][0-9]*)'
[[ $version =~ ^v${num}\.${num}\.${num}$ ]] || {
  echo "usage: $0 vX.Y.Z" >&2
  exit 64
}
[[ -f $workflow ]] || {
  echo "set-release-ref: no $workflow" >&2
  exit 1
}

pattern='(uses: wireapp/wire-rm-actions/[^@[:space:]]+)@[^[:space:]]+'
grep -Eq "$pattern" "$workflow" || {
  echo "set-release-ref: no wireapp/wire-rm-actions ref in $workflow" >&2
  exit 1
}
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
sed -E "s|${pattern}|\\1@${version}|" "$workflow" >"$tmp"
cat "$tmp" >"$workflow"
grep -Eo "$pattern" "$workflow"
