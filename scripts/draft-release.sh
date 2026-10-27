#!/usr/bin/env bash
# The draft GitHub Release of a release candidate (ADR-0021 sections 3 and 4): created at
# preparation with every artifact as an asset, resolved and downloaded at publication, then
# published LAST, which creates the tag. Three modes, selected by MODE:
#
#   create   refuse when a release (draft or published) already has the tag, then create the
#            draft on TARGET with TITLE, BODY_FILE and ASSETS, and resolve its id (drafts are
#            absent from /releases/tags/{tag}: list and filter, retried, the list being
#            eventually consistent; more than one match is a conflict);
#   resolve  find the draft (RELEASE_ID, else the only draft with the tag), check it is a
#            draft with the expected tag and target, check the tag state, and download its
#            assets into ASSET_DIR (DOWNLOAD); the sha256 checks are release-manifest verify;
#   publish  the same checks, replace REPLACE_ASSETS on the draft, decide make_latest and
#            publish the draft (draft=false), which creates the tag on its target commit.
#
# The tag state: absent, or present at the target commit (a publication completed earlier);
# present at another commit fails.
#
# Inputs (environment): GH_TOKEN, REPO (owner/name, default $GITHUB_REPOSITORY), MODE,
# VERSION, TAG_PREFIX (default v);
# create: TARGET (full commit sha), TITLE (default the tag), BODY_FILE, PRERELEASE (auto: the
#   version has a pre-release suffix), ASSETS (paths, one per line), CREATE_ATTEMPTS (5),
#   CREATE_DELAY (3 seconds);
# resolve, publish: RELEASE_ID, EXPECTED_COMMIT;
# resolve: ASSET_DIR (default $RUNNER_TEMP/release-assets), DOWNLOAD (none, manifest,
#   manifest-files, all), MANIFEST_NAME (release-manifest.json), ASSETS (more asset names);
# publish: REPLACE_ASSETS (<path> or <name>=<path>, one per line), MAKE_LATEST (auto, true,
#   false, legacy), SOURCE_REF, LATEST_BRANCHES (regex, default ^dev$).
#
# Outputs (stdout and $GITHUB_OUTPUT): id, tag, url; create: published-url; resolve:
# target-commitish, prerelease, tag-exists, asset-dir, manifest, body-file; publish:
# make-latest.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

MODE="${MODE:-}"
REPO="${REPO:-${GITHUB_REPOSITORY:-}}"
VERSION="${VERSION:-}"
TAG_PREFIX="${TAG_PREFIX-v}"
RELEASE_ID="${RELEASE_ID:-}"
EXPECTED_COMMIT="${EXPECTED_COMMIT:-}"
MANIFEST_NAME="${MANIFEST_NAME:-release-manifest.json}"
SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"

# A release asset name: one plain file name, never a path.
plain_name() {
  [[ "$1" =~ ^[A-Za-z0-9._+-]+$ && "$1" != . && "$1" != .. ]]
}

# The releases with the tag, drafts included, as a JSON array.
releases_for_tag() {
  gh api --paginate "repos/${REPO}/releases?per_page=100" \
    | jq -cs --arg tag "$1" '[(add // [])[] | select(.tag_name == $tag)]'
}

assets_of() {
  gh api --paginate "repos/${REPO}/releases/$1/assets?per_page=100" | jq -cs 'add // []'
}

# The commit a tag points to (annotated tags dereferenced), empty when the tag does not exist.
tag_commit() {
  local tag="$1" object type sha
  object="$(gh api "repos/${REPO}/git/matching-refs/tags/${tag}" \
    | jq -c --arg ref "refs/tags/${tag}" '[.[] | select(.ref == $ref) | .object] | first')"
  [[ "$object" != null ]] || return 0
  type="$(jq -r '.type' <<<"$object")"
  sha="$(jq -r '.sha' <<<"$object")"
  while [[ "$type" == tag ]]; do
    object="$(gh api "repos/${REPO}/git/tags/${sha}" | jq -c '.object')"
    type="$(jq -r '.type' <<<"$object")"
    sha="$(jq -r '.sha' <<<"$object")"
  done
  printf '%s\n' "$sha"
}

