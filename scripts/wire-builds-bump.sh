#!/usr/bin/env bash
# Point the wire-builds entry of a chart at a published version: helmCharts.<chart> of
# build.json gets the version, and the repo and meta fields given, and the top-level version
# gets its pre-release bumped, in one commit through the contents API.
#
# Retry-safe: an entry already at those values is a no-op (nothing committed, status
# unchanged), so a rerun after a commit that landed changes nothing. The update is a
# compare-and-swap on the blob sha: when another commit landed in between, the file is read
# again and the change applied again, up to ATTEMPTS times. Before every write, the new file
# must differ from the one read only in .version and .helmCharts.<chart> (normalized JSON).
#
# Inputs (environment): GH_TOKEN (contents write on the wire-builds repository), CHART (the
# helmCharts key), VERSION (the chart version), CHART_REPO (the chart repository URL; empty
# keeps the current one, required for a new entry), APP_VERSION (meta.appVersion, default
# VERSION; "-" leaves it out), COMMIT (meta.commit, a full sha; empty leaves it out),
# COMMIT_URL (meta.commitURL, default <server>/<SOURCE_REPOSITORY>/commit/<COMMIT>),
# SOURCE_REPOSITORY (default $GITHUB_REPOSITORY), WIRE_BUILDS_REPOSITORY (default
# wireapp/wire-builds), BRANCH (default dev), FILE (default build.json), MESSAGE (default
# "Bump <chart> to <version>"), BUMP_BUILD_VERSION (true | false, default true), ATTEMPTS (5),
# RETRY_DELAY (5 seconds).
#
# Other meta fields of the entry are kept. Outputs (stdout and $GITHUB_OUTPUT): status
# (bumped | unchanged), build-version (the top-level version after the step), commit (the
# wire-builds commit, empty when unchanged).
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

CHART="${CHART:-}"
VERSION="${VERSION:-}"
CHART_REPO="${CHART_REPO:-}"
APP_VERSION="${APP_VERSION:-$VERSION}"
COMMIT="${COMMIT:-}"
SOURCE_REPOSITORY="${SOURCE_REPOSITORY:-${GITHUB_REPOSITORY:-}}"
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
WIRE_BUILDS_REPOSITORY="${WIRE_BUILDS_REPOSITORY:-wireapp/wire-builds}"
BRANCH="${BRANCH:-dev}"
FILE="${FILE:-build.json}"
BUMP_BUILD_VERSION="${BUMP_BUILD_VERSION:-true}"
ATTEMPTS="${ATTEMPTS:-5}"
RETRY_DELAY="${RETRY_DELAY:-5}"

