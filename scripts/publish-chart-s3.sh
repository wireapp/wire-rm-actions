#!/usr/bin/env bash
# Push a packaged chart (<name>-<version>.tgz) to an S3 Helm repository with
# helm-s3 (`helm s3 push --relative`, never --force). The same package already
# under that version is a no-op, another content a failure.
#
# Environment:
#   CHART_FILE        path of the packaged chart
#   S3_REPOSITORY     repository name (charts-develop, charts-extra, ...)
#   S3_URL            repository URL; default s3://public.wire.com/<S3_REPOSITORY>
#   HELM_S3_VERSION   helm-s3 plugin version installed when missing
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION   read by the plugin
#
# Outputs: name, version, status (pushed | present), repository (the S3 URL).
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

CHART_FILE="${CHART_FILE:-}"
S3_REPOSITORY="${S3_REPOSITORY:-}"
S3_URL="${S3_URL:-}"
HELM_S3_VERSION="${HELM_S3_VERSION:-0.15.1}"

[[ -f $CHART_FILE ]] || die "chart-file '$CHART_FILE' not found"
[[ $S3_REPOSITORY =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "s3-repository must be a lowercase repository name (got: '$S3_REPOSITORY')"
[[ -n $S3_URL ]] || S3_URL="s3://public.wire.com/${S3_REPOSITORY}"
[[ $S3_URL == s3://* ]] || die "s3-url must start with s3:// (got: '$S3_URL')"
[[ -n ${AWS_ACCESS_KEY_ID:-} && -n ${AWS_SECRET_ACCESS_KEY:-} ]] || die "AWS credentials are required"
[[ -n ${AWS_REGION:-} ]] || unset AWS_REGION

chart_field() {
  helm show chart "$CHART_FILE" | sed -n "s/^$1: *//p" | head -n1
}
name="$(chart_field name)"
version="$(chart_field version)"
[[ -n $name && -n $version ]] || die "cannot read the name and version of $CHART_FILE"
file="$(basename "$CHART_FILE")"
[[ $file == "${name}-${version}.tgz" ]] || die "$file should be named ${name}-${version}.tgz"
expected_sha256="$(sha256_of "$CHART_FILE")"

if ! helm plugin list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -qx s3; then
  helm plugin install https://github.com/hypnoglow/helm-s3.git --version "$HELM_S3_VERSION" >/dev/null
fi

helm repo add "$S3_REPOSITORY" "$S3_URL" >/dev/null
helm repo update "$S3_REPOSITORY" >/dev/null

emit name "$name"
emit version "$version"
emit repository "$S3_URL"

# Exact match on name and version through JSON: `helm search` matches names by
# substring and, under pipefail, a failing search would read as "absent" and
# send a rerun into a push against an existing version.
if helm search repo "${S3_REPOSITORY}/${name}" --version "$version" --devel -o json 2>/dev/null \
  | jq -e --arg n "${S3_REPOSITORY}/${name}" --arg v "$version" 'any(.[]; .name == $n and .version == $v)' >/dev/null; then
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  helm pull "${S3_REPOSITORY}/${name}" --version "$version" --devel --destination "$work" >/dev/null
  existing_sha256="$(sha256_of "$work/$file")"
  [[ $existing_sha256 == "$expected_sha256" ]] \
    || die "${name} ${version} already exists in ${S3_REPOSITORY} with sha256 ${existing_sha256}, expected ${expected_sha256}: refusing to overwrite"
  echo "${name} ${version} is already in ${S3_REPOSITORY} with the same sha256: nothing to push."
  emit status present
  summary "Chart \`${name} ${version}\` already in \`${S3_URL}\`."
  exit 0
fi

helm s3 push --relative "$CHART_FILE" "$S3_REPOSITORY"
echo "Pushed ${file} to ${S3_REPOSITORY} (${S3_URL})."
emit status pushed
summary "Chart \`${name} ${version}\` pushed to \`${S3_URL}\`."