# check_tag_state <tag> <commit>: prints true when the tag exists (at the commit), false when
# it does not; fails when it exists at another commit.
check_tag_state() {
  local tag="$1" commit="$2" existing
  existing="$(tag_commit "$tag")" || die "could not read the tag ${tag} of ${REPO}"
  if [[ -z "$existing" ]]; then
    echo "Tag ${tag} does not exist yet: it is created when the release is published." >&2
    echo false
  elif [[ "$existing" == "$commit" ]]; then
    echo "Tag ${tag} already exists at the expected commit ${commit}." >&2
    echo true
  else
    die "tag ${tag} already exists at ${existing}, expected ${commit}: refusing to publish"
  fi
}

# The draft of the tag, checked: prints the release JSON.
resolve_draft() {
  local tag="$1" id="$RELEASE_ID" matches count data
  if [[ -z "$id" ]]; then
    # GitHub permits several drafts sharing a tag_name: exactly one must match.
    matches="$(releases_for_tag "$tag")" || die "could not list the releases of ${REPO}"
    count="$(jq '[.[] | select(.draft == true)] | length' <<<"$matches")"
    [[ "$count" -eq 1 ]] || die "expected exactly one draft release for tag ${tag}, found ${count}"
    id="$(jq -r '[.[] | select(.draft == true)][0].id' <<<"$matches")"
  fi
  data="$(gh api "repos/${REPO}/releases/${id}")" || die "could not read release ${id} of ${REPO}"
  [[ "$(jq -r '.draft' <<<"$data")" == true ]] \
    || die "release ${id} (tag $(jq -r '.tag_name' <<<"$data")) is not a draft: refusing to publish"
  [[ "$(jq -r '.tag_name' <<<"$data")" == "$tag" ]] \
    || die "release ${id} has tag_name '$(jq -r '.tag_name' <<<"$data")', expected '${tag}'"
  if [[ -n "$EXPECTED_COMMIT" && "$(jq -r '.target_commitish' <<<"$data")" != "$EXPECTED_COMMIT" ]]; then
    die "release ${id} targets '$(jq -r '.target_commitish' <<<"$data")', expected '${EXPECTED_COMMIT}'"
  fi
  printf '%s\n' "$data"
}