[[ "$CHART" =~ ^[A-Za-z0-9._-]+$ ]] || die "CHART '${CHART}' is not a chart name"
"$here/semver.sh" valid "$VERSION" || die "VERSION '${VERSION}' is not a SemVer version"
[[ "$APP_VERSION" == - || -n "$APP_VERSION" ]] || die "APP_VERSION is empty"
[[ -z "$COMMIT" || "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "COMMIT '${COMMIT}' is not a full commit sha"
[[ -z "$CHART_REPO" || "$CHART_REPO" =~ ^(https|oci)://[^[:space:]]+$ ]] || die "CHART_REPO '${CHART_REPO}' is not an https:// or oci:// URL"
[[ "$WIRE_BUILDS_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "WIRE_BUILDS_REPOSITORY '${WIRE_BUILDS_REPOSITORY}' is not owner/name"
[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || die "BRANCH '${BRANCH}' has unexpected characters"
[[ "$FILE" =~ ^[A-Za-z0-9._/-]+$ && "$FILE" != *..* ]] || die "FILE '${FILE}' is not a plain path"
[[ "$BUMP_BUILD_VERSION" == true || "$BUMP_BUILD_VERSION" == false ]] || die "BUMP_BUILD_VERSION must be true or false"
[[ "$ATTEMPTS" =~ ^[1-9][0-9]*$ ]] || die "ATTEMPTS must be a positive number, not '${ATTEMPTS}'"
[[ "$RETRY_DELAY" =~ ^[0-9]+$ ]] || die "RETRY_DELAY must be a number of seconds, not '${RETRY_DELAY}'"

COMMIT_URL="${COMMIT_URL:-}"
if [[ -z "$COMMIT_URL" && -n "$COMMIT" ]]; then
  [[ -n "$SOURCE_REPOSITORY" ]] || die "COMMIT_URL or SOURCE_REPOSITORY is required with COMMIT"
  COMMIT_URL="${SERVER_URL}/${SOURCE_REPOSITORY}/commit/${COMMIT}"
fi
MESSAGE="${MESSAGE:-Bump ${CHART} to ${VERSION}}"

# The meta fields to set, as a JSON object.
meta="$(jq -n --arg app "$APP_VERSION" --arg commit "$COMMIT" --arg url "$COMMIT_URL" '
  {}
  + (if $app != "-" then {appVersion: $app} else {} end)
  + (if $commit != "" then {commit: $commit} else {} end)
  + (if $url != "" then {commitURL: $url} else {} end)')"

# bump_prerelease <version>: the last numeric identifier of the pre-release plus one
# (1.0.0-zulu.5897 -> 1.0.0-zulu.5898), as wire-builds' bin/bump-prerelease does.
bump_prerelease() {
  local v="$1" core pre last
  [[ "$v" == *-* ]] || die "the ${FILE} version '${v}' has no pre-release to bump"
  core="${v%%-*}" pre="${v#*-}"
  pre="${pre%%+*}"
  last="${pre##*.}"
  [[ "$last" =~ ^[0-9]+$ ]] || die "the ${FILE} version '${v}' does not end with a number"
  if [[ "$pre" == *.* ]]; then
    printf '%s-%s.%s\n' "$core" "${pre%.*}" "$((10#$last + 1))"
  else
    printf '%s-%s\n' "$core" "$((10#$last + 1))"
  fi
}

# The entry is at the target when every field we set already has its value.
at_target() {
  jq -e --arg c "$CHART" --arg v "$VERSION" --arg r "$CHART_REPO" --argjson meta "$meta" '
    .helmCharts[$c] as $e
    | $e != null and $e.version == $v and ($r == "" or $e.repo == $r)
      and ($meta | to_entries | all(.value == ($e.meta // {})[.key]))' "$1" >/dev/null
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
api="repos/${WIRE_BUILDS_REPOSITORY}/contents/${FILE}"

for ((attempt = 1; attempt <= ATTEMPTS; attempt++)); do
  gh api -H "Accept: application/vnd.github+json" "${api}?ref=${BRANCH}" >"$work/read.json" \
    || die "could not read ${FILE} of ${WIRE_BUILDS_REPOSITORY}@${BRANCH}"
  blob="$(jq -r '.sha' "$work/read.json")"
  jq -r '.content' "$work/read.json" | base64 -d >"$work/old.json" \
    || die "could not decode ${FILE} of ${WIRE_BUILDS_REPOSITORY}@${BRANCH}"
  jq -e 'type == "object" and (.helmCharts | type == "object")' "$work/old.json" >/dev/null 2>&1 \
    || die "${FILE} of ${WIRE_BUILDS_REPOSITORY}@${BRANCH} has no helmCharts object"

  build_version="$(jq -r '.version // ""' "$work/old.json")"
  if at_target "$work/old.json"; then
    echo "${CHART} is already at ${VERSION} in ${WIRE_BUILDS_REPOSITORY}@${BRANCH}: nothing to commit."
    emit status unchanged
    emit build-version "$build_version"
    emit commit ""
    exit 0
  fi
  if [[ -z "$CHART_REPO" ]] && ! jq -e --arg c "$CHART" '.helmCharts[$c].repo // empty' "$work/old.json" >/dev/null; then
    die "${CHART} has no entry (or no repo) in ${FILE}: CHART_REPO is required"
  fi
  [[ "$BUMP_BUILD_VERSION" == false ]] || build_version="$(bump_prerelease "$build_version")"

  jq --arg c "$CHART" --arg v "$VERSION" --arg r "$CHART_REPO" --argjson meta "$meta" \
    --arg bv "$build_version" --arg bump "$BUMP_BUILD_VERSION" '
    (if $bump == "true" then .version = $bv else . end)
    | .helmCharts[$c] = ((.helmCharts[$c] // {})
        + {version: $v}
        + (if $r != "" then {repo: $r} else {} end)
        + {meta: (((.helmCharts[$c] // {}).meta // {}) + $meta)})' "$work/old.json" >"$work/new.json"

  # Only the two fields may move: anything else is a bug, never committed.
  diff <(jq -S --arg c "$CHART" 'del(.version, .helmCharts[$c])' "$work/old.json") \
    <(jq -S --arg c "$CHART" 'del(.version, .helmCharts[$c])' "$work/new.json") >/dev/null \
    || die "the update of ${CHART} would change more than .version and .helmCharts.${CHART}: refusing to commit"

  jq -n --arg message "$MESSAGE" --arg branch "$BRANCH" --arg sha "$blob" \
    --rawfile content <(base64 -w0 <"$work/new.json" 2>/dev/null || base64 <"$work/new.json" | tr -d '\n') \
    '{message: $message, branch: $branch, sha: $sha, content: $content}' >"$work/put.json"
  if gh api --method PUT "$api" --input "$work/put.json" >"$work/put-answer.json" 2>"$work/put.err"; then
    commit="$(jq -r '.commit.sha // ""' "$work/put-answer.json")"
    echo "Committed ${CHART} ${VERSION} to ${WIRE_BUILDS_REPOSITORY}@${BRANCH} (${commit}), build version ${build_version}."
    summary "### wire-builds" "" "\`${CHART}\` at \`${VERSION}\` in ${WIRE_BUILDS_REPOSITORY}@${BRANCH}, build version \`${build_version}\` (${commit})."
    emit status bumped
    emit build-version "$build_version"
    emit commit "$commit"
    exit 0
  fi
  cat "$work/put.err" >&2
  (( attempt < ATTEMPTS )) || break
  # A conflict (another commit landed) or a transient error: read again, apply again.
  echo "::warning::the commit to ${WIRE_BUILDS_REPOSITORY}@${BRANCH} failed (attempt ${attempt}/${ATTEMPTS}), reading ${FILE} again in ${RETRY_DELAY}s"
  sleep "$RETRY_DELAY"
done
die "could not commit ${CHART} ${VERSION} to ${WIRE_BUILDS_REPOSITORY}@${BRANCH} after ${ATTEMPTS} attempt(s)"
