#!/usr/bin/env bash
# Validate the dispatch inputs of a prepare-release or publish-release workflow
# (ADR-0021 section 1), before any checkout: a bad input fails the run here,
# with the reason, and nothing else has happened. MODE selects the workflow:
#
#   prepare  (default) the nine inputs of prepare-release, below;
#   publish  VERSION, RELEASE_ID, REQUEST_ID and RM_ORIGIN of publish-release, further below.
#
# Environment, prepare (each one the dispatch input of the same name):
#   SOURCE_BRANCH        must match SOURCE_BRANCHES
#   RELEASE_TYPE         ga | alpha | beta | rc
#   VERSION_BUMP         patch | minor | major
#   FORCE                true | false (empty means false)
#   REQUEST_ID           empty, or a UUID4 (the release manager request)
#   EXPECTED_VERSION     empty, or X.Y.Z[-(alpha|beta|rc).N]
#   RELEASE_NOTE         free text, only counted in the size budget
#   RELEASE_DECLARATION  empty, or the JSON text of a declaration object
#   RM_ORIGIN            empty, or staging | prod | local (a developer's release
#                        manager: accepted with a warning); required with
#                        REQUEST_ID, refused without
#   SOURCE_BRANCHES      regex of the releasable branches
#                        (default ^(dev|release/[0-9]+\.[0-9]+)$)
#
# The nine inputs together must not exceed 60 000 characters, the budget the
# release manager applies before dispatching (ADR-0021 section 1).
#
# Prints rm-driven= (true when REQUEST_ID is set), force= (true | false) and
# release-type=, and appends them to $GITHUB_OUTPUT when set.
#
# Environment, publish:
#   VERSION              X.Y.Z[-(alpha|beta|rc).N]
#   RELEASE_ID           empty, or the numeric id of the draft release
#   REQUEST_ID           empty, or a lower-case UUID4
#   RM_ORIGIN            empty, or staging | prod | local (accepted with a warning); it goes
#                        with REQUEST_ID: both or neither
#
# No size budget in this mode. Prints rm-driven= and release-type= (ga without a suffix,
# else alpha | beta | rc, derived from VERSION), and appends them to $GITHUB_OUTPUT when set.
set -euo pipefail
export LC_ALL=C
# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

MODE="${MODE:-prepare}"
VERSION="${VERSION:-}"
RELEASE_ID="${RELEASE_ID:-}"
SOURCE_BRANCH="${SOURCE_BRANCH:-}"
RELEASE_TYPE="${RELEASE_TYPE:-}"
VERSION_BUMP="${VERSION_BUMP:-}"
FORCE="${FORCE:-false}"
REQUEST_ID="${REQUEST_ID:-}"
EXPECTED_VERSION="${EXPECTED_VERSION:-}"
RELEASE_NOTE="${RELEASE_NOTE:-}"
RELEASE_DECLARATION="${RELEASE_DECLARATION:-}"
RM_ORIGIN="${RM_ORIGIN:-}"
SOURCE_BRANCHES="${SOURCE_BRANCHES:-^(dev|release/[0-9]+\.[0-9]+)$}"

readonly UUID4_RE='^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
readonly VERSION_RE='^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)\.[0-9]+)?$'
readonly BUDGET=60000