create() {
  local tag="$1" target="${TARGET:-}" title="${TITLE:-}" body="${BODY_FILE:-}"
  local prerelease="${PRERELEASE:-auto}" attempts="${CREATE_ATTEMPTS:-5}" delay="${CREATE_DELAY:-3}"
  local -a files=() args=()
  local line names matches count id url attempt existing

  [[ "$target" =~ ^[0-9a-f]{40}$ ]] || die "target '${target}' is not a full commit sha"
  [[ -n "$title" ]] || title="$tag"
  [[ -z "$body" || -f "$body" ]] || die "body file '${body}' not found"
  case "$prerelease" in
    auto) if [[ "$VERSION" == *-* ]]; then prerelease=true; else prerelease=false; fi ;;
    true | false) ;;
    *) die "prerelease must be auto, true or false (got: '${prerelease}')" ;;
  esac
  while IFS= read -r line; do
    [[ -n "${line//[[:space:]]/}" ]] || continue
    [[ -f "$line" ]] || die "asset '${line}' not found"
    plain_name "$(basename "$line")" || die "asset name '$(basename "$line")' is not a plain file name"
    files+=("$line")
  done <<<"${ASSETS:-}"
  if [[ ${#files[@]} -gt 0 ]]; then
    names="$(for line in "${files[@]}"; do basename "$line"; done | sort | uniq -d)"
    [[ -z "$names" ]] || die "two assets share the name: ${names}"
  fi

  # Repeated right before the creation, to narrow the race window (ci-gate checks it earlier).
  existing="$(releases_for_tag "$tag" | jq -r 'map(.id | tostring) | join(", ")')" \
    || die "could not list the releases of ${REPO}"
  [[ -z "$existing" ]] || die "a draft or published release already exists for tag ${tag} (id(s): ${existing})"

  args=(--repo "$REPO" --target "$target" --title "$title" --draft)
  if [[ -n "$body" ]]; then args+=(--notes-file "$body"); else args+=(--notes ""); fi
  [[ "$prerelease" == false ]] || args+=(--prerelease)
  # tail -n1: only the URL is wanted.
  url="$(gh release create "$tag" ${files[@]+"${files[@]}"} "${args[@]}" | tail -n1)" \
    || die "gh release create ${tag} failed"
  echo "Created draft release: ${url}"

  id=""
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    matches="$(releases_for_tag "$tag")" || die "could not list the releases of ${REPO}"
    count="$(jq 'length' <<<"$matches")"
    if [[ "$count" -eq 1 ]]; then
      id="$(jq -r '.[0].id' <<<"$matches")"
      url="$(jq -r '.[0].html_url // empty' <<<"$matches")"
      break
    fi
    [[ "$count" -le 1 ]] || die "found ${count} releases for ${tag}: refusing to guess which draft to publish"
    echo "the releases list has not caught up with ${tag} yet (attempt ${attempt}/${attempts}), retrying in ${delay}s"
    sleep "$delay"
  done
  [[ -n "$id" ]] || die "${tag} was created but never appeared in the releases list after ${attempts} attempts. The draft exists and must be deleted before preparing this version again."
  [[ -n "$url" ]] || url="${SERVER_URL}/${REPO}/releases"

  emit id "$id"
  emit tag "$tag"
  emit url "$url"
  emit published-url "${SERVER_URL}/${REPO}/releases/tag/${tag}"
  summary "### Draft release ready" "" \
    "[Review the draft ${tag}](${url}): this link works while the release is a draft." "" \
    "Once published it becomes [\`${tag}\`](${SERVER_URL}/${REPO}/releases/tag/${tag}); that URL 404s until then, because the tag does not exist yet."
  if [[ ${#files[@]} -gt 0 ]]; then
    summary "" "| Asset |" "| --- |"
    for line in "${files[@]}"; do summary "| \`$(basename "$line")\` |"; done
  fi
}

download_asset() {
  local assets="$1" name="$2" dir="$3" id
  plain_name "$name" || die "asset name '${name}' is not a plain file name"
  id="$(jq -r --arg name "$name" '.[] | select(.name == $name) | .id' <<<"$assets")"
  [[ -n "$id" ]] || die "asset '${name}' not found on the draft release"
  # A draft asset's browser_download_url 404s: the asset API with an octet-stream Accept.
  gh api -H "Accept: application/octet-stream" "repos/${REPO}/releases/assets/${id}" >"${dir}/${name}" \
    || die "could not download asset '${name}'"
  echo "Downloaded ${name}"
}

resolve() {
  local tag="$1" data id target assets dir="${ASSET_DIR:-}" download="${DOWNLOAD:-manifest}"
  local manifest="" body_file tag_exists line
  local -a names=()

  case "$download" in none | manifest | manifest-files | all) ;; *)
    die "download must be none, manifest, manifest-files or all (got: '${download}')" ;;
  esac
  plain_name "$MANIFEST_NAME" || die "manifest-name '${MANIFEST_NAME}' is not a plain file name"
  [[ -n "$dir" ]] || dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/release-assets"

  data="$(resolve_draft "$tag")"
  id="$(jq -r '.id' <<<"$data")"
  target="$(jq -r '.target_commitish' <<<"$data")"
  echo "Resolved draft release ${id} (tag ${tag}, target ${target})"
  tag_exists="$(check_tag_state "$tag" "$target")"

  mkdir -p "$dir"
  body_file="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/draft-release-body.XXXXXX")"
  jq -j '.body // ""' <<<"$data" >"$body_file"

  if [[ "$download" != none || -n "${ASSETS:-}" ]]; then
    assets="$(assets_of "$id")" || die "could not list the assets of release ${id}"
    case "$download" in
      manifest | manifest-files) names+=("$MANIFEST_NAME") ;;
      all) while IFS= read -r line; do names+=("$line"); done < <(jq -r '.[].name' <<<"$assets") ;;
    esac
    if [[ "$download" == manifest || "$download" == manifest-files ]]; then
      download_asset "$assets" "$MANIFEST_NAME" "$dir"
      manifest="${dir}/${MANIFEST_NAME}"
    fi
    if [[ "$download" == manifest-files ]]; then
      # Every file the manifest names: chart packages and release documents.
      jq -e 'type == "object"' "$manifest" >/dev/null 2>&1 || die "${MANIFEST_NAME} is not a JSON object"
      while IFS= read -r line; do
        [[ -n "$line" ]] && names+=("$line")
      done < <(jq -r '[((.artifacts // [])[] | .file? // empty), ((.documents // {})[] | .file? // empty)] | unique | .[]' "$manifest")
    fi
    while IFS= read -r line; do
      line="${line//[[:space:]]/}"
      [[ -n "$line" ]] && names+=("$line")
    done <<<"${ASSETS:-}"
    if [[ ${#names[@]} -gt 0 ]]; then
      while IFS= read -r line; do
        [[ "$line" == "$MANIFEST_NAME" && -n "$manifest" ]] && continue
        download_asset "$assets" "$line" "$dir"
      done < <(printf '%s\n' "${names[@]}" | sort -u)
    fi
    if [[ "$download" == all && -f "${dir}/${MANIFEST_NAME}" ]]; then
      manifest="${dir}/${MANIFEST_NAME}"
    fi
  fi

  emit id "$id"
  emit tag "$tag"
  emit url "$(jq -r '.html_url // ""' <<<"$data")"
  emit target-commitish "$target"
  emit prerelease "$(jq -r '.prerelease' <<<"$data")"
  emit tag-exists "$tag_exists"
  emit asset-dir "$dir"
  emit manifest "$manifest"
  emit body-file "$body_file"
}

make_latest() {
  local data="$1" value="${MAKE_LATEST:-auto}" source_ref="${SOURCE_REF:-}"
  local branches="${LATEST_BRANCHES-^dev$}" refs ref t newer=""
  case "$value" in
    true | false | legacy) echo "$value"; return ;;
    auto) ;;
    *) die "make-latest must be auto, true, false or legacy (got: '${value}')" ;;
  esac
  # A GA from a latest branch is Latest, unless a newer GA went out while the approval waited.
  if [[ "$(jq -r '.prerelease' <<<"$data")" == true || "$VERSION" == *-* ]]; then
    echo false
    return
  fi
  if [[ -n "$branches" ]]; then
    [[ -n "$source_ref" ]] || die "make-latest auto needs the source-ref of a GA (or an empty latest-branches)"
    if [[ ! "$source_ref" =~ $branches ]]; then
      echo "A GA from ${source_ref}: not the Latest release." >&2
      echo false
      return
    fi
  fi
  refs="$(gh api "repos/${REPO}/git/matching-refs/tags/${TAG_PREFIX}" | jq -r '.[].ref')" \
    || die "could not list the tags of ${REPO}"
  while IFS= read -r ref; do
    t="${ref#refs/tags/}"
    [[ "$t" == "$TAG_PREFIX"* ]] || continue
    t="${t#"$TAG_PREFIX"}"
    [[ "$t" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || continue
    if [[ "$("$here/semver.sh" compare "$t" "$VERSION")" == 1 ]]; then newer="${TAG_PREFIX}${t}"; break; fi
  done <<<"$refs"
  if [[ -n "$newer" ]]; then
    warn "${newer} is already released and newer than ${TAG_PREFIX}${VERSION}: publishing with make_latest=false so the newer release keeps the Latest badge."
    echo false
    return
  fi
  echo true
}

content_type() {
  case "$1" in
    *.json) echo application/json ;;
    *.md) echo text/markdown ;;
    *.tgz | *.tar.gz) echo application/gzip ;;
    *.zip) echo application/zip ;;
    *) echo application/octet-stream ;;
  esac
}

