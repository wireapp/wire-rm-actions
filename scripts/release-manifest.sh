#!/usr/bin/env bash
# The release manifest of a candidate, schema wire.component-release-manifest/v1alpha1
# (ADR-0020 section 2, ADR-0021 section 3). Three modes, selected by MODE:
#
#   write     build the frozen part of the manifest with `jq -n --arg` (every value comes
#             from the environment, jq does the escaping) and refuse an empty required field;
#   verify    check downloaded release assets against the manifest: version, source commit,
#             chart sha256, document sha256, and print the fields publication needs;
#   complete  append the `publication` block (published_at, run_url, OCI digests) to a
#             manifest without touching anything above it; idempotent.
#
# Inputs (environment), write:
#   MANIFEST             output path (default: release-manifest.json)
#   COMPONENT            release manager component id (required)
#   TAG_PREFIX           prefix of the git tag in source.tag (default: v)
#   VERSION, RELEASE_TYPE (ga | alpha | beta | rc | dev)
#     dev: a dev build (dev.yml), kind dev, without git tag, candidate tag nor chart file: the
#     chart is identified by CHART_DIGEST, and IMAGE_CANDIDATE_TAG, CHART_FILE, CHART_SHA256,
#     REQUEST_ID and RM_ORIGIN are not used
#   SOURCE_REPOSITORY, SOURCE_REF, SOURCE_COMMIT
#   IMAGE_REPOSITORY, IMAGE_DIGEST, IMAGE_CANDIDATE_TAG
#   CHART_REPOSITORY (oci://...), CHART_FILE, CHART_SHA256, CHART_DIGEST (dev only)
#   COMPATIBILITY_FILE   read by compatibility.sh: default publication/compatibility.yaml
#                        (ADR-0020 section 3)
#   BUILD_WORKFLOW, BUILD_RUN_ID, BUILD_RUN_URL, BUILD_CREATED_AT (default: now, UTC)
#   REQUEST_ID, RM_ORIGIN  empty on the manual path (written as null)
#   DOCUMENTS_JSON       the `documents` object from release-documents.sh (default {})
#   INPUTS_JSON          the build inputs other than the source repository, e.g. the
#                        configuration repository of a component: a JSON array of objects
#                        with a name, written as `inputs` (default [])
#   EXTRA_ARTIFACTS_JSON the artifacts other than the image and the chart, e.g. a deployment
#                        bundle: a JSON array of {type, file, sha256}, appended after the
#                        chart (default []); file is a plain name, type is not image or chart
#   EXPIRES_AFTER        dev only, e.g. 90d (hours h, days d, weeks w): written as
#                        expires_at, BUILD_CREATED_AT plus that delay (ADR-0020 section 5);
#                        BUILD_CREATED_AT must then be YYYY-MM-DDTHH:MM:SSZ
# verify:
#   MANIFEST, ASSET_DIR (where the assets were downloaded), VERSION (expected, optional),
#   SOURCE_COMMIT (expected, optional: the draft's target commit), TAG_PREFIX (default: v),
#   RELEASE_BRANCHES (regex of the releasable source refs, default: ^(dev|release/[0-9]+\.[0-9]+)$)
#   CHECK_SOURCE_BRANCH (true | false, default false): also refuse a stale source, one that is no
#     longer an ancestor of origin/<source.ref>; the checkout must have the branch (fetch-depth 0)
# complete:
#   MANIFEST, PUBLISHED_AT (default: now, UTC), RUN_URL, DIGESTS_JSON (object: ref -> digest),
#   OUT (default: MANIFEST, in place)
#
# Outputs (stdout and $GITHUB_OUTPUT): write: manifest; verify: the fields of the manifest
# (version, kind, stage, type, source-ref, source-commit, image-*, chart-*, request-id,
# rm-origin, note-file, declaration-file) and extra-artifacts-json, the extra artifacts
# with the path of their downloaded file ([] when there is none); complete: manifest.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

