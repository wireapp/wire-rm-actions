#!/usr/bin/env bash
# Promote a candidate image to its release tag by digest, without any rebuild
# (ADR-0020 rule 3): `crane tag` writes a tag against the existing manifest, so
# a multi-arch index keeps its digest. Idempotent: a release tag already at the
# expected digest is a no-op, a release tag at another digest is a hard failure
# (an immutable artifact is never overwritten).
#
# Environment:
#   REPOSITORY         image repository, e.g. quay.io/wire/my-component
#   DIGEST             sha256 digest of the candidate, as the release manifest records it
#   TAG                release tag to write, e.g. 1.41.4-rc.1
#   REGISTRY_USER      registry user; empty when the job is already logged in
#                      (quay-login, docker login)
#   REGISTRY_PASSWORD  registry password, given to crane on stdin only
#
# Needs crane on PATH. Prints digest= (what the release tag resolves to) and
# status= (promoted | present), and appends them to $GITHUB_OUTPUT when set.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REPOSITORY="${REPOSITORY:-}"
DIGEST="${DIGEST:-}"
TAG="${TAG:-}"
REGISTRY_USER="${REGISTRY_USER:-}"
REGISTRY_PASSWORD="${REGISTRY_PASSWORD:-}"

[[ "$REPOSITORY" =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+$ ]] || die "REPOSITORY '$REPOSITORY' is not an image repository"
[[ "$DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] || die "DIGEST '$DIGEST' is not a sha256 digest"
[[ "$TAG" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)\.[0-9]+)?$ ]] || die "TAG '$TAG' is not a release version"
if [[ -n "$REGISTRY_USER" ]]; then
  [[ -n "$REGISTRY_PASSWORD" ]] || die "REGISTRY_PASSWORD is required with REGISTRY_USER"
elif [[ -n "$REGISTRY_PASSWORD" ]]; then
  die "REGISTRY_PASSWORD is set without REGISTRY_USER"
fi
command -v crane >/dev/null 2>&1 || die "crane is not installed"

registry="${REPOSITORY%%/*}"
if [[ -n "$REGISTRY_USER" ]]; then
  printf '%s' "$REGISTRY_PASSWORD" | crane auth login "$registry" --username "$REGISTRY_USER" --password-stdin
fi

# The candidate must still be there: nothing is ever rebuilt at publication.
crane manifest "${REPOSITORY}@${DIGEST}" >/dev/null 2>&1 \
  || die "candidate ${REPOSITORY}@${DIGEST} no longer exists in the registry: it cannot be promoted, prepare the release again"

release_ref="${REPOSITORY}:${TAG}"
status=""
# Resolve BEFORE tagging, never tag-then-check: `crane tag` overwrites an
# existing tag silently.
if existing="$(crane digest "$release_ref" 2>/dev/null)"; then
  if [[ "$existing" == "$DIGEST" ]]; then
    echo "${release_ref} already resolves to ${DIGEST}: already promoted."
    status=present
  else
    die "${release_ref} already exists with digest ${existing}, expected ${DIGEST}: refusing to overwrite a published image"
  fi
else
  crane tag "${REPOSITORY}@${DIGEST}" "$TAG"
  echo "Promoted ${REPOSITORY}@${DIGEST} -> ${release_ref}"
  status=promoted
fi

final="$(crane digest "$release_ref")"
[[ "$final" == "$DIGEST" ]] || die "${release_ref} resolves to ${final} after promotion, expected ${DIGEST}"

emit digest "$final"
emit status "$status"