prepare() {
  [[ -n "$SOURCE_BRANCH" ]] || die "source_branch is required"
  [[ "$SOURCE_BRANCH" =~ $SOURCE_BRANCHES ]] \
    || die "source_branch '$SOURCE_BRANCH' is not a releasable branch (expected to match $SOURCE_BRANCHES)"

  case "$RELEASE_TYPE" in
    ga | alpha | beta | rc) ;;
    *) die "type must be one of ga, alpha, beta, rc (got: '$RELEASE_TYPE')" ;;
  esac

  case "$VERSION_BUMP" in
    patch | minor | major) ;;
    *) die "version_bump must be one of patch, minor, major (got: '$VERSION_BUMP')" ;;
  esac

  [[ -n "$FORCE" ]] || FORCE=false
  case "$FORCE" in
    true | false) ;;
    *) die "force must be true or false (got: '$FORCE')" ;;
  esac

  if [[ -n "$REQUEST_ID" ]]; then
    [[ "$REQUEST_ID" =~ $UUID4_RE ]] || die "request_id '$REQUEST_ID' is not a lower-case UUID4"
  fi

  if [[ -n "$EXPECTED_VERSION" ]]; then
    [[ "$EXPECTED_VERSION" =~ $VERSION_RE ]] \
      || die "expected_version '$EXPECTED_VERSION' is not X.Y.Z or X.Y.Z-<alpha|beta|rc>.N"
  fi

  if [[ -n "$RM_ORIGIN" ]]; then
    case "$RM_ORIGIN" in
      staging | prod) ;;
      local)
        echo "::warning title=rm_origin local::request ${REQUEST_ID:-(none)} comes from a local release manager: no deployed release manager follows this run" >&2
        ;;
      *) die "rm_origin must be staging, prod or local (got: '$RM_ORIGIN')" ;;
    esac
    [[ -n "$REQUEST_ID" ]] || die "rm_origin '$RM_ORIGIN' is set without a request_id"
  elif [[ -n "$REQUEST_ID" ]]; then
    die "rm_origin is required when request_id is set (got request_id '$REQUEST_ID')"
  fi

  # A declaration arrives as the JSON text of an object (ADR-0021 section 1); its
  # content is checked by release-documents once the version is known.
  if [[ -n "$RELEASE_DECLARATION" ]]; then
    printf '%s' "$RELEASE_DECLARATION" | jq -e 'type == "object"' >/dev/null 2>&1 \
      || die "release_declaration is not the JSON text of an object"
  fi

  # Characters, not bytes: jq counts code points, like the release manager.
  total="$(jq -n \
    --arg a "$SOURCE_BRANCH" --arg b "$RELEASE_TYPE" --arg c "$VERSION_BUMP" --arg d "$FORCE" \
    --arg e "$REQUEST_ID" --arg f "$EXPECTED_VERSION" --arg g "$RELEASE_NOTE" \
    --arg h "$RELEASE_DECLARATION" --arg i "$RM_ORIGIN" \
    '[$a, $b, $c, $d, $e, $f, $g, $h, $i] | map(length) | add')"
  (( total <= BUDGET )) \
    || die "the inputs total ${total} characters, above the ${BUDGET} budget (ADR-0021): shorten release_note or release_declaration"

  echo "Validated release inputs: source_branch=${SOURCE_BRANCH} type=${RELEASE_TYPE} version_bump=${VERSION_BUMP} force=${FORCE} request_id=${REQUEST_ID:-(none)} rm_origin=${RM_ORIGIN:-(none)} expected_version=${EXPECTED_VERSION:-(none)} (${total} characters, budget ${BUDGET})"
  if [[ -n "$REQUEST_ID" ]]; then
    emit rm-driven true
  else
    emit rm-driven false
  fi
  emit force "$FORCE"
  emit release-type "$RELEASE_TYPE"
}

publish() {
  local release_type
  [[ "$VERSION" =~ $VERSION_RE ]] \
    || die "version '$VERSION' is not a release version (X.Y.Z or X.Y.Z-<alpha|beta|rc>.N)"
  if [[ -n "$RELEASE_ID" ]]; then
    [[ "$RELEASE_ID" =~ ^[0-9]+$ ]] || die "release_id '$RELEASE_ID' is not numeric"
  fi
  if [[ -n "$REQUEST_ID" ]]; then
    [[ "$REQUEST_ID" =~ $UUID4_RE ]] || die "request_id '$REQUEST_ID' is not a lower-case UUID4"
  fi
  if [[ -n "$RM_ORIGIN" ]]; then
    case "$RM_ORIGIN" in
      staging | prod) ;;
      local)
        echo "::warning title=rm_origin local::request ${REQUEST_ID:-(none)} comes from a local release manager: no deployed release manager follows this run" >&2
        ;;
      *) die "rm_origin '$RM_ORIGIN' is not staging, prod or local" ;;
    esac
  fi
  if [[ -n "$REQUEST_ID" && -z "$RM_ORIGIN" ]] || [[ -z "$REQUEST_ID" && -n "$RM_ORIGIN" ]]; then
    die "request_id and rm_origin go together (got request_id '$REQUEST_ID', rm_origin '$RM_ORIGIN')"
  fi

  if [[ "$VERSION" == *-* ]]; then
    release_type="${VERSION#*-}"
    release_type="${release_type%%.*}"
  else
    release_type=ga
  fi
  echo "Inputs validated for v${VERSION}."
  if [[ -n "$REQUEST_ID" ]]; then
    emit rm-driven true
  else
    emit rm-driven false
  fi
  emit release-type "$release_type"
}

case "$MODE" in
  prepare) prepare ;;
  publish) publish ;;
  *) die "MODE must be prepare or publish (got: '$MODE')" ;;
esac