replace_assets() {
  local data="$1" id upload line name path assets old
  id="$(jq -r '.id' <<<"$data")"
  upload="$(jq -r '.upload_url // ""' <<<"$data")"
  upload="${upload%%\{*}"
  [[ -n "$upload" ]] || upload="https://uploads.github.com/repos/${REPO}/releases/${id}/assets"
  while IFS= read -r line; do
    [[ -n "${line//[[:space:]]/}" ]] || continue
    if [[ "$line" == *=* ]]; then name="${line%%=*}"; path="${line#*=}"; else path="$line"; name="$(basename "$line")"; fi
    plain_name "$name" || die "asset name '${name}' is not a plain file name"
    [[ -f "$path" ]] || die "asset '${path}' not found"
    assets="$(assets_of "$id")" || die "could not list the assets of release ${id}"
    old="$(jq -r --arg name "$name" '.[] | select(.name == $name) | .id' <<<"$assets")"
    if [[ -n "$old" ]]; then
      gh api --method DELETE "repos/${REPO}/releases/assets/${old}" >/dev/null || die "could not delete asset '${name}'"
    fi
    gh api --method POST -H "Content-Type: $(content_type "$name")" "${upload}?name=${name}" --input "$path" >/dev/null \
      || die "could not upload asset '${name}'"
    echo "Replaced asset ${name} with ${path}"
  done <<<"${REPLACE_ASSETS:-}"
}

