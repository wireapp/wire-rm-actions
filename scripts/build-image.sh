#!/usr/bin/env bash
# Build a container image from a Dockerfile and push it as IMAGE:TAG, never
# overwriting a tag that is already in the registry: its digest is read back
# instead, so a rerun of the same commit is safe. One build per tag: the
# release pipeline promotes this exact digest later, it never rebuilds.
#
# Environment:
#   IMAGE           image repository, e.g. quay.io/wire/my-component (required)
#   DOCKERFILE      path of the Dockerfile (required); a <Dockerfile>.dockerignore
#                   next to it wins over <context>/.dockerignore (BuildKit rule)
#   VERSION         the build version, from the version action (required): the
#                   org.opencontainers.image.version label and the default tag
#   TAG             tag to push (default VERSION), e.g. <version>-candidate-<run>
#   CONTEXT         build context directory (default .)
#   REVISION        source commit (default GITHUB_SHA)
#   CREATED         build time for the org.opencontainers.image.created label,
#                   YYYY-MM-DDTHH:MM:SSZ (default now, UTC)
#   LABELS          more OCI labels, KEY=VALUE lines (title, description, url,
#                   ...): set as label and as annotation like the stamped ones;
#                   never one the action stamps or quay.expires-after
#   PLATFORMS       comma-separated platforms (default linux/amd64)
#   BUILD_ARGS      KEY=VALUE lines, never secrets (they stay in the image history)
#   BUILD_CONTEXTS  name=path lines: extra named contexts (COPY --from=name)
#   TARGET          Dockerfile stage to build (default the last one)
#   PROVENANCE      SLSA provenance attestation: mode=max (default), mode=min,
#                   true (= mode=min) or false
#   SBOM            SBOM attestation: true (default) or false
#   EXPIRES_AFTER   Quay deletes the image after this delay (e.g. 90d): dev
#                   builds only, never a release candidate (Quay expires the
#                   manifest, which the promoted release tag shares)
# The registry login is done beforehand (docker login).
#
# Attestations ride with the image, as extra manifests of its index:
#
#   PROVENANCE  SBOM   pushed
#   mode=max    true   image + provenance (full build inputs) + SBOM   (default)
#   mode=min    true   image + provenance (digest-only) + SBOM
#   false       false  the bare image, a single manifest when single-platform
#
# Prints image=, tag=, digest=, ref= and status= (pushed | present), and
# appends them to $GITHUB_OUTPUT when set.
set -euo pipefail
export LC_ALL=C

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

: "${IMAGE:?IMAGE is required}"
: "${DOCKERFILE:?DOCKERFILE is required}"
: "${VERSION:?VERSION is required}"
tag=${TAG:-$VERSION}
context=${CONTEXT:-.}
revision=${REVISION:-${GITHUB_SHA:-}}
platforms=${PLATFORMS:-linux/amd64}
provenance=${PROVENANCE:-mode=max}
sbom=${SBOM:-true}
expires_after=${EXPIRES_AFTER:-}
created=${CREATED:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}