MODE="${MODE:-}"
MANIFEST="${MANIFEST:-release-manifest.json}"
TAG_PREFIX="${TAG_PREFIX-v}"
RELEASE_BRANCHES="${RELEASE_BRANCHES:-^(dev|release/[0-9]+\.[0-9]+)$}"
CHECK_SOURCE_BRANCH="${CHECK_SOURCE_BRANCH:-false}"

readonly SCHEMA_VERSION='wire.component-release-manifest/v1alpha1'

now_utc() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# require <path> <jq path...>: every field must be present and non-empty.
require() {
  local file="$1" path value
  shift
  for path in "$@"; do
    value="$(jq -r "$path // empty" "$file")"
    [[ -n "$value" ]] || die "manifest field ${path} is empty in ${file}"
  done
}

write() {
  local component="${COMPONENT:-}"
  local version="${VERSION:-}" type="${RELEASE_TYPE:-}"
  local compat_file="${COMPATIBILITY_FILE:-}"
  local documents="${DOCUMENTS_JSON:-}" inputs="${INPUTS_JSON:-}" extras="${EXTRA_ARTIFACTS_JSON:-}"
  local expires_after="${EXPIRES_AFTER:-}"
  [[ -n "$documents" ]] || documents='{}'
  [[ -n "$inputs" ]] || inputs='[]'
  [[ -n "$extras" ]] || extras='[]'
  local created_at="${BUILD_CREATED_AT:-$(now_utc)}"
  local kind stage compatibility tmp

  [[ -n "$component" ]] || die "COMPONENT is required"
  case "$type" in
    ga) kind=ga; stage="" ;;
    alpha | beta | rc) kind=prerelease; stage="$type" ;;
    dev) kind=dev; stage="" ;;
    *) die "RELEASE_TYPE must be one of ga, alpha, beta, rc, dev (got: '$type')" ;;
  esac
  if [[ "$kind" == dev ]]; then
    # X.Y.(Z+1)-<ts>[.<branch>].g<sha7> or X.Y.Z-<stage>.N.<ts>[.<branch>].g<sha7> (ADR-0018).
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-[0-9A-Za-z.-]*\.?g[0-9a-f]{7}$ ]] \
      || die "VERSION '$version' is not a dev version (X.Y.Z-...g<sha7>)"
    [[ -z "${REQUEST_ID:-}" && -z "${RM_ORIGIN:-}" ]] || die "a dev build has no REQUEST_ID nor RM_ORIGIN"
  else
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)\.[0-9]+)?$ ]] \
      || die "VERSION '$version' is not X.Y.Z or X.Y.Z-<alpha|beta|rc>.N"
    [[ "$kind" == ga && "$version" != *-* || "$kind" == prerelease && "$version" == *-${stage}.* ]] \
      || die "VERSION '$version' does not match the release type '$type'"
  fi
  # compatibility.sh reads publication/compatibility.yaml (ADR-0020 section 3),
  # checks it and writes the provides / requires / includes object the
  # release manager reads; its own outputs stay out of $GITHUB_OUTPUT and of stdout.
  compat_dir="$(mktemp -d)"
  GITHUB_OUTPUT='' FILE="$compat_file" OUTPUT_DIR="$compat_dir" "$here/compatibility.sh" >&2 \
    || { rm -rf "$compat_dir"; die "the compatibility file was refused (ADR-0020 rule 7)"; }
  compatibility="$(cat "$compat_dir/manifest-compatibility.json")"
  rm -rf "$compat_dir"
  jq -e 'type == "object" and all(.[]; type == "object")' <<<"$documents" >/dev/null 2>&1 \
    || die "DOCUMENTS_JSON must be a JSON object (never null): '$documents'"
  jq -e 'type == "array" and all(.[]; type == "object" and (.name | type == "string" and length > 0))' <<<"$inputs" >/dev/null 2>&1 \
    || die "INPUTS_JSON must be a JSON array of objects with a name: '$inputs'"
  jq -e '
    type == "array" and all(.[];
      type == "object" and (keys | sort) == ["file", "sha256", "type"]
      and (.type | type == "string" and length > 0 and (IN("image", "chart") | not))
      and (.file | type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._-]*$"))
      and (.sha256 | type == "string" and test("^[0-9a-f]{64}$")))' <<<"$extras" >/dev/null 2>&1 \
    || die "EXTRA_ARTIFACTS_JSON must be a JSON array of {type, file, sha256}: a type other than image or chart, a plain file name, a hex sha256: '$extras'"
  if [[ -n "$expires_after" ]]; then
    [[ "$kind" == dev ]] || die "EXPIRES_AFTER is for a dev build only: a $type release never expires"
    [[ "$expires_after" =~ ^[1-9][0-9]*[hdw]$ ]] \
      || die "EXPIRES_AFTER must be a number of hours, days or weeks (e.g. 90d), not '$expires_after'"
    [[ "$created_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
      || die "BUILD_CREATED_AT '$created_at' is not YYYY-MM-DDTHH:MM:SSZ, needed with EXPIRES_AFTER"
  fi
  [[ -z "${REQUEST_ID:-}" || -n "${RM_ORIGIN:-}" ]] || die "RM_ORIGIN is required with REQUEST_ID"
  [[ -n "${REQUEST_ID:-}" || -z "${RM_ORIGIN:-}" ]] || die "RM_ORIGIN is set without REQUEST_ID"

  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  jq -n \
    --arg schema "$SCHEMA_VERSION" \
    --arg component "$component" \
    --arg version "$version" \
    --arg kind "$kind" \
    --arg stage "$stage" \
    --arg source_repository "${SOURCE_REPOSITORY:-}" \
    --arg source_ref "${SOURCE_REF:-}" \
    --arg source_commit "${SOURCE_COMMIT:-}" \
    --arg image_repository "${IMAGE_REPOSITORY:-}" \
    --arg image_digest "${IMAGE_DIGEST:-}" \
    --arg image_candidate_tag "${IMAGE_CANDIDATE_TAG:-}" \
    --arg chart_repository "${CHART_REPOSITORY:-}" \
    --arg chart_file "${CHART_FILE:-}" \
    --arg chart_sha256 "${CHART_SHA256:-}" \
    --arg chart_digest "${CHART_DIGEST:-}" \
    --argjson compatibility "$compatibility" \
    --arg build_workflow "${BUILD_WORKFLOW:-}" \
    --arg build_run_id "${BUILD_RUN_ID:-}" \
    --arg build_run_url "${BUILD_RUN_URL:-}" \
    --arg build_created_at "$created_at" \
    --arg request_id "${REQUEST_ID:-}" \
    --arg rm_origin "${RM_ORIGIN:-}" \
    --arg tag_prefix "$TAG_PREFIX" \
    --arg expires_after "$expires_after" \
    --argjson inputs "$inputs" \
    --argjson extras "$extras" \
    --argjson documents "$documents" '
    def opt: if . == "" then null else . end;
    # 90d -> seconds; the unit was validated by the shell.
    def seconds: (.[0:-1] | tonumber) * ({h: 3600, d: 86400, w: 604800}[.[-1:]]);
    {
      schemaVersion: $schema,
      component: $component,
      version: $version,
      kind: $kind
    }
    + (if $stage != "" then {stage: $stage} else {} end)
    + {
      source: {
        repository: $source_repository,
        ref: $source_ref,
        commit: $source_commit,
        tag: (if $kind == "dev" then null else $tag_prefix + $version end)
      },
      inputs: $inputs,
      artifacts: ((if $kind == "dev" then [
        {type: "image", repository: $image_repository, tag: $version, digest: $image_digest},
        {type: "chart", repository: $chart_repository, version: $version, digest: $chart_digest}
      ] else [
        {
          type: "image",
          repository: $image_repository,
          tag: $version,
          digest: $image_digest,
          candidate_tag: $image_candidate_tag
        },
        {
          type: "chart",
          repository: $chart_repository,
          version: $version,
          file: $chart_file,
          sha256: $chart_sha256
        }
      ] end) + $extras),
      # The release manager refuses a manifest without the three lists (ADR-0020 section 2):
      # An absent includes is written as [] (the component includes no other one).
      compatibility: {
        provides: $compatibility.provides,
        requires: $compatibility.requires,
        includes: ($compatibility.includes // [])
      },
      build: {
        workflow: $build_workflow,
        run_id: $build_run_id,
        run_url: $build_run_url,
        created_at: $build_created_at
      }
    }
    + (if $expires_after != "" then
        {expires_at: (($build_created_at | fromdateiso8601) + ($expires_after | seconds) | todateiso8601)}
      else {} end)
    + {
      request_id: ($request_id | opt),
      rm_origin: ($rm_origin | opt),
      documents: $documents
    }' >"$tmp"

  # Fail here rather than at publication if anything came through empty. The manifest is
  # only moved into place once every check passed.
  require "$tmp" .schemaVersion .component .version .kind \
    .source.repository .source.ref .source.commit \
    '.artifacts[0].repository' '.artifacts[0].tag' '.artifacts[0].digest' \
    '.artifacts[1].repository' '.artifacts[1].version' \
    .build.workflow .build.run_id .build.run_url .build.created_at
  [[ "$(jq -r '.artifacts[0].digest' "$tmp")" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || die "the image digest is not a sha256 digest"
  if [[ "$kind" == dev ]]; then
    [[ "$(jq -r '.artifacts[1].digest' "$tmp")" =~ ^sha256:[0-9a-f]{64}$ ]] \
      || die "the chart digest is not a sha256 digest"
  else
    require "$tmp" .source.tag '.artifacts[0].candidate_tag' '.artifacts[1].file' '.artifacts[1].sha256'
    [[ "$(jq -r '.artifacts[1].sha256' "$tmp")" =~ ^[0-9a-f]{64}$ ]] \
      || die "the chart sha256 is not a hex sha256"
  fi
  [[ "$(jq -r '.source.commit' "$tmp")" =~ ^[0-9a-f]{40}$ ]] \
    || die "the source commit is not a full sha"
  mv "$tmp" "$MANIFEST"

  echo "Release manifest written to ${MANIFEST}:"
  cat "$MANIFEST"
  emit manifest "$MANIFEST"
}

verify() {
  local asset_dir="${ASSET_DIR:-.}" expected_version="${VERSION:-}" expected_commit="${SOURCE_COMMIT:-}"
  local schema version kind stage type source_ref source_commit chart_file chart_sha256 actual
  local note_file declaration_file document path
  local extras='[]' extra_type extra_file extra_sha256

  case "$CHECK_SOURCE_BRANCH" in
    true | false) ;;
    *) die "CHECK_SOURCE_BRANCH must be true or false (got: '$CHECK_SOURCE_BRANCH')" ;;
  esac
  [[ -f "$MANIFEST" ]] || die "manifest '$MANIFEST' not found"
  jq -e 'type == "object"' "$MANIFEST" >/dev/null 2>&1 || die "'$MANIFEST' is not a JSON object"
  schema="$(jq -r '.schemaVersion // empty' "$MANIFEST")"
  [[ "$schema" == "$SCHEMA_VERSION" ]] || die "manifest schemaVersion is '${schema}', expected '${SCHEMA_VERSION}'"
  require "$MANIFEST" .component .version .kind .source.ref .source.commit .source.tag \
    '.artifacts[0].repository' '.artifacts[0].tag' '.artifacts[0].digest' \
    '.artifacts[1].repository' '.artifacts[1].version' '.artifacts[1].file' '.artifacts[1].sha256' \
    .build.run_url
  jq -e '(.documents | type) == "object"' "$MANIFEST" >/dev/null 2>&1 \
    || die "manifest 'documents' must be an object"
  [[ "$(jq -r '.artifacts[0].type' "$MANIFEST")" == image && "$(jq -r '.artifacts[1].type' "$MANIFEST")" == chart ]] \
    || die "manifest artifacts must be the image then the chart"

  version="$(jq -r '.version' "$MANIFEST")"
  kind="$(jq -r '.kind' "$MANIFEST")"
  stage="$(jq -r '.stage // empty' "$MANIFEST")"
  source_ref="$(jq -r '.source.ref' "$MANIFEST")"
  source_commit="$(jq -r '.source.commit' "$MANIFEST")"
  chart_file="$(jq -r '.artifacts[1].file' "$MANIFEST")"
  chart_sha256="$(jq -r '.artifacts[1].sha256' "$MANIFEST")"

  if [[ -n "$expected_version" && "$version" != "$expected_version" ]]; then
    die "manifest version '${version}' does not match the requested version '${expected_version}'"
  fi
  if [[ -n "$expected_commit" && "$source_commit" != "$expected_commit" ]]; then
    die "manifest source.commit '${source_commit}' does not match the draft target '${expected_commit}'"
  fi
  case "$kind" in
    ga) [[ -z "$stage" && "$version" != *-* ]] || die "manifest kind ga with stage '${stage}' and version '${version}'"; type=ga ;;
    prerelease) [[ "$stage" =~ ^(alpha|beta|rc)$ && "$version" == *-${stage}.* ]] || die "manifest kind prerelease with stage '${stage}' and version '${version}'"; type="$stage" ;;
    *) die "manifest kind '${kind}' is neither ga nor prerelease" ;;
  esac
  [[ "$(jq -r '.artifacts[0].tag' "$MANIFEST")" == "$version" && "$(jq -r '.artifacts[1].version' "$MANIFEST")" == "$version" ]] \
    || die "manifest artifacts do not carry the version '${version}'"
  [[ "$(jq -r '.source.tag' "$MANIFEST")" == "${TAG_PREFIX}${version}" ]] || die "manifest source.tag is not '${TAG_PREFIX}${version}'"
  [[ "$source_ref" =~ $RELEASE_BRANCHES ]] || die "manifest source.ref '${source_ref}' is not a releasable branch"
  [[ "$source_commit" =~ ^[0-9a-f]{40}$ ]] || die "manifest source.commit '${source_commit}' is not a full sha"
  [[ "$chart_file" == "$(basename "$chart_file")" && "$chart_file" == *.tgz ]] || die "manifest chart file '${chart_file}' is not a plain .tgz name"

  path="$asset_dir/$chart_file"
  [[ -f "$path" ]] || die "chart package '${path}' was not downloaded"
  actual="$(sha256_of "$path")"
  [[ "$actual" == "$chart_sha256" ]] \
    || die "chart package sha256 ${actual} does not match the manifest ${chart_sha256}: refusing to publish"

  # The artifacts after the image and the chart (a deployment bundle, ...): each file
  # was downloaded and still has the sha256 the manifest froze.
  # Fields are joined with a unit separator: a blank separator (a tab) would swallow an empty field.
  while IFS=$'\037' read -r extra_type extra_file extra_sha256; do
    [[ -n "$extra_type" && "$extra_type" != image && "$extra_type" != chart ]] \
      || die "manifest artifact type '${extra_type}' is not an extra artifact type"
    [[ "$extra_file" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "manifest ${extra_type} file '${extra_file}' is not a plain name"
    [[ "$extra_sha256" =~ ^[0-9a-f]{64}$ ]] || die "manifest ${extra_type} sha256 '${extra_sha256}' is not a hex sha256"
    path="$asset_dir/$extra_file"
    [[ -f "$path" ]] || die "${extra_type} '${path}' was not downloaded"
    actual="$(sha256_of "$path")"
    [[ "$actual" == "$extra_sha256" ]] \
      || die "${extra_type} '${extra_file}' sha256 ${actual} does not match the manifest ${extra_sha256}: refusing to publish"
    extras="$(jq -c --arg type "$extra_type" --arg file "$extra_file" --arg path "$path" --arg sha256 "$extra_sha256" \
      '. + [{type: $type, file: $file, path: $path, sha256: $sha256}]' <<<"$extras")"
  done < <(jq -r '.artifacts[2:][] | [(.type // ""), (.file // ""), (.sha256 // "")] | join("\u001f")' "$MANIFEST")

  note_file="$(jq -r '.documents.release_note.file // empty' "$MANIFEST")"
  declaration_file="$(jq -r '.documents.release_declaration.file // empty' "$MANIFEST")"
  for document in release_note release_declaration; do
    path="$(jq -r ".documents.${document}.file // empty" "$MANIFEST")"
    [[ -n "$path" ]] || continue
    [[ "$path" == "$(basename "$path")" ]] || die "manifest document ${document} file '${path}' is not a plain name"
    [[ -f "$asset_dir/$path" ]] || die "document '${path}' was not downloaded"
    actual="$(sha256_of "$asset_dir/$path")"
    [[ "$actual" == "$(jq -r ".documents.${document}.sha256" "$MANIFEST")" ]] \
      || die "document '${path}' sha256 ${actual} does not match the manifest: refusing to publish"
  done

  if [[ "$CHECK_SOURCE_BRANCH" == true ]]; then
    git rev-parse --verify -q "refs/remotes/origin/${source_ref}" >/dev/null \
      || die "branch '${source_ref}' is not in the checkout (fetch-depth 0, branch fetched): cannot check the source is not stale"
    git merge-base --is-ancestor "$source_commit" "origin/${source_ref}" \
      || die "prepared source commit ${source_commit} is no longer an ancestor of origin/${source_ref}: the candidate is stale and must be prepared again"
    echo "Source commit ${source_commit} is still an ancestor of origin/${source_ref}."
  fi

  echo "Verified manifest for ${TAG_PREFIX}${version} @ ${source_commit:0:7} (${kind}${stage:+ $stage})"
  emit version "$version"
  emit kind "$kind"
  emit stage "$stage"
  emit type "$type"
  emit source-ref "$source_ref"
  emit source-commit "$source_commit"
  emit image-repository "$(jq -r '.artifacts[0].repository' "$MANIFEST")"
  emit image-tag "$(jq -r '.artifacts[0].tag' "$MANIFEST")"
  emit image-digest "$(jq -r '.artifacts[0].digest' "$MANIFEST")"
  emit image-candidate-tag "$(jq -r '.artifacts[0].candidate_tag // empty' "$MANIFEST")"
  emit chart-repository "$(jq -r '.artifacts[1].repository' "$MANIFEST")"
  emit chart-file "$chart_file"
  emit chart-path "$asset_dir/$chart_file"
  emit chart-sha256 "$chart_sha256"
  emit request-id "$(jq -r '.request_id // empty' "$MANIFEST")"
  emit rm-origin "$(jq -r '.rm_origin // empty' "$MANIFEST")"
  emit note-file "$note_file"
  emit declaration-file "$declaration_file"
  emit extra-artifacts-json "$extras"
}

complete() {
  local out="${OUT:-$MANIFEST}" published_at="${PUBLISHED_AT:-$(now_utc)}" run_url="${RUN_URL:-}"
  local digests="${DIGESTS_JSON:-}" tmp
  [[ -n "$digests" ]] || digests='{}'

  [[ -f "$MANIFEST" ]] || die "manifest '$MANIFEST' not found"
  [[ -n "$run_url" ]] || die "RUN_URL is required"
  jq -e 'type == "object" and all(.[]; type == "string" and test("^sha256:[0-9a-f]{64}$"))' <<<"$digests" >/dev/null 2>&1 \
    || die "DIGESTS_JSON must be an object of sha256 digests: '$digests'"
  [[ "$(jq -r '.schemaVersion // empty' "$MANIFEST")" == "$SCHEMA_VERSION" ]] \
    || die "'$MANIFEST' is not a ${SCHEMA_VERSION} manifest"

  tmp="$(mktemp)"
  jq --arg published_at "$published_at" --arg run_url "$run_url" --argjson digests "$digests" '
    . + {publication: {published_at: $published_at, run_url: $run_url, digests: $digests}}' \
    "$MANIFEST" >"$tmp"
  # The frozen part is never edited: refuse to continue if anything but `publication` moved.
  if ! diff <(jq -S 'del(.publication)' "$MANIFEST") <(jq -S 'del(.publication)' "$tmp") >/dev/null; then
    rm -f "$tmp"
    die "completing the manifest would alter its frozen part"
  fi
  mv "$tmp" "$out"
  echo "Release manifest completed in ${out}:"
  jq '.publication' "$out"
  emit manifest "$out"
}

case "$MODE" in
  write) write ;;
  verify) verify ;;
  complete) complete ;;
  *) die "MODE must be write, verify or complete (got: '$MODE')" ;;
esac