publish() {
  local tag="$1" data id target latest url
  data="$(resolve_draft "$tag")"
  id="$(jq -r '.id' <<<"$data")"
  target="$(jq -r '.target_commitish' <<<"$data")"
  check_tag_state "$tag" "$target" >/dev/null
  latest="$(make_latest "$data")"
  replace_assets "$data"
  # draft is a boolean (-F), make_latest a string enum (-f). The tag is born here.
  url="$(gh api --method PATCH "repos/${REPO}/releases/${id}" -F draft=false -f "make_latest=${latest}" | jq -r '.html_url // ""')" \
    || die "could not publish release ${id}"
  echo "Published release ${tag} (make_latest=${latest})"
  emit id "$id"
  emit tag "$tag"
  emit url "$url"
  emit make-latest "$latest"
}

main() {
  local tag
  [[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "REPO '${REPO}' is not owner/name"
  [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || die "VERSION '${VERSION}' is not a release version"
  [[ "$TAG_PREFIX" =~ ^[A-Za-z0-9._/-]*$ ]] || die "tag-prefix '${TAG_PREFIX}' has unexpected characters"
  [[ -z "$RELEASE_ID" || "$RELEASE_ID" =~ ^[0-9]+$ ]] || die "release-id '${RELEASE_ID}' is not numeric"
  [[ -z "$EXPECTED_COMMIT" || "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "expected-commit '${EXPECTED_COMMIT}' is not a full commit sha"
  tag="${TAG_PREFIX}${VERSION}"
  case "$MODE" in
    create) create "$tag" ;;
    resolve) resolve "$tag" ;;
    publish) publish "$tag" ;;
    *) die "MODE must be create, resolve or publish (got: '${MODE}')" ;;
  esac
}

main "$@"