[[ $IMAGE =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+$ ]] || die "IMAGE '$IMAGE' is not an image repository (registry/namespace/name)"
[[ $tag =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || die "TAG '$tag' is not a valid image tag"
[[ -f $DOCKERFILE ]] || die "DOCKERFILE '$DOCKERFILE' does not exist"
[[ -d $context ]] || die "CONTEXT '$context' is not a directory"
[[ -z $revision || $revision =~ ^[0-9a-f]{40}$ ]] || die "REVISION '$revision' is not a full commit SHA"
[[ $platforms =~ ^[a-z0-9/_.-]+(,[a-z0-9/_.-]+)*$ ]] || die "PLATFORMS '$platforms' is not a comma-separated list of platforms"
[[ $provenance =~ ^(true|false|mode=(min|max))$ ]] || die "PROVENANCE must be mode=max, mode=min, true or false, not '$provenance'"
[[ $sbom =~ ^(true|false)$ ]] || die "SBOM must be true or false, not '$sbom'"
[[ $created =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || die "CREATED must be YYYY-MM-DDTHH:MM:SSZ, not '$created'"
if [[ -n $expires_after ]]; then
  [[ $expires_after =~ ^[1-9][0-9]*[hdw]$ ]] || die "EXPIRES_AFTER must be a number of hours, days or weeks (e.g. 90d), not '$expires_after'"
fi

args=(--file "$DOCKERFILE" --platform "$platforms" --tag "${IMAGE}:${tag}")
while IFS= read -r line; do
  line=${line#"${line%%[![:space:]]*}"}
  [[ -z $line ]] && continue
  [[ $line =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || die "build-args line '${line%%=*}' is not KEY=VALUE"
  args+=(--build-arg "$line")
done <<<"${BUILD_ARGS:-}"
while IFS= read -r line; do
  line=${line#"${line%%[![:space:]]*}"}
  [[ -z $line ]] && continue
  [[ $line =~ ^[a-z0-9][a-z0-9._/-]*=.+ ]] || die "build-contexts line '$line' is not name=path"
  args+=(--build-context "$line")
done <<<"${BUILD_CONTEXTS:-}"
[[ -n ${TARGET:-} ]] && args+=(--target "$TARGET")

# OCI provenance (ADR-0020 rule 8) as labels (docker inspect) and annotations
# (registry UIs, crane): on the manifest, and on the index of a multi-platform
# image (a single-platform push has no index to annotate).
levels=manifest
[[ $platforms == *,* ]] && levels=index,manifest
oci=("org.opencontainers.image.version=$VERSION")
[[ -n $revision ]] && oci+=("org.opencontainers.image.revision=$revision")
if [[ -n ${GITHUB_REPOSITORY:-} ]]; then
  oci+=("org.opencontainers.image.source=${GITHUB_SERVER_URL:-https://github.com}/$GITHUB_REPOSITORY")
fi
oci+=("org.opencontainers.image.created=$created")
# The labels the caller adds: the same label and annotation as the stamped ones. What the action
# stamps itself stays out of reach, so an image never carries two values for one key.
while IFS= read -r line; do
  line=${line#"${line%%[![:space:]]*}"}
  [[ -z $line ]] && continue
  [[ $line =~ ^[a-z0-9][a-z0-9._-]*=. ]] || die "labels line '${line%%=*}' is not KEY=VALUE"
  case ${line%%=*} in
  org.opencontainers.image.version | org.opencontainers.image.revision | org.opencontainers.image.source | org.opencontainers.image.created | quay.expires-after)
    die "label '${line%%=*}' is set by the action" ;;
  esac
  oci+=("$line")
done <<<"${LABELS:-}"
for kv in "${oci[@]}"; do
  args+=(--label "$kv" --annotation "${levels}:$kv")
done
# A label only: Quay reads it from the image config.
[[ -n $expires_after ]] && args+=(--label "quay.expires-after=$expires_after")

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

registry_digest() {
  docker buildx imagetools inspect "$1" --format '{{.Manifest.Digest}}' 2>/dev/null
}

ref="${IMAGE}:${tag}"
if digest=$(registry_digest "$ref") && [[ $digest == sha256:* ]]; then
  echo "::notice::$ref already pushed, not rebuilt nor overwritten"
  status=present
else
  docker buildx build "${args[@]}" "--provenance=$provenance" "--sbom=$sbom" \
    --metadata-file "$work/metadata.json" --push "$context"
  built=$(sed -n 's/.*"containerimage\.digest": *"\(sha256:[0-9a-f]*\)".*/\1/p' "$work/metadata.json" | head -n1)
  # Read from the registry, not the local builder, which is not authoritative.
  digest=$(registry_digest "$ref") || die "$ref is not in the registry after the push"
  [[ -z $built || $built == "$digest" ]] || die "$ref resolves to $digest in the registry, the build pushed $built"
  status=pushed
fi

[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || die "no digest for $ref"

emit image "$IMAGE"
emit tag "$tag"
emit digest "$digest"
emit ref "${IMAGE}@${digest}"
emit status "$status"
